"""Two concurrent worker threads in one process, two max-size exposures.

Quota is measured in high-sample pixels, not memory. This measures whether
the per-process memory cost of concurrently executing two admitted jobs is
simply additive, which matters because the default capacity admits four
max-size canvases at once and the HTTP server is threaded.
"""
import json
import sys
import tempfile
import threading
import time
import shutil

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/benchmarks")

from lib import Harness, RssSampler, read_rss_kb, grid_mesh  # noqa: E402
from facetproof.application import Application  # noqa: E402


def main():
    root = tempfile.mkdtemp(prefix="facet-threads-")
    try:
        setup = Harness(root)
        setup.setup(grid_mesh(19602, 1.0),
                    lens={"eye": [0, 0, 5], "projection": "orthographic", "span": 2.0})
        exposures = [setup.submit("t1", 512, 512, 2), setup.submit("t2", 512, 512, 2)]
        apps = [Application(root), Application(root)]
        results = {}

        def run(index):
            started = time.monotonic()
            results[index] = {"state": apps[index].worker.run_one().get("state"),
                              "wall_s": round(time.monotonic() - started, 2)}

        baseline = read_rss_kb() / 1024
        with RssSampler() as sampler:
            threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=300)
        final = Application(root)
        output = {
            "baseline_rss_mb": round(baseline, 1),
            "peak_rss_mb": round(sampler.peak_mb, 1),
            "delta_rss_mb": round(sampler.peak_mb - baseline, 1),
            "worker_results": results,
            "exposure_states": [final.exposures.get(e["id"])["state"] for e in exposures],
            "capacity_after": final.resources.snapshot()["reserved"],
        }
        print(json.dumps(output))
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
