"""
tests/test_avl_wrapper.py — integration tests for the AVL wrapper.

Runs AVL against the hand-built rectangular-wing fixture and checks:
  1. Integrated (FT) CL at α=5° is within 1 % of the known-good AVL value.
  2. Strip (FS) data for each alpha has the expected station count and y range.
  3. At α=0°, CL = 0 exactly (symmetric airfoil, inviscid).
  4. Schema: all required keys are present with the correct types.

Run from the repo root:
    python -m unittest tests/test_avl_wrapper.py

The fixture is tests/fixtures/naca0012_rectangular_wing.avl:
  - Rectangular planform, NACA 0012, semi-span = 1 m, chord = 1 m
  - YDUPLICATE → full span = 2 m, AR_eff = 4
  - 20 spanwise strips per half → 40 strips total per alpha
  - Reference CL at α=5°: 0.43002 (AVL 3.52)
"""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

# Allow running from anywhere as long as the repo root is accessible
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.avl_loading import run  # noqa: E402


FIXTURE = REPO_ROOT / "tests" / "fixtures" / "naca0012_rectangular_wing.avl"
ALPHAS = [-5.0, 0.0, 5.0]
REF_CL_ALPHA5 = 0.43002   # AVL 3.52, rectangular NACA 0012 wing, AR_eff=4
REF_STRIPS_PER_ALPHA = 40  # 20 per half-wing × 2 (YDUPLICATE)
REF_Y_MIN = -0.9988        # tip strip of negative (YDUP) half
REF_Y_MAX = +0.9988        # tip strip of positive half

_SCHEMA_KEYS_INTEGRATED = {
    "alpha", "solver", "solver_version", "station_y",
    "CL", "CD", "CDind", "Cm",
    "chord", "area", "cl", "cd", "cm", "ai",
}
_SCHEMA_KEYS_STRIP = _SCHEMA_KEYS_INTEGRATED  # same set; NaN for unused fields


class TestAVLWrapperFixture(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.rows = run(FIXTURE, alphas=ALPHAS, Re=3e6, V=10.0)
        cls.integrated = [r for r in cls.rows if math.isnan(r["station_y"])]
        cls.strips     = [r for r in cls.rows if not math.isnan(r["station_y"])]

    # ── basic output presence ─────────────────────────────────────────────────

    def test_integrated_row_count(self):
        """One integrated row per alpha."""
        self.assertEqual(len(self.integrated), len(ALPHAS))

    def test_strip_row_count(self):
        """REF_STRIPS_PER_ALPHA strip rows for each alpha."""
        self.assertEqual(len(self.strips), REF_STRIPS_PER_ALPHA * len(ALPHAS))

    # ── schema ────────────────────────────────────────────────────────────────

    def test_integrated_schema(self):
        """Integrated rows carry all required keys."""
        for row in self.integrated:
            self.assertEqual(set(row.keys()), _SCHEMA_KEYS_INTEGRATED,
                             msg=f"Schema mismatch at alpha={row.get('alpha')}")

    def test_strip_schema(self):
        """Strip rows carry all required keys."""
        if not self.strips:
            self.skipTest("No strip rows returned")
        for row in self.strips[:5]:  # spot-check first 5
            self.assertEqual(set(row.keys()), _SCHEMA_KEYS_STRIP,
                             msg=f"Schema mismatch at station_y={row.get('station_y')}")

    def test_solver_metadata(self):
        """solver and solver_version are correctly populated."""
        for row in self.rows[:3]:
            self.assertEqual(row["solver"], "avl")
            self.assertNotEqual(row["solver_version"], "unknown")
            self.assertRegex(row["solver_version"], r"\d+\.\d+")

    # ── integrated force values ───────────────────────────────────────────────

    def test_cl_at_alpha5_within_1pct(self):
        """Integrated CL at α=5° matches reference within 1 %."""
        row = next(r for r in self.integrated if abs(r["alpha"] - 5.0) < 0.01)
        cl = row["CL"]
        rel_err = abs(cl - REF_CL_ALPHA5) / REF_CL_ALPHA5
        self.assertLess(rel_err, 0.01,
                        msg=f"CL={cl:.5f} deviates {rel_err*100:.2f}% from "
                            f"reference {REF_CL_ALPHA5}")

    def test_cl_zero_at_alpha0(self):
        """CL = 0 at α=0° for a symmetric airfoil (inviscid)."""
        row = next(r for r in self.integrated if abs(r["alpha"]) < 0.01)
        self.assertAlmostEqual(row["CL"], 0.0, places=4,
                               msg=f"CL={row['CL']} at alpha=0 should be 0")

    def test_cl_antisymmetric(self):
        """CL is antisymmetric: CL(-α) = -CL(+α) for a symmetric section."""
        neg = next(r for r in self.integrated if abs(r["alpha"] - (-5.0)) < 0.01)
        pos = next(r for r in self.integrated if abs(r["alpha"] - 5.0)  < 0.01)
        self.assertAlmostEqual(neg["CL"], -pos["CL"], places=4)

    def test_cd_nonnegative(self):
        """Induced drag is non-negative for all alphas."""
        for row in self.integrated:
            self.assertGreaterEqual(row["CDind"], 0.0,
                                    msg=f"Negative CDind at alpha={row['alpha']}")

    def test_integrated_strip_fields_are_nan(self):
        """Strip-specific fields in integrated rows are NaN."""
        for row in self.integrated:
            for key in ("chord", "area", "cl", "cd", "cm", "ai"):
                self.assertTrue(math.isnan(row[key]),
                                msg=f"Expected NaN for '{key}' in integrated row")

    # ── strip data ────────────────────────────────────────────────────────────

    def test_strip_y_range(self):
        """Strip Yle positions span from -1 to +1 (YDUPLICATE mirror included)."""
        if not self.strips:
            self.skipTest("No strip rows returned")
        alpha5 = [s for s in self.strips if abs(s["alpha"] - 5.0) < 0.01]
        yles = [s["station_y"] for s in alpha5]
        self.assertAlmostEqual(min(yles), REF_Y_MIN, places=3)
        self.assertAlmostEqual(max(yles), REF_Y_MAX, places=3)

    def test_strip_count_per_alpha(self):
        """Each alpha produces exactly REF_STRIPS_PER_ALPHA strip rows."""
        for alpha in ALPHAS:
            count = sum(1 for s in self.strips if abs(s["alpha"] - alpha) < 0.01)
            self.assertEqual(count, REF_STRIPS_PER_ALPHA,
                             msg=f"Wrong strip count at alpha={alpha}")

    def test_strip_cl_positive_at_alpha5(self):
        """Strip cl values on the positive-y side are positive at α=5°."""
        pos_strips = [s for s in self.strips
                      if abs(s["alpha"] - 5.0) < 0.01 and s["station_y"] > 0]
        for s in pos_strips:
            self.assertGreater(s["cl"], 0.0,
                               msg=f"Negative strip cl at y={s['station_y']}")

    def test_strip_integrated_fields_are_nan(self):
        """Integrated fields in strip rows are NaN."""
        if not self.strips:
            self.skipTest("No strip rows returned")
        for row in self.strips[:5]:
            for key in ("CL", "CD", "CDind", "Cm"):
                self.assertTrue(math.isnan(row[key]),
                                msg=f"Expected NaN for '{key}' in strip row")


if __name__ == "__main__":
    unittest.main()
