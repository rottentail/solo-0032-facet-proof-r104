"""Correlate wall time with a predictive cost proxy.

The rasterizer loops each triangle over its screen-space bounding box, so cost
is closer to sum(triangle bbox area in high-sample pixels) than to the union
coverage. Plan triangles are computed with the production planner, but no
raster is run here; wall times come from the sweep result file.

Prints a least-squares fit wall_s ~ intercept + slope * sum_bbox_pixels so the
report can state the measurement's explanatory variable honestly.
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, "/workspace")
sys.path.insert(0, HERE)

from lib import Harness, fan_mesh, grid_mesh  # noqa: E402
from facetproof.planner import build_plan  # noqa: E402


def sum_bbox(spec):
    builder = fan_mesh if spec.get("geometry", "fan") == "fan" else grid_mesh
    mesh = builder(spec["faces"], 1.0)
    h = Harness()
    try:
        h.mesh = h.call("POST", "meshes", mesh)
        pigment = h.call("POST", "pigments", {"name": "p", "color": [0.2, 0.6, 0.6],
                                              "two_sided": True})
        assembly = h.call("POST", "assemblies", {
            "name": "a", "lens": {"eye": [0, 0, 5], "projection": "orthographic",
                                  "span": spec.get("span", 2.0)}})
        placements = [{"key": "p%02d" % i, "mesh_id": h.mesh["id"],
                       "pigment_id": pigment["id"]}
                      for i in range(spec.get("placements", 1))]
        h.call("PUT", "assemblies/" + assembly["id"],
               {"revision": 1, "placements": placements})
        seal = h.call("POST", "assemblies/" + assembly["id"] + "/seal", {"revision": 2})
        request = {"width": spec["width"], "height": spec["height"],
                   "samples": spec.get("samples", 1), "renderer": "facet-raster-1"}
        plan = build_plan(h.app.seals.get(seal["id"])["payload"], request)
        total = 0
        for triangle in plan["triangles"]:
            xs = [v[0] for v in triangle["vertices"]]
            ys = [v[1] for v in triangle["vertices"]]
            left = max(0, math.floor(min(xs)))
            right = min(plan["width"] - 1, math.ceil(max(xs)))
            top = max(0, math.floor(min(ys)))
            bottom = min(plan["height"] - 1, math.ceil(max(ys)))
            total += max(0, right - left + 1) * max(0, bottom - top + 1)
        return {"triangles": len(plan["triangles"]), "sum_bbox_pixels": total,
                "high_sample_pixels": plan["width"] * plan["height"]}
    finally:
        h.cleanup()


def main():
    rows = []
    sweep = [json.loads(line) for line in
             open(os.path.join(HERE, "results", "sweep.jsonl"))]
    for record in sweep:
        spec = record["spec"]
        if "state" not in record or record.get("state") == "failed":
            continue
        if spec.get("placements", 1) > 1:
            continue
        measured = sum_bbox(spec)
        measured["wall_s"] = record["wall_s"]
        measured["peak_rss_mb"] = record["peak_rss_mb"]
        measured["spec"] = spec
        rows.append(measured)
        print(json.dumps({k: measured[k] for k in
                          ("triangles", "sum_bbox_pixels", "wall_s", "peak_rss_mb")}))
    xs = [r["sum_bbox_pixels"] for r in rows]
    ys = [r["wall_s"] for r in rows]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    intercept = my - slope * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    r2 = 1 - ss_res / ss_tot
    out = {"n": n, "slope_s_per_bbox_pixel": slope, "intercept_s": intercept, "r2": r2,
           "rows": rows}
    print(json.dumps({k: out[k] for k in ("n", "slope_s_per_bbox_pixel", "intercept_s", "r2")}))
    open(os.path.join(HERE, "results", "bbox_correlation.json"), "w").write(
        json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
