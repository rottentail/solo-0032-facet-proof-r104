"""Cancel responsiveness sweep.

For a fixed render, send the cancel at increasing delays after the worker
starts. Records where the cancel lands (queued / tiles / finalize), how long
the worker takes to reach a terminal state *after* the cancel is accepted,
whether a plate exists, and whether the result can be reviewed or exported.

The point is to find the worst observed acknowledgement latency and the
boundary at which an already-computable plate is destroyed by cancellation.
"""
import json
import sys
import threading
import time

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/benchmarks")

from lib import Harness, fan_mesh, grid_mesh  # noqa: E402


def one_case(delay, geometry, faces, width, height, samples):
    h = Harness().setup(
        (fan_mesh if geometry == "fan" else grid_mesh)(faces, 1.0),
        lens={"eye": [0, 0, 5], "projection": "orthographic", "span": 2.0})
    exposure = h.submit("c", width, height, samples)
    eid = exposure["id"]
    holder = {}

    def worker():
        holder["result"] = h.app.worker.run_one()
        holder["done"] = time.monotonic()

    thread = threading.Thread(target=worker)
    started = time.monotonic()
    thread.start()
    time.sleep(delay)
    before = h.call("GET", "exposures/" + eid)
    progress_before = h.call("GET", "exposures/" + eid + "/progress")
    sent = time.monotonic()
    try:
        response = h.call("POST", "exposures/" + eid + "/cancel")
        accepted = response["state"]
        error = None
    except Exception as exc:
        accepted, error = None, getattr(exc, "code", str(exc))
    accepted_at = time.monotonic()
    thread.join(timeout=180)
    final = h.call("GET", "exposures/" + eid)
    progress = h.call("GET", "exposures/" + eid + "/progress")
    export = None
    if final.get("plate_id"):
        export = {"verify": h.call("POST", "plates/" + final["plate_id"] + "/verify")["valid"],
                  "bundle_bytes": len(h.call("GET", "plates/" + final["plate_id"] + "/bundle"))}
    out = {"delay_s": delay, "state_before_cancel": before["state"],
           "cancel_requested_before": before["cancel_requested"],
           "progress_before": {k: progress_before[k] for k in
                               ("committed_tiles", "total_tiles", "complete")},
           "cancel_http_state": accepted, "cancel_error": error,
           "cancel_accept_latency_s": round(accepted_at - sent, 3),
           "terminal_after_cancel_s": round(holder["done"] - sent, 3),
           "worker_total_s": round(holder["done"] - started, 3),
           "worker_result": holder["result"].get("state"),
           "final_state": final["state"], "final_error": final["error"],
           "progress_after": {k: progress[k] for k in
                              ("committed_tiles", "total_tiles", "complete")},
           "plate_id": final.get("plate_id"), "export": export,
           "capacity_after": h.call("GET", "resources")["reserved"]}
    h.cleanup()
    return out


def main():
    cases = []
    # A fast render: cancel arrives either before or after completion.
    for delay in (0.0, 0.2, 0.5, 0.8, 1.2):
        cases.append(one_case(delay, "fan", 8, 64, 64, 1))
    # A longer render where cancel lands mid-tiles.
    for delay in (0.5, 1.5, 3.0, 5.0):
        cases.append(one_case(delay, "fan", 4000, 256, 256, 1))
    # A render whose every pixel is computed right before the cancel.
    for delay in (10.0, 11.5, 12.5):
        cases.append(one_case(delay, "grid", 19602, 512, 512, 2))
    print(json.dumps(cases, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
