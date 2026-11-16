"""Behaviour under a hard address-space limit (simulated small host).

Runs a max-size legal render in a child with RLIMIT_AS set, so allocation
failure surfaces as MemoryError rather than a cgroup SIGKILL. Verifies:
  * the exposure reaches a definite terminal state,
  * capacity is released,
  * committed tile progress survives and a retry (under a larger limit)
    completes from that progress,
  * the process itself does not die or corrupt the database.
"""
import json
import os
import resource
import subprocess
import sys
import tempfile
import shutil

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/benchmarks")

CHILD = r"""
import json, resource, sys, time
limit_mb = int(sys.argv[2])
resource.setrlimit(resource.RLIMIT_AS, (limit_mb*1024*1024, limit_mb*1024*1024))
sys.path.insert(0, '/workspace')
from facetproof.application import Application
app = Application(sys.argv[1])
started = time.monotonic()
try:
    result = app.worker.run_one()
    error = result.get("error")
    out = {"state": result.get("state"), "exposure_id": result.get("exposure_id"),
           "error": (error.get("error") if isinstance(error, dict) else error),
           "wall_s": round(time.monotonic()-started, 2)}
except MemoryError:
    out = {"state": "uncaught_memory_error", "wall_s": round(time.monotonic()-started, 2)}
print(json.dumps(out))
"""


def main():
    root = tempfile.mkdtemp(prefix="facet-memlimit-")
    try:
        from lib import Harness, fan_mesh, grid_mesh  # noqa: E402
        from facetproof.application import Application  # noqa: E402

        h = Harness(root)
        h.setup(grid_mesh(19602, 1.0),
                lens={"eye": [0, 0, 5], "projection": "orthographic", "span": 2.0})
        exposure = h.submit("mem", 512, 512, 2)
        del h
        observations = []
        # Try progressively larger limits, each time on a fresh child.
        for limit in (40, 48, 56, 64, 72, 80):
            child = subprocess.run([sys.executable, "-c", CHILD, root, str(limit)],
                                   capture_output=True, text=True, timeout=300)
            try:
                result = json.loads(child.stdout.strip().splitlines()[-1])
            except Exception:
                result = {"state": "child_crash", "stderr": child.stderr[-800:],
                          "returncode": child.returncode}
            db = Application(root)
            state = db.exposures.get(exposure["id"])
            progress = db.tiles.progress(exposure["id"])
            capacity = db.resources.snapshot()["reserved"]
            observations.append({"limit_mb": limit, "child": result,
                                 "exposure_state": state["state"],
                                 "exposure_error": state["error"],
                                 "plate_id": state["plate_id"],
                                 "progress": {k: progress[k] for k in
                                              ("committed_tiles", "total_tiles")},
                                 "capacity_reserved": capacity})
            print(json.dumps(observations[-1]))
            if state["state"] == "succeeded":
                break
            if state["state"] == "failed":
                db.exposures.retry(exposure["id"])
        # Final unlimited attempt should reuse tiles and finish.
        db = Application(root)
        final = db.worker.run_one()
        state = db.exposures.get(exposure["id"])
        out = {"scenario": "memory_limit", "observations": observations,
               "final_attempt": final.get("state"),
               "final_state": state["state"], "final_error": state["error"],
               "final_progress": db.tiles.progress(exposure["id"]),
               "plate_verify": db.plates.verify(state["plate_id"])["valid"]
               if state["plate_id"] else None,
               "capacity_after": db.resources.snapshot()["reserved"]}
        print(json.dumps(out, indent=2))
        open("/workspace/benchmarks/results/memory_limit.json", "w").write(
            json.dumps(out, indent=2))
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
