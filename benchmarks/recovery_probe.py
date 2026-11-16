"""Cross-process terminal-state and artifact-retention checks.

Scenario A - worker process is killed mid-render, then the service restarts.
    Does the exposure become recoverable, and does a retry reuse tiles?
Scenario B - cancel a queued exposure, restart, and confirm it stays cancelled
    with a definite terminal state.
Scenario C - two workers racing the same exposure: one wins, the other must
    not publish a plate or free capacity twice.
"""
import json
import os
import signal
import sys
import tempfile
import time
import shutil

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/benchmarks")

from lib import Harness, fan_mesh, grid_mesh  # noqa: E402
from facetproof.application import Application  # noqa: E402


def scenario_kill_and_recover():
    root = tempfile.mkdtemp(prefix="facet-recover-")
    try:
        h = Harness(root)
        h.setup(fan_mesh(4000, 1.0), lens={"eye": [0, 0, 5], "projection": "orthographic",
                                           "span": 2.0})
        exposure = h.submit("kill", 512, 512, 2)
        # Claim and render part of the canvas, then abandon without settling.
        claimed = h.app.exposures.claim()
        started = time.monotonic()
        from facetproof.planner import build_plan  # noqa: E402
        from facetproof.raster import rasterize  # noqa: E402
        from facetproof.tile_protocol import encode  # noqa: E402

        plan = build_plan(h.app.seals.get(h.seal["id"])["payload"], claimed["request"])
        h.app.tiles.store.prepare(claimed, plan, 64)
        frame, records = h.app.tiles.store.snapshot(exposure["id"])
        for ordinal in range(4):
            record = records[ordinal]
            rendered = rasterize(plan, lambda: None, tuple(record["bounds"]))
            payload = encode(rendered, record["bounds"], frame["fingerprint"], h.app.blobs)
            h.app.tiles.store.commit(claimed, ordinal, payload)
        partial = h.call("GET", "exposures/" + exposure["id"] + "/progress")
        # Simulate a crash: abandon the process entirely (new Application on
        # the same root means all SQL connections are new).
        del h
        restarted = Application(root)
        recovered = restarted.exposures.recover()  # lease still live -> no-op
        live_lease = restarted.exposures.get(exposure["id"])["state"]
        # Force the lease to look expired, as if the worker died and its
        # 120s lease elapsed.
        with restarted.db.unit_of_work() as conn:
            conn.execute("UPDATE exposures SET lease_until=? WHERE id=?", (time.time() - 1, exposure["id"]))
        recovered = restarted.exposures.recover()
        after_recover = restarted.exposures.get(exposure["id"])
        capacity_after_recover = restarted.resources.snapshot()["reserved"]
        result = restarted.worker.run_one()
        final = restarted.exposures.get(exposure["id"])
        progress = restarted.tiles.progress(exposure["id"])
        review = None
        if final.get("plate_id"):
            review = {"verify": restarted.plates.verify(final["plate_id"])["valid"],
                      "bundle_bytes": len(restarted.bundles.export(final["plate_id"]))}
        return {"scenario": "kill_recover",
                "partial_progress": {k: partial[k] for k in ("committed_tiles", "total_tiles")},
                "state_before_lease_expiry": live_lease,
                "recovered": recovered["recovered"],
                "state_after_recover": after_recover["state"],
                "capacity_after_recover": capacity_after_recover,
                "worker_result": result.get("state"),
                "final_state": final["state"], "final_error": final["error"],
                "final_progress": {k: progress[k] for k in ("committed_tiles", "total_tiles", "complete")},
                "review": review, "recover_wall_s": round(time.monotonic() - started, 2)}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def scenario_kill_mid_tile():
    """Kill the worker inside a tile: no tile is committed for that window."""
    root = tempfile.mkdtemp(prefix="facet-kill-")
    try:
        h = Harness(root)
        h.setup(grid_mesh(19602, 1.0), lens={"eye": [0, 0, 5], "projection": "orthographic",
                                             "span": 2.0})
        exposure = h.submit("killmid", 512, 512, 2)
        pid = os.fork()
        if pid == 0:
            h.app.worker.run_one()
            os._exit(0)
        time.sleep(1.5)  # allow some tiles to commit, then SIGKILL mid-tile
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
        db = Application(root)
        progress = db.tiles.progress(exposure["id"])
        state = db.exposures.get(exposure["id"])["state"]
        with db.db.unit_of_work() as conn:
            conn.execute("UPDATE exposures SET lease_until=? WHERE id=?", (time.time() - 1, exposure["id"]))
        recovered = db.exposures.recover()["recovered"]
        after = db.exposures.get(exposure["id"])
        capacity = db.resources.snapshot()["reserved"]
        before = progress["committed_tiles"]
        result = db.worker.run_one()
        final = db.exposures.get(exposure["id"])
        progress_after = db.tiles.progress(exposure["id"])
        return {"scenario": "kill_mid_tile", "state_at_kill": state,
                "tiles_at_kill": {"committed": before, "total": progress["total_tiles"],
                                  "complete": progress["complete"]},
                "recovered": recovered, "state_after_recover": after["state"],
                "capacity_after_recover": capacity,
                "worker_result": result.get("state"),
                "final_state": final["state"],
                "tiles_after": {"committed": progress_after["committed_tiles"],
                                "total": progress_after["total_tiles"]},
                "plate_verify": db.plates.verify(final["plate_id"])["valid"] if final.get("plate_id") else None}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def scenario_cancelled_survives_restart():
    root = tempfile.mkdtemp(prefix="facet-cancelrestart-")
    try:
        h = Harness(root)
        h.setup(fan_mesh(8, 1.0), lens={"eye": [0, 0, 5], "projection": "orthographic",
                                        "span": 2.0})
        exposure = h.submit("late", 64, 64, 1)
        h.app.worker.run_one()  # succeeds fully
        try:
            supplied = h.call("POST", "exposures/" + exposure["id"] + "/cancel")
        except Exception as exc:
            supplied = {"state": None, "error": getattr(exc, "code", str(exc))}
        del h
        restarted = Application(root)
        final = restarted.exposures.get(exposure["id"])
        plate = restarted.exposures.get(exposure["id"])["plate_id"]
        return {"scenario": "cancel_after_terminal_restart", "cancel_status_state": supplied["state"],
                "final_state": final["state"],
                "plate_after_restart": plate,
                "bundle_bytes": len(restarted.bundles.export(plate)) if plate else None}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    outcomes = []
    for fn in (scenario_kill_and_recover, scenario_kill_mid_tile,
               scenario_cancelled_survives_restart):
        print("running", fn.__name__, file=sys.stderr)
        outcomes.append(fn())
    print(json.dumps(outcomes, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
