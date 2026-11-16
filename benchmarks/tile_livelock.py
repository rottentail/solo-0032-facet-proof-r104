"""A legal request whose first high-sample tile exceeds the whole 45 s budget.

Limits admit 40000 source faces and a 512x512 canvas. TileEngine commits a
tile only after the whole 64x64 window is rasterized, and the 45 s checkpoint
raises inside rasterize(), so a single unfinished window leaves no durable
progress. If that window alone needs more than 45 s, every retry restarts it
and the exposure can never succeed, no matter how many times it is retried.

Reproduction without touching internals: place 80 copies of a 500-face wide
fan so their dense centres sit in the top-left tile (ordinal 0 is rendered
first). Then run the worker repeatedly with explicit retries.

Recorded: attempt wall time, committed tiles, terminal state, whether a plate
exists, and whether the reservation is still held.
"""
import json
import os
import sys
import time

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/benchmarks")

from lib import Harness, fan_mesh  # noqa: E402

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def main():
    harness = Harness(capacity=2 ** 22)
    try:
        mesh = fan_mesh(500, 1.0)
        harness.mesh = harness.call("POST", "meshes", mesh)
        pigment = harness.call("POST", "pigments", {"name": "p",
                                                    "color": [0.2, 0.6, 0.6],
                                                    "two_sided": True})
        assembly = harness.call("POST", "assemblies", {
            "name": "a", "lens": {"eye": [0, 0, 5], "projection": "orthographic",
                                  "span": 2.0}})
        harness.call("PUT", "assemblies/" + assembly["id"], {
            "revision": 1,
            "placements": [{"key": "p%02d" % i, "mesh_id": harness.mesh["id"],
                            "pigment_id": pigment["id"],
                            "transform": {"translation": [-0.95, 0.95, 0.0]}}
                           for i in range(80)]})
        harness.seal = harness.call("POST", "assemblies/" + assembly["id"] + "/seal",
                                    {"revision": 2})
        exposure = harness.submit("livelock", 512, 512, 1)
        rows = []
        for attempt in range(1, 6):
            started = time.monotonic()
            result = harness.app.worker.run_one()
            elapsed = time.monotonic() - started
            progress = harness.call("GET", "exposures/" + exposure["id"] + "/progress")
            rows.append({"attempt": attempt, "state": result.get("state"),
                         "error": (result.get("error") or {}).get("error"),
                         "wall_s": round(elapsed, 2),
                         "committed_tiles": progress["committed_tiles"],
                         "total_tiles": progress["total_tiles"]})
            print(json.dumps(rows[-1]), flush=True)
            if result.get("state") != "failed":
                break
            harness.call("POST", "exposures/" + exposure["id"] + "/retry", {})
        final = harness.call("GET", "exposures/" + exposure["id"])
        out = {"request": {"width": 512, "height": 512, "samples": 1,
                           "source_faces": 40000,
                           "geometry": "80 wide fans, dense centres in tile ordinal 0"},
               "attempts": rows, "attempts_run": len(rows),
               "final_state": final["state"], "final_error": final["error"],
               "plate_id": final["plate_id"],
               "capacity_still_reserved": harness.call("GET", "resources")["reserved"],
               "meaning": "No attempt can commit even the first tile; retrying cannot "
                          "move this exposure toward success. Capacity stays reserved "
                          "while it is queued."}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        open(os.path.join(RESULTS, "livelock_real_run.json"), "w").write(
            json.dumps(out, ensure_ascii=False, indent=2))
    finally:
        harness.cleanup()


if __name__ == "__main__":
    main()
