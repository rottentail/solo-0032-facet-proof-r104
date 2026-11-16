"""Turn the raw result files into the tables used in REPORT.md.

Reads benchmarks/results/*.json[l] and prints markdown tables. No timing is
performed here, so it is cheap to re-run after adding cases.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")


def load(name, default=None):
    path = os.path.join(RESULTS, name)
    if not os.path.exists(path):
        return default
    if name.endswith(".jsonl"):
        return [json.loads(line) for line in open(path)]
    return json.load(open(path))


def sweep_table():
    rows = load("sweep.jsonl", [])
    lines = ["| axis | geometry | source faces | request | wall s | peak RSS MB | Δ RSS MB | state |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        s = r.get("spec", {})
        if "state" not in r:
            lines.append("| %s | crash | | | | | | %s |" % (
                s.get("axis", "?"), str(r.get("crash"))[:80]))
            continue
        request = "%dx%d s%d" % (s.get("width"), s.get("height"), s.get("samples"))
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            s.get("axis", "?"), s.get("geometry", "?"),
            s.get("source_faces", s.get("faces") * s.get("placements", 1)),
            request, r.get("wall_s"), r.get("peak_rss_mb"),
            r.get("delta_rss_mb"), r.get("state") +
            (("/" + r["error"]) if r.get("error") else "")))
    return "\n".join(lines)


def cancel_table():
    rows = load("cancel_sweep.json", [])
    lines = ["| delay s | state before | tiles before | HTTP | accept ms | worker terminal after cancel s | worker result | plate | bundle |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        tiles = "%s/%s" % (r["progress_before"]["committed_tiles"],
                           r["progress_before"]["total_tiles"])
        accept = "%s%s" % (round(r["cancel_accept_latency_s"] * 1000),
                           "" if r["cancel_http_state"] else " (rejected:%s)" % r["cancel_error"])
        export = "yes" if r["export"] else "no"
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["delay_s"], r["state_before_cancel"], tiles,
            r["cancel_http_state"] or "409", accept,
            r["terminal_after_cancel_s"], r["worker_result"],
            "yes" if r["plate_id"] else "no", export))
    return "\n".join(lines)


def phase_table():
    rows = load("phase_profile.jsonl", [])
    lines = ["| geometry | faces | request | plan s | tiles s | downsample+PNG s | blob s | total s |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        s = r["spec"]
        lines.append("| %s | %s | %dx%d s%d | %s | %s | %s | %s | %s |" % (
            s["geometry"], r["source_faces"], s["width"], s["height"], s["samples"],
            r["plan_s"], r["render_s"], r["serialize_s"], r["blob_write_s"], r["total_s"]))
    return "\n".join(lines)


def variance_table():
    rows = load("variance.json", [])
    lines = ["| case | wall min/mean/max s | peak RSS min/mean/max MB |",
             "|---|---|---|"]
    for r in rows:
        s = r["spec"]
        label = "%s %d faces %dx%d s%d" % (s["geometry"], s["faces"], s["width"],
                                           s["height"], s["samples"])
        lines.append("| %s | %.2f / %.2f / %.2f | %.1f / %.1f / %.1f |" % (
            label, r["wall_min"], r["wall_mean"], r["wall_max"],
            r["peak_min"], r["peak_mean"], r["peak_max"]))
    return "\n".join(lines)


def memory_table():
    rows = load("memory_scaling.json", [])
    lines = ["| high-sample pixels | wall s | peak RSS MB | Δ RSS MB |",
             "|---|---|---|---|"]
    for r in rows:
        lines.append("| %s | %s | %s | %s |" % (
            r["high_sample_pixels"], r["wall_s"], r["peak_rss_mb"], r["delta_rss_mb"]))
    return "\n".join(lines)


def main():
    print("## Sweep\n")
    print(sweep_table())
    print("\n## Cancel timing\n")
    print(cancel_table())
    print("\n## Phases\n")
    print(phase_table())
    print("\n## Variance\n")
    print(variance_table())
    print("\n## Memory scaling\n")
    print(memory_table())


if __name__ == "__main__":
    main()
