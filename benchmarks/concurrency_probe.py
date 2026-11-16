"""Concurrency and storage-growth observations.

1. Two independent processes call /worker/step on the same data root. Verify
   exactly one claims, the other idles or errors, and capacity/plate counts
   stay consistent.
2. Measure CAS byte growth across a timed-out then retried exposure: tiles
   committed before a timeout are reused, but repeated timeouts cannot add
   duplicate bytes for the same window (content-addressed).
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import shutil

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/benchmarks")

from lib import Harness, fan_mesh, grid_mesh  # noqa: E402
from facetproof.application import Application  # noqa: E402

CHILD = r"""
import json, sys, time
sys.path.insert(0, '/workspace')
from facetproof.application import Application
app = Application(sys.argv[1])
start = time.monotonic()
result = app.worker.run_one()
print(json.dumps({"state": result.get("state"), "ms": round((time.monotonic()-start)*1000, 1),
                  "exposure_id": result.get("exposure_id"),
                  "error": (result.get("error") or {}).get("error")}))
"""


def dir_bytes(path):
    total = 0
    for base, _, files in os.walk(path):
        for name in files:
            total += os.path.getsize(os.path.join(base, name))
    return total


def concurrency_case():
    root = tempfile.mkdtemp(prefix="facet-concurrent-")
    try:
        h = Harness(root)
        h.setup(grid_mesh(5000, 1.0), lens={"eye": [0, 0, 5], "projection": "orthographic",
                                            "span": 2.0})
        first = h.submit("c1", 256, 256, 1)
        second = h.submit("c2", 64, 64, 1)
        children = [subprocess.Popen([sys.executable, "-c", CHILD, root],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    for _ in range(3)]
        outputs = []
        for child in children:
            stdout, stderr = child.communicate(timeout=180)
            try:
                outputs.append(json.loads(stdout.strip().splitlines()[-1]))
            except Exception:
                outputs.append({"state": "child_crash", "stderr": stderr[-500:]})
        db = Application(root)
        exposures = [db.exposures.get(first["id"]), db.exposures.get(second["id"])]
        plates = sum(1 for e in exposures if e["plate_id"])
        return {"scenario": "three_workers_two_jobs", "worker_outputs": outputs,
                "exposure_states": [e["state"] for e in exposures],
                "plate_rows": plates, "capacity": db.resources.snapshot()["reserved"]}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def storage_growth_case():
    root = tempfile.mkdtemp(prefix="facet-storage-")
    try:
        h = Harness(root)
        h.setup(fan_mesh(2000, 1.0), lens={"eye": [0, 0, 5], "projection": "orthographic",
                                           "span": 2.0})
        exposure = h.submit("s1", 256, 256, 1)
        measurements = []
        for attempt in range(1, 4):
            started = time.monotonic()
            result = h.app.worker.run_one()
            progress = h.call("GET", "exposures/" + exposure["id"] + "/progress")
            measurements.append({
                "attempt": attempt, "state": result.get("state"),
                "committed_tiles": progress["committed_tiles"],
                "plate_dir_bytes": dir_bytes(os.path.join(root, "plates")),
                "db_bytes": os.path.getsize(os.path.join(root, "facetproof.sqlite3")),
                "wall_s": round(time.monotonic() - started, 2)})
            if result.get("state") == "succeeded":
                break
            h.call("POST", "exposures/" + exposure["id"] + "/retry", {})
        # Same exposure retried after success is rejected; a fresh identical
        # exposure should share CAS bytes.
        if result.get("state") == "succeeded":
            duplicate = h.submit("s2", 256, 256, 1)
            h.app.worker.run_one()
            measurements.append({"attempt": "duplicate_success",
                                 "plate_dir_bytes": dir_bytes(os.path.join(root, "plates")),
                                 "db_bytes": os.path.getsize(os.path.join(root, "facetproof.sqlite3"))})
        return {"scenario": "storage_growth", "measurements": measurements}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    outcomes = [concurrency_case(), storage_growth_case()]
    print(json.dumps(outcomes, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
