"""Recovery paths out of an unrenderable legal request.

The 40000-face wide-triangle request at 512x512 s2 can never commit its
centre tile inside the 45 s attempt budget. An operator therefore needs a
definite, non-success terminal state and a way to reclaim the reservation.

This checks, against a real HTTP server:
  1. POST /cancel on the queued exposure returns `cancelled` and frees the
     full reservation.
  2. A resubmission at a smaller canvas succeeds and is exportable.
  3. The cancelled exposure exposes no plate and cannot be retried.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/benchmarks")

from http_probe import Server, prepare  # noqa: E402
from lib import fan_mesh  # noqa: E402


def main():
    root = tempfile.mkdtemp(prefix="facet-unrenderable-")
    mesh = fan_mesh(500, 1.0)
    with Server(root) as server:
        # 80 placements of the same 500-face fan: 40000 source faces.
        mesh_obj, _ = server.call("POST", "meshes", mesh)
        pigment, _ = server.call("POST", "pigments", {"name": "p",
                                                      "color": [0.2, 0.6, 0.6],
                                                      "two_sided": True})
        assembly, _ = server.call("POST", "assemblies", {
            "name": "a", "lens": {"eye": [0, 0, 5], "projection": "orthographic",
                                  "span": 2.0}})
        assembly, _ = server.call("PUT", "assemblies/" + assembly["id"], {
            "revision": 1,
            "placements": [{"key": "p%02d" % i, "mesh_id": mesh_obj["id"],
                            "pigment_id": pigment["id"]} for i in range(80)]})
        seal, _ = server.call("POST", "assemblies/" + assembly["id"] + "/seal",
                              {"revision": 2})
        big, _ = server.call("POST", "seals/" + seal["id"] + "/exposures",
                             {"key": "big", "width": 512, "height": 512, "samples": 2})
        reserved_before, _ = server.call("GET", "resources")
        # Three failing attempts (three full 45 s budgets) is enough to show the
        # exposure cannot be finished by retrying on this machine.
        attempts = []
        for _ in range(3):
            result, _ = server.call("POST", "worker/step", {})
            attempts.append({"state": result.get("state"),
                             "error": (result.get("error") or {}).get("error")})
            if result.get("state") == "failed":
                server.call("POST", "exposures/" + big["id"] + "/retry", {})
        progress, _ = server.call("GET", "exposures/" + big["id"] + "/progress")
        # Cancel the remaining queued work; this must be a synchronous terminal
        # state because no worker owns it.
        cancelled, status = server.call("POST", "exposures/" + big["id"] + "/cancel")
        exposure_after, _ = server.call("GET", "exposures/" + big["id"])
        capacity_after_cancel, _ = server.call("GET", "resources")
        retry_attempt, retry_status = server.call("POST",
                                                  "exposures/" + big["id"] + "/retry", {})
        # Smaller canvas is renderable and exportable.
        small = prepare(server, mesh, 256, 256, 1, key="small")
        small_result, _ = server.call("POST", "worker/step", {})
        small_exposure, _ = server.call("GET", "exposures/" + small["id"])
        bundle = None
        if small_exposure.get("plate_id"):
            bundle, bundle_status = server.call(
                "GET", "plates/" + small_exposure["plate_id"] + "/bundle")
        out = {
            "request": {"width": 512, "height": 512, "samples": 2, "source_faces": 40000},
            "attempts": attempts,
            "progress_after_attempts": {k: progress[k] for k in
                                        ("committed_tiles", "total_tiles", "complete")},
            "reservation_before": reserved_before["reserved"],
            "cancel_status": status,
            "cancel_state": cancelled.get("state"),
            "exposure_state_after_cancel": exposure_after["state"],
            "capacity_reserved_after_cancel": capacity_after_cancel["reserved"],
            "retry_http_status": retry_status,
            "retry_error": retry_attempt.get("error"),
            "small_request": {"width": 256, "height": 256, "samples": 1},
            "small_worker_state": small_result.get("state"),
            "small_exposure_state": small_exposure["state"],
            "small_bundle_bytes": len(bundle) if isinstance(bundle, bytes) else None,
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results",
                          "unrenderable_recovery.json"), "w").write(
            json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
