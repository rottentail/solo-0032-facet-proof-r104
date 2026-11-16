"""Run exactly one boundary case in a fresh process and emit JSON on stdout.

Usage: python3 benchmarks/case_runner.py '<json spec>'

Spec keys:
  geometry   "fan" | "grid"
  faces      int (triangles in the first placement's mesh)
  placements int, replicate the same mesh with distinct placement keys
  width,height,samples   exposure request
  span       orthographic span (smaller span -> larger screen coverage)
  eye        camera eye, default [0,0,5]
  mode       "render" (one worker step) | "timeout" (one step, report progress)
             | "cancel_at_progress" handled by http probe instead

Measured:
  wall_s        one worker step, monotonic
  peak_rss_mb   ru_maxrss (kernel high-water mark, no sampling thread)
  baseline_mb   VmRSS after Application init, before submission
  delta_mb      peak - baseline
  statistics    plates statistics on success
  progress      tile progress after the step
  capacity      reserved units after the step

Exit 0 even when the exposure fails; the JSON states the terminal outcome.
"""
import json
import os
import resource
import sys
import tempfile
import time
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import Harness, fan_mesh, grid_mesh  # noqa: E402


def rss_mb():
    with open("/proc/self/status") as stream:
        for line in stream:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    return None


def peak_mb():
    # ru_maxrss is KiB on Linux.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def main():
    spec = json.loads(sys.argv[1])
    geometry = spec.get("geometry", "fan")
    faces = int(spec.get("faces", 48))
    builder = fan_mesh if geometry == "fan" else grid_mesh
    mesh = builder(faces, spec.get("radius", 1.0))
    placements = int(spec.get("placements", 1))
    # Distinct keys and tiny offsets avoid exact coplanar ties between copies.
    placement_list = [{"key": "part%02d" % i, "mesh_id": None, "pigment_id": None,
                       "transform": {"translation": [0.0, 0.0, 0.0]}}
                      for i in range(placements)]

    span = spec.get("span", 2.0)
    lens = {"eye": spec.get("eye", [0, 0, 5]), "projection": "orthographic",
            "span": span}
    root = tempfile.mkdtemp(prefix="facet-case-")
    try:
        h = Harness(root, capacity=spec.get("capacity", 2 ** 40))
        h.mesh = h.call("POST", "meshes", mesh)
        h.pigment = h.call("POST", "pigments",
                           {"name": "釉青", "color": [0.12, 0.62, 0.61],
                            "two_sided": True})
        assembly = h.call("POST", "assemblies", {"name": "边界", "lens": lens})
        for item in placement_list:
            item["mesh_id"] = h.mesh["id"]
            item["pigment_id"] = h.pigment["id"]
        h.assembly = h.call("PUT", "assemblies/" + assembly["id"],
                            {"revision": 1, "placements": placement_list})
        h.seal = h.call("POST", "assemblies/" + assembly["id"] + "/seal",
                        {"revision": 2})
        exposure = h.submit("case", spec.get("width", 256),
                            spec.get("height", 256), spec.get("samples", 1))
        baseline = rss_mb()
        started = time.monotonic()
        result = h.app.worker.run_one()
        elapsed = time.monotonic() - started
        progress = h.call("GET", "exposures/" + exposure["id"] + "/progress")
        exposure_state = h.call("GET", "exposures/" + exposure["id"])
        capacity = h.call("GET", "resources")["reserved"]
        payload = result.get("plate", {}).get("payload") if result.get("plate") else None
        out = {"spec": spec, "geometry": geometry, "faces": faces,
               "placements": placements, "source_faces": faces * placements,
               "request": {"width": spec.get("width", 256),
                           "height": spec.get("height", 256),
                           "samples": spec.get("samples", 1)},
               "high_sample_pixels": spec.get("width", 256) * spec.get("height", 256)
                                     * spec.get("samples", 1) ** 2,
               "span": span, "state": result.get("state"),
               "error": (result.get("error") or {}).get("error") if result.get("error") else None,
               "wall_s": round(elapsed, 3),
               "baseline_rss_mb": round(baseline, 1) if baseline else None,
               "peak_rss_mb": round(peak_mb(), 1),
               "delta_rss_mb": round(peak_mb() - baseline, 1) if baseline else None,
               "statistics": payload.get("statistics") if payload else None,
               "progress": {k: progress[k] for k in
                            ("planned", "committed_tiles", "total_tiles",
                             "committed_pixels", "total_pixels", "complete")},
               "exposure_state": exposure_state["state"],
               "error_field": exposure_state["error"],
               "capacity_reserved_after": capacity,
               "render_bytes": sum(d["size"] for d in payload["passes"].values()) if payload else None}
        print(json.dumps(out, ensure_ascii=False))
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
