"""Cancel a render while it is genuinely in flight.

Phases probed:
  queued   - cancel before any worker claims the exposure
  tiles    - cancel after some (not all) high-sample tiles are committed
  finalize - cancel once every tile is committed, while assemble/downscale/
             PNG encoding is still running

For each phase we record: cancel acceptance latency, worker terminal latency,
final exposure state, whether any plate exists, whether a bundle can be
exported, progress watermark, and when capacity is returned.
"""
import json
import sys
import threading
import time

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/benchmarks")

from lib import Harness, fan_mesh, grid_mesh  # noqa: E402


def run_phase(phase, mesh, width, height, samples, trigger):
    h = Harness().setup(mesh, lens={"eye": [0, 0, 5], "projection": "orthographic",
                                    "span": 2.0})
    exposure = h.submit("k", width, height, samples)
    eid = exposure["id"]
    outcome = {"phase": phase, "request": {"width": width, "height": height,
                                           "samples": samples},
               "faces": len(mesh["faces"])}
    if phase == "queued":
        started = time.monotonic()
        after = h.call("POST", "exposures/" + eid + "/cancel")
        outcome["cancel_latency_s"] = round(time.monotonic() - started, 4)
        outcome["state_after_cancel"] = after["state"]
        outcome["capacity_after_cancel"] = h.call("GET", "resources")["reserved"]
        result, elapsed, sampler = h.step()
        outcome["worker_result"] = result.get("state")
        outcome["worker_elapsed_s"] = round(elapsed, 3)
        outcome["capacity_after_worker"] = h.call("GET", "resources")["reserved"]
        outcome["plate"] = bool(result.get("plate"))
        outcome["progress"] = h.call("GET", "exposures/" + eid + "/progress")
        outcome["step_claimed"] = result.get("state") != "idle"
        return outcome

    results = {}
    cancel_time = {}

    def worker():
        results["step"] = h.app.worker.run_one()
        results["elapsed"] = time.monotonic() - results["start"]

    thread = threading.Thread(target=worker)
    results["start"] = time.monotonic()
    thread.start()
    trigger_reached = trigger(h, eid, results)
    if not trigger_reached:
        outcome["trigger"] = "not reached"
        thread.join(timeout=180)
        return outcome
    progress = h.call("GET", "exposures/" + eid + "/progress")
    cancel_time["sent"] = time.monotonic()
    cancel_time["state_before"] = h.call("GET", "exposures/" + eid)["state"]
    cancel_time["progress_before"] = {k: progress[k] for k in
                                      ("committed_tiles", "total_tiles", "complete")}
    try:
        accepted = h.call("POST", "exposures/" + eid + "/cancel")
        cancel_time["accepted_state"] = accepted["state"]
    except Exception as exc:  # completed before the cancel landed
        cancel_time["error"] = getattr(exc, "code", str(exc))
    cancel_time["returned"] = time.monotonic()
    outcome["cancel_state_before"] = cancel_time["state_before"]
    outcome["cancel_progress_before"] = cancel_time["progress_before"]
    outcome["cancel_http_state"] = cancel_time.get("accepted_state", cancel_time.get("error"))
    outcome["cancel_request_latency_s"] = round(cancel_time["returned"] - cancel_time["sent"], 3)
    outcome["capacity_while_running"] = h.call("GET", "resources")["reserved"]
    thread.join(timeout=180)
    cancel_time["terminal"] = time.monotonic()
    outcome["worker_terminal_latency_s"] = round(cancel_time["terminal"] - cancel_time["sent"], 3)
    outcome["worker_wall_s"] = round(results.get("elapsed", -1), 3)
    result = results.get("step", {})
    outcome["worker_result"] = result.get("state")
    outcome["plate"] = bool(result.get("plate"))
    outcome["exposure"] = {k: h.call("GET", "exposures/" + eid).get(k)
                           for k in ("state", "error")}
    outcome["progress"] = h.call("GET", "exposures/" + eid + "/progress")
    outcome["capacity_after"] = h.call("GET", "resources")["reserved"]
    # Can anything be reviewed or exported after cancellation?
    outcome["export_attempt"] = attempt_export(h, eid)
    h.cleanup()
    return outcome


def attempt_export(h, exposure_id):
    exposure = h.call("GET", "exposures/" + exposure_id)
    plate_id = exposure.get("plate_id")
    if not plate_id:
        return {"plate_id": None, "bundle": "no plate row"}
    try:
        raw = h.call("GET", "plates/" + plate_id + "/bundle")
        return {"plate_id": plate_id, "bundle_bytes": len(raw)}
    except Exception as exc:
        return {"plate_id": plate_id, "bundle_error": getattr(exc, "code", str(exc))}


def wait_partial_tiles(h, eid, results, minimum=4, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if "step" in results:
            return False
        try:
            progress = h.call("GET", "exposures/" + eid + "/progress")
        except Exception:
            return False
        if any(progress.get(k) for k in ("committed_tiles",)) and \
                progress["committed_tiles"] >= min(minimum, progress["total_tiles"] - 1):
            return True
        time.sleep(0.01)
    return False


def wait_all_tiles(h, eid, results, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if "step" in results:
            return False
        try:
            progress = h.call("GET", "exposures/" + eid + "/progress")
        except Exception:
            return False
        if progress.get("planned") and progress["complete"]:
            return True
        time.sleep(0.005)
    return False


def main():
    cases = [
        ("queued", fan_mesh(8, 1.0), 64, 64, 1, None),
        ("tiles", fan_mesh(2000, 1.0), 256, 256, 1, wait_partial_tiles),
        ("finalize", grid_mesh(19602, 1.0), 512, 512, 2, wait_all_tiles),
    ]
    outcomes = []
    for phase, mesh, width, height, samples, trigger in cases:
        print("running", phase, file=sys.stderr)
        outcomes.append(run_phase(phase, mesh, width, height, samples,
                                  trigger or (lambda h, e, r: True)))
    print(json.dumps(outcomes, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
