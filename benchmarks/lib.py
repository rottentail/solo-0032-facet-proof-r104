"""Shared harness for Facet Proof resource-boundary measurements.

Produces deterministic geometry with controllable face count and screen
coverage, runs the real in-process Application API, and samples the worker
process RSS from a separate thread.

No production behaviour is altered here; the harness only drives public
routes and reads the same state an operator/worker would.
"""
import json
import math
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from facetproof.application import Application
from facetproof.routing import route_request, PREFIX


def read_rss_kb():
    try:
        with open("/proc/self/status") as stream:
            for line in stream:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return None


def peak_rss_kb():
    try:
        with open("/proc/self/status") as stream:
            for line in stream:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return None


class RssSampler:
    """Sample process RSS in a thread while one worker step runs."""

    def __init__(self, interval=0.02):
        self.interval = interval
        self.samples = []
        self._stop = threading.Event()
        self._thread = None

    def __enter__(self):
        self.samples.append(read_rss_kb())

        def loop():
            while not self._stop.wait(self.interval):
                value = read_rss_kb()
                if value is not None:
                    self.samples.append(value)

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=2)
        value = read_rss_kb()
        if value is not None:
            self.samples.append(value)

    @property
    def peak_mb(self):
        values = [v for v in self.samples if v is not None]
        return max(values) / 1024 if values else None

    @property
    def start_mb(self):
        values = [v for v in self.samples if v is not None]
        return values[0] / 1024 if values else None


def fan_mesh(faces, radius=1.0, z=0.0):
    """A radially symmetric fan of `faces` triangles centred on the origin.

    Triangles span a wide chord, so their screen-space bounding boxes are
    large even though total geometric area stays modest. This models a
    "long thin triangles / large coverage" load rather than a tessellated
    surface.
    """
    faces = int(faces)
    n = max(faces, 3)
    vertices = [[0.0, 0.0, z]]
    for i in range(n):
        angle = 2 * math.pi * i / n + 0.013
        vertices.append([radius * math.cos(angle), radius * math.sin(angle), z])
    # Skip antipodal pairs: centre + two exactly opposite rim points are
    # collinear and would be rejected as degenerate.
    step = n // 3
    if step in (0, n // 2):
        step = max(1, n // 3 - 1)
    built = []
    for i in range(n):
        j = (i + step) % n
        if j == i:
            continue
        built.append([0, i + 1, j + 1])
    # Pad with small adjacent fan triangles if the stride skipped some.
    i = 0
    while len(built) < faces:
        j = (i + 1) % n
        built.append([0, i + 1, j + 1])
        i += 1
    built = built[:faces]
    return {"name": "probe", "vertices": vertices, "faces": built}


def grid_mesh(faces, radius=1.0, z=0.0):
    """A square grid of two triangles per cell; total faces ~ faces."""
    cells = max(1, faces // 2)
    side = max(2, int(math.ceil(math.sqrt(cells))) + 1)
    vertices, index = [], {}
    step = 2 * radius / (side - 1)
    for y in range(side):
        for x in range(side):
            index[(x, y)] = len(vertices)
            vertices.append([-radius + x * step, -radius + y * step, z])
    built = []
    for y in range(side - 1):
        for x in range(side - 1):
            a, b = index[(x, y)], index[(x + 1, y)]
            c, d = index[(x, y + 1)], index[(x + 1, y + 1)]
            built.append([a, b, d])
            built.append([a, d, c])
            if len(built) >= faces:
                return {"name": "grid", "vertices": vertices, "faces": built[:faces]}
    return {"name": "grid", "vertices": vertices, "faces": built[:faces]}


class Harness:
    def __init__(self, root=None, capacity=2**40):
        self.root = root or tempfile.mkdtemp(prefix="facet-bench-")
        self.app = Application(self.root)
        self.call("PUT", "resources", {"capacity": capacity, "revision": 1})

    def call(self, method, route, data=None):
        return route_request(self.app, method, PREFIX + route, data)

    def setup(self, mesh, *, lens=None, illumination=None, placements=None,
              pigment=None, key_prefix="bench"):
        pigment = pigment or {"name": "釉青", "color": [0.12, 0.62, 0.61], "two_sided": True}
        self.mesh = self.call("POST", "meshes", mesh)
        self.pigment = self.call("POST", "pigments", pigment)
        assembly = self.call("POST", "assemblies", {
            "name": "边界测量", "lens": lens or {}, "illumination": illumination or {}})
        if placements is None:
            placements = [{"key": "body", "mesh_id": self.mesh["id"],
                           "pigment_id": self.pigment["id"]}]
        self.assembly = self.call("PUT", "assemblies/" + assembly["id"],
                                  {"revision": 1, "placements": placements})
        self.seal = self.call("POST", "assemblies/" + assembly["id"] + "/seal",
                              {"revision": 2})
        return self

    def submit(self, key, width, height, samples):
        return self.call("POST", "seals/" + self.seal["id"] + "/exposures",
                         {"key": key, "width": width, "height": height, "samples": samples})

    def step(self):
        started = time.monotonic()
        with RssSampler() as sampler:
            result = self.app.worker.run_one()
        elapsed = time.monotonic() - started
        return result, elapsed, sampler

    def cleanup(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)
