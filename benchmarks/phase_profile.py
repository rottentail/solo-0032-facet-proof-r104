"""Phase timing for one attempt: plan, tiles, assemble, downsample, encode.

These phases are timed with direct calls to the same functions the Worker
calls, so the numbers reflect production code. No checkpoint policy is
changed. Runs one case per fresh process: python3 phase_profile.py '<json>'
"""
import json
import os
import sys
import tempfile
import time
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import Harness, fan_mesh, grid_mesh  # noqa: E402
from facetproof.planner import build_plan  # noqa: E402
from facetproof.passes import serialize_passes  # noqa: E402


def main():
    spec = json.loads(sys.argv[1])
    builder = fan_mesh if spec.get("geometry", "fan") == "fan" else grid_mesh
    mesh = builder(spec["faces"], 1.0)
    root = tempfile.mkdtemp(prefix="facet-phase-")
    try:
        h = Harness(root)
        h.mesh = h.call("POST", "meshes", mesh)
        h.pigment = h.call("POST", "pigments", {"name": "p", "color": [0.2, 0.6, 0.6],
                                                "two_sided": True})
        assembly = h.call("POST", "assemblies", {
            "name": "a", "lens": {"eye": [0, 0, 5], "projection": "orthographic", "span": 2.0}})
        h.assembly = h.call("PUT", "assemblies/" + assembly["id"], {
            "revision": 1, "placements": [{"key": "body", "mesh_id": h.mesh["id"],
                                           "pigment_id": h.pigment["id"]}]})
        h.seal = h.call("POST", "assemblies/" + assembly["id"] + "/seal", {"revision": 2})
        exposure = h.submit("phase", spec["width"], spec["height"], spec["samples"])
        claimed = h.app.exposures.claim()
        seal = h.app.seals.get(h.seal["id"])["payload"]

        t = time.monotonic()
        plan = build_plan(seal, claimed["request"])
        plan_s = time.monotonic() - t

        t = time.monotonic()
        rendered = h.app.tiles.render(claimed, plan, lambda: None)
        render_s = time.monotonic() - t

        t = time.monotonic()
        passes, statistics = serialize_passes(plan, rendered, claimed["request"])
        serialize_s = time.monotonic() - t

        t = time.monotonic()
        for name, data in passes.items():
            h.app.blobs.put(data)
        blobs_s = time.monotonic() - t

        print(json.dumps({"spec": spec, "source_faces": len(mesh["faces"]),
                          "triangles": len(plan["triangles"]),
                          "plan_s": round(plan_s, 3),
                          "render_s": round(render_s, 3),
                          "serialize_s": round(serialize_s, 3),
                          "blob_write_s": round(blobs_s, 3),
                          "total_s": round(plan_s + render_s + serialize_s + blobs_s, 3),
                          "statistics": statistics}, ensure_ascii=False))
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
