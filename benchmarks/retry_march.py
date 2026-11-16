"""March a legal-but-slow exposure to completion using repeated retry.

Limits allow 40000 source faces and 512x512 s2, but the worker has a hard
45 s budget per attempt. This script quantifies how many attempts a legal
maximum-size job needs and whether the tile checkpoint actually lets it
converge (a definite terminal state) or livelock.
"""
import json
import sys
import time

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/benchmarks")

from lib import Harness, fan_mesh  # noqa: E402


def main():
    faces_per_placement = 9000
    placements = 4
    width = height = 256
    samples = 1
    mesh = fan_mesh(faces_per_placement, 1.0)
    h = Harness()
    h.mesh = h.call("POST", "meshes", mesh)
    h.pigment = h.call("POST", "pigments", {"name": "p", "color": [0.2, 0.6, 0.6],
                                            "two_sided": True})
    assembly = h.call("POST", "assemblies", {
        "name": "a", "lens": {"eye": [0, 0, 5], "projection": "orthographic", "span": 2.0}})
    h.assembly = h.call("PUT", "assemblies/" + assembly["id"], {
        "revision": 1,
        "placements": [{"key": "p%d" % i, "mesh_id": h.mesh["id"],
                        "pigment_id": h.pigment["id"]} for i in range(placements)]})
    h.seal = h.call("POST", "assemblies/" + assembly["id"] + "/seal", {"revision": 2})
    exposure = h.submit("k", width, height, samples)
    eid = exposure["id"]
    attempts = []
    total = 0.0
    for attempt in range(1, 17):
        started = time.monotonic()
        result = h.app.worker.run_one()
        elapsed = time.monotonic() - started
        total += elapsed
        progress = h.call("GET", "exposures/" + eid + "/progress")
        record = {"attempt": attempt, "state": result.get("state"),
                  "error": (result.get("error") or {}).get("error"),
                  "wall_s": round(elapsed, 3),
                  "committed_tiles": progress["committed_tiles"],
                  "total_tiles": progress["total_tiles"]}
        attempts.append(record)
        if result.get("state") == "succeeded":
            plate = result["plate"]
            record["plate_id"] = plate["id"]
            record["statistics"] = plate["payload"]["statistics"]
            break
        h.call("POST", "exposures/" + eid + "/retry", {})
    final = h.call("GET", "exposures/" + eid)
    out = {"scenario": "retry_march", "source_faces": faces_per_placement * placements,
           "request": {"width": width, "height": height, "samples": samples},
           "attempts": attempts, "total_wall_s": round(total, 3),
           "final_state": final["state"], "final_error": final["error"],
           "capacity_after": h.call("GET", "resources")["reserved"]}
    if final.get("plate_id"):
        plate = h.call("GET", "plates/" + final["plate_id"])
        out["plate_verify"] = h.call("POST", "plates/" + final["plate_id"] + "/verify")
        out["bundle_bytes"] = len(h.call("GET", "plates/" + final["plate_id"] + "/bundle"))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    h.cleanup()


if __name__ == "__main__":
    main()
