"""Exercise the real HTTP server for cancellation and post-terminal review.

Starts `python3 -m facetproof` as a subprocess, drives it with urllib, and
records:
  * whether cancel of a running exposure is accepted immediately,
  * how long until the worker acknowledges a terminal state,
  * capacity release timing,
  * whether a plate exists and can be verified/exported afterwards,
  * what happens to a completed exposure if cancellation arrives too late.
"""
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.error

sys.path.insert(0, "/workspace/benchmarks")
from lib import fan_mesh, grid_mesh  # noqa: E402


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Server:
    def __init__(self, root):
        self.root = root
        self.port = free_port()
        self.base = "http://127.0.0.1:%d/facet/v1/" % self.port
        self.proc = None

    def __enter__(self):
        env = dict(os.environ)
        os.makedirs(self.root, exist_ok=True)
        self.log = open(os.path.join(self.root, "server.log"), "wb")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "facetproof", "--root", os.path.join(self.root, "data"),
             "--host", "127.0.0.1", "--port", str(self.port)],
            cwd="/workspace", stdout=self.log, stderr=subprocess.STDOUT, env=env)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                self.call("GET", "health")
                return self
            except Exception:
                time.sleep(0.05)
        raise RuntimeError("server did not start")

    def __exit__(self, *exc):
        self.proc.send_signal(signal.SIGTERM)
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()

    def call(self, method, route, data=None, timeout=180):
        raw = None if data is None else json.dumps(data).encode()
        req = urllib.request.Request(self.base + route, data=raw, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body = response.read()
                ctype = response.headers.get("Content-Type", "")
                return (json.loads(body) if "json" in ctype else body), response.status
        except urllib.error.HTTPError as exc:
            return json.loads(exc.read()), exc.code


def prepare(server, mesh, width, height, samples, key="bench"):
    mesh_obj, _ = server.call("POST", "meshes", mesh)
    pig, _ = server.call("POST", "pigments", {"name": "釉青", "color": [0.12, 0.62, 0.61],
                                              "two_sided": True})
    assembly, _ = server.call("POST", "assemblies", {
        "name": "取消检查", "lens": {"eye": [0, 0, 5], "projection": "orthographic", "span": 2.0}})
    assembly, _ = server.call("PUT", "assemblies/" + assembly["id"], {
        "revision": 1, "placements": [{"key": "body", "mesh_id": mesh_obj["id"],
                                       "pigment_id": pig["id"]}]})
    seal, _ = server.call("POST", "assemblies/" + assembly["id"] + "/seal", {"revision": 2})
    exposure, _ = server.call("POST", "seals/" + seal["id"] + "/exposures",
                              {"key": key, "width": width, "height": height,
                               "samples": samples})
    return exposure


def worker_loop(server, results, stop):
    while not stop.is_set():
        result, status = server.call("POST", "worker/step", {})
        results.append({"result": result, "at": time.monotonic()})
        if result.get("state") in ("succeeded", "failed", "cancelled"):
            return


def wait_progress(server, exposure_id, predicate, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        progress, _ = server.call("GET", "exposures/" + exposure_id + "/progress")
        if predicate(progress):
            return progress
        time.sleep(0.01)
    return None


def scenario_cancel_midway(root):
    """Cancel while tiles are still being committed."""
    with Server(root) as server:
        exposure = prepare(server, fan_mesh(4000, 1.0), 512, 512, 2)
        results, stop = [], threading.Event()
        thread = threading.Thread(target=worker_loop, args=(server, results, stop))
        thread.start()
        progress = wait_progress(server, exposure["id"],
                                 lambda p: p.get("committed_tiles", 0) >= 8)
        before, _ = server.call("GET", "exposures/" + exposure["id"])
        capacity_before, _ = server.call("GET", "resources")
        sent = time.monotonic()
        cancel, cancel_status = server.call("POST", "exposures/" + exposure["id"] + "/cancel")
        cancel_returned = time.monotonic()
        thread.join(timeout=120)
        terminal = time.monotonic()
        after, _ = server.call("GET", "exposures/" + exposure["id"])
        capacity_after, _ = server.call("GET", "resources")
        progress_after, _ = server.call("GET", "exposures/" + exposure["id"] + "/progress")
        review = post_terminal_review(server, after)
        return {
            "scenario": "cancel_midway",
            "request": {"width": 512, "height": 512, "samples": 2, "faces": 4000},
            "state_before_cancel": before["state"],
            "progress_at_cancel": {k: progress[k] for k in
                                   ("committed_tiles", "total_tiles", "complete")},
            "cancel_http_status": cancel_status,
            "cancel_returned_state": cancel.get("state"),
            "cancel_latency_s": round(cancel_returned - sent, 3),
            "worker_terminal_latency_s": round(terminal - sent, 3),
            "worker_results": [r["result"].get("state") for r in results],
            "terminal_state": after["state"],
            "terminal_error": after["error"],
            "capacity_before": capacity_before["reserved"],
            "capacity_at_cancel_return": None,
            "capacity_after": capacity_after["reserved"],
            "progress_after": {k: progress_after[k] for k in
                               ("committed_tiles", "total_tiles", "complete")},
            "review": review,
        }


def scenario_cancel_after_commit(root):
    """Cancel arrives while the exposure is already succeeded."""
    with Server(root) as server:
        exposure = prepare(server, fan_mesh(8, 1.0), 64, 64, 1, key="late")
        server.call("POST", "worker/step", {})
        after, _ = server.call("GET", "exposures/" + exposure["id"])
        cancel, status = server.call("POST", "exposures/" + exposure["id"] + "/cancel")
        review = post_terminal_review(server, after)
        return {"scenario": "cancel_after_success", "terminal_state": after["state"],
                "cancel_http_status": status, "cancel_body": cancel, "review": review}


def post_terminal_review(server, exposure):
    """What can an operator still review or export after the terminal state?"""
    plate_id = exposure.get("plate_id")
    if not plate_id:
        return {"plate_id": None, "verifiable": False, "exportable": False,
                "progress_query": "available (tile watermark only)",
                "artifacts": "no plate row; committed tiles are CAS blobs, not reviewable plates"}
    verify, verify_status = server.call("POST", "plates/" + plate_id + "/verify")
    pick, pick_status = server.call("GET", "plates/" + plate_id + "/pick?x=0&y=0")
    bundle, bundle_status = server.call("GET", "plates/" + plate_id + "/bundle")
    proof, proof_status = server.call("POST", "plates/" + plate_id + "/proofs",
                                      {"note": "终态后审阅"})
    return {"plate_id": plate_id, "verify_status": verify_status,
            "verified": verify.get("valid"), "pick_status": pick_status,
            "bundle_status": bundle_status, "bundle_bytes": len(bundle) if isinstance(bundle, bytes) else None,
            "proof_status": proof_status, "proof_state": proof.get("state") if isinstance(proof, dict) else None}


def main():
    root = tempfile.mkdtemp(prefix="facet-http-")
    outcomes = [scenario_cancel_midway(os.path.join(root, "a")),
                scenario_cancel_after_commit(os.path.join(root, "b"))]
    print(json.dumps(outcomes, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
