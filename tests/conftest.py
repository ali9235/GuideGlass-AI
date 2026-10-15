import cv2
import numpy as np
import pytest
from guideglass.geometry import Intrinsics


@pytest.fixture
def unit_rgbd():
    """Deterministic SYNTHETIC unit fixture only; not an application/demo source."""
    rng = np.random.default_rng(421)
    rgb = rng.integers(0, 256, (240, 320, 3), dtype=np.uint8)
    rgb = cv2.GaussianBlur(rgb, (3, 3), 0)
    depth = np.full((240, 320), 2., np.float32)
    k = Intrinsics(320, 240, 250., 250., 159.5, 119.5, True, "synthetic_unit_fixture")
    return rgb, depth, k


class StubModels:
    """Unit tests exercise control logic separately from real model acceptance."""
    def availability(self): return {"device":"unit_stub"}
    def load(self, **kwargs): pass
    def detect(self, rgb): return []
    def depth(self, rgb): return np.full(rgb.shape[:2], 2., np.float32)


@pytest.fixture
def stub_models(): return StubModels()
