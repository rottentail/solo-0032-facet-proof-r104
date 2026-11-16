"""Supplementary measurements cited in REPORT.md, saved as JSON.

1. span experiment: fixed geometry/canvas, vary orthographic span so visible
   coverage changes while the canvas does not. Separates canvas cost from
   visible-area cost.
2. 40000 small-bbox faces at 256x256 s1: shows the face cap is reachable when
   triangle bounding boxes are small.
3. planner-only peak memory at the 40000-face cap.
"""
import json
import os
import sys

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/benchmarks")

from lib import Harness, fan_mesh, grid_mesh, RssSampler  # noqa: E402
from facetproof.planner import build_plan  # noqa: E402

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def span_experiment():
    rows = []
    for span in (2.0, 6.0, 20.0, 60.0):
        harness = Harness().setup(grid_mesh(5000, 1.0), lens={
            "eye": [0, 0, 5], "projection": "orthographic", "span": span})
        harness.submit("k", 512, 512, 1)
        result, elapsed, sampler = harness.step()
        statistics = result["plate"]["payload"]["statistics"]
        rows.append({"span": span, "covered_pixels": statistics["covered_pixels"],
                     "coverage_ratio": round(statistics["covered_pixels"] / (512 * 512), 4),
                     "wall_s": round(elapsed, 2),
                     "peak_rss_mb": round(sampler.peak_mb, 1)})
        print(rows[-1], flush=True)
        harness.cleanup()
    return rows


def face_cap_small_bbox():
    harness = Harness()
    try:
        mesh = grid_mesh(500, 1.0)
        harness.mesh = harness.call("POST", "meshes", mesh)
        pigment = harness.call("POST", "pigments", {"name": "p",
                                                    "color": [0.2, 0.6, 0.6],
                                                    "two_sided": True})
        assembly = harness.call("POST", "assemblies", {
            "name": "a", "lens": {"eye": [0, 0, 5], "projection": "orthographic",
                                  "span": 2.0}})
        harness.call("PUT", "assemblies/" + assembly["id"], {
            "revision": 1,
            "placements": [{"key": "p%02d" % i, "mesh_id": harness.mesh["id"],
                            "pigment_id": pigment["id"]} for i in range(80)]})
        harness.seal = harness.call("POST", "assemblies/" + assembly["id"] + "/seal",
                                    {"revision": 2})
        harness.submit("k", 256, 256, 1)
        result, elapsed, sampler = harness.step()
        statistics = result["plate"]["payload"]["statistics"]
        return {"source_faces": 40000, "request": "256x256 s1",
                "state": result["state"], "wall_s": round(elapsed, 2),
                "peak_rss_mb": round(sampler.peak_mb, 1),
                "triangles": statistics["triangles"]}
    finally:
        harness.cleanup()


def planner_memory():
    harness = Harness(capacity=2 ** 22)
    try:
        mesh = fan_mesh(500, 1.0)
        harness.mesh = harness.call("POST", "meshes", mesh)
        pigment = harness.call("POST", "pigments", {"name": "p",
                                                    "color": [0.2, 0.6, 0.6],
                                                    "two_sided": True})
        assembly = harness.call("POST", "assemblies", {
            "name": "a", "lens": {"eye": [0, 0, 5], "projection": "orthographic",
                                  "span": 2.0}})
        harness.call("PUT", "assemblies/" + assembly["id"], {
            "revision": 1,
            "placements": [{"key": "p%02d" % i, "mesh_id": harness.mesh["id"],
                            "pigment_id": pigment["id"]} for i in range(80)]})
        seal = harness.call("POST", "assemblies/" + assembly["id"] + "/seal",
                            {"revision": 2})
        before = RssSampler()
        before.samples.append(__import__("lib").read_rss_kb())
        plan = build_plan(harness.app.seals.get(seal["id"])["payload"],
                          {"width": 1024, "height": 1024, "samples": 1,
                           "renderer": "facet-raster-1"})
        after = __import__("lib").read_rss_kb()
        return {"triangles": len(plan["triangles"]),
                "rss_before_mb": round(before.samples[0] / 1024, 1),
                "rss_after_mb": round(after / 1024, 1),
                "delta_mb": round((after - before.samples[0]) / 1024, 1),
                "note": "RSS, not peak; planner allocations persist in the local 'plan'"}
    finally:
        harness.cleanup()


def main():
    out = {"span": span_experiment(),
           "face_cap_small_bbox": face_cap_small_bbox(),
           "planner_memory": planner_memory()}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    open(os.path.join(RESULTS, "supplementary.json"), "w").write(
        json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
