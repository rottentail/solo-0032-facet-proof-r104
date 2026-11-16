"""Sweep the three dimensions independently and write JSONL results.

Each case runs in a fresh interpreter so peak RSS is the kernel high-water
mark for that case alone, not a cumulative process maximum.

Dimensions
  coverage : same fan geometry (48 faces) and span, vary span -> screen area
             (we instead vary the canvas width/height at fixed samples=1 and a
             fixed span, which is the honest meaning of "picture coverage"
             for a full-canvas orthographic view; we also include a
             small-object case where geometry covers little area)
  faces    : fan/grid face count at fixed canvas and samples
  samples  : samples^2 high-sample multiplier at fixed output canvas
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(HERE, "case_runner.py")


def run(spec, timeout=300):
    proc = subprocess.run([sys.executable, RUNNER, json.dumps(spec)],
                          capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        return {"spec": spec, "crash": proc.stderr.strip()[-4000:],
                "returncode": proc.returncode}
    return json.loads(proc.stdout.strip().splitlines()[-1])


def main():
    cases = []

    # --- coverage sweep: 48-face fan, output canvas grows 64 -> 512 ---------
    for size in (64, 128, 256, 384, 512):
        cases.append({"axis": "coverage", "geometry": "fan", "faces": 48,
                      "width": size, "height": size, "samples": 1, "span": 2.0})
    # Small object in a big canvas: geometry covers ~1/16 of the frame.
    for size in (256, 512):
        cases.append({"axis": "coverage-small", "geometry": "fan", "faces": 48,
                      "width": size, "height": size, "samples": 1, "span": 16.0})

    # --- face sweep: fixed 256x256 s1, fan and grid -------------------------
    for faces in (8, 48, 256, 1000, 2000, 4000, 8000):
        cases.append({"axis": "faces-fan", "geometry": "fan", "faces": faces,
                      "width": 256, "height": 256, "samples": 1, "span": 2.0})
    for faces in (100, 1000, 5000, 19602):
        cases.append({"axis": "faces-grid", "geometry": "grid", "faces": faces,
                      "width": 256, "height": 256, "samples": 1, "span": 2.0})
    # Multiple placements multiply planner work, not tile work.
    for count in (10, 40):
        cases.append({"axis": "faces-multi", "geometry": "grid", "faces": 500,
                      "placements": count, "width": 256, "height": 256,
                      "samples": 1, "span": 2.0})

    # --- sample sweep: fixed 256x256 output, samples 1 and 2 ----------------
    for samples in (1, 2):
        cases.append({"axis": "samples", "geometry": "grid", "faces": 5000,
                      "width": 256, "height": 256, "samples": samples, "span": 2.0})
    # Largest legal canvas/faces/samples combination (limits: 512x512, s2,
    # 40000 source faces).
    cases.append({"axis": "max-legal", "geometry": "grid", "faces": 19602,
                  "width": 512, "height": 512, "samples": 2, "span": 2.0})
    cases.append({"axis": "max-legal-fan", "geometry": "fan", "faces": 8000,
                  "width": 512, "height": 512, "samples": 2, "span": 2.0})

    results = []
    out_path = os.path.join(HERE, "results", "sweep.jsonl")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as sink:
        for index, case in enumerate(cases, 1):
            print("case %d/%d %s" % (index, len(cases), case), file=sys.stderr)
            try:
                record = run(case)
            except subprocess.TimeoutExpired:
                record = {"spec": case, "crash": "harness timeout 300s"}
            record["case"] = case
            results.append(record)
            sink.write(json.dumps(record, ensure_ascii=False) + "\n")
            sink.flush()
    print(json.dumps({"cases": len(results), "output": out_path}))


if __name__ == "__main__":
    main()
