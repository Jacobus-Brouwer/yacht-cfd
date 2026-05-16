"""
validate.py — run the full geometry → XFOIL → plot pipeline across the
canonical NACA reference sections and produce a single composite figure
overlaying each generated polar against NACA Report 824 measurements.

This is the V&V harness. It exists to prove that the geometry generator +
XFOIL wrapper produce results consistent with the canonical wind-tunnel
data, across both symmetric and cambered sections, thin and thick.

Sections validated: 0012, 2412, 4412, 0015. All at Re=3×10⁶ (Report 824's
standard reference condition).

Output: docs/validation.png — the single chart for the README.

Examples:
    python scripts/validate.py
    python scripts/validate.py --alpha -10 18 0.5
    python scripts/validate.py --re 3e6 --output docs/validation.png
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import matplotlib.pyplot as plt

# Make scripts/ importable so we can reuse load_polar and REPORT_824
sys.path.insert(0, str(Path(__file__).resolve().parent))
from plot_polar import REPORT_824, load_polar       # noqa: E402


SECTIONS = ["0012", "2412", "4412", "0015"]


def run(cmd: list[str], **kwargs) -> None:
    """Run a subprocess, printing the command, raise on failure."""
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")


def ensure_polar(
    project_name: str,
    naca: str,
    re: float,
    alpha: tuple[float, float, float],
    projects_root: Path,
    force: bool,
) -> Path:
    """Create the project and run XFOIL if polar.csv doesn't already exist."""
    project_dir = projects_root / project_name
    csv_path = project_dir / "polar.csv"

    if csv_path.exists() and not force:
        print(f"[{naca}] polar.csv exists, skipping (use --force to regenerate)")
        return csv_path

    # Wipe any stale half-built project so new_design.py doesn't refuse
    if project_dir.exists():
        shutil.rmtree(project_dir)

    print(f"[{naca}] generating and running")
    run([sys.executable, "scripts/new_design.py", project_name,
         "--naca", naca, "--chord", "1.0", "--span", "1.0"])
    run([sys.executable, "scripts/xfoil_polar.py", project_name,
         "--re", f"{re}",
         "--alpha", f"{alpha[0]}", f"{alpha[1]}", f"{alpha[2]}"])
    return csv_path


def plot_validation(naca_list: list[str], polars: dict[str, list[dict]],
                    output: Path, re: float) -> None:
    """Build a 4-row × 3-column figure: one row per section, columns are
    CL/α, CD/α, drag polar."""
    fig, axes = plt.subplots(len(naca_list), 3,
                             figsize=(15, 3.7 * len(naca_list)),
                             squeeze=False)

    for row, naca in enumerate(naca_list):
        rows = polars[naca]
        ref = REPORT_824.get(naca, [])

        alpha = [r["alpha"] for r in rows]
        cl = [r["CL"] for r in rows]
        cd = [r["CD"] for r in rows]

        # CL vs alpha
        ax = axes[row][0]
        ax.plot(alpha, cl, color="#1f77b4", linewidth=1.8, label="XFOIL")
        if ref:
            ax.plot([p[0] for p in ref], [p[1] for p in ref],
                    "o", color="#d62728", markersize=5, label="Report 824")
        ax.set_xlabel("α (deg)")
        ax.set_ylabel("C_L")
        ax.set_title(f"NACA {naca}: Lift coefficient")
        ax.grid(alpha=0.3)
        ax.axhline(0, color="k", linewidth=0.4)
        ax.axvline(0, color="k", linewidth=0.4)
        if row == 0:
            ax.legend(fontsize=9, loc="best")

        # CD vs alpha
        ax = axes[row][1]
        ax.plot(alpha, cd, color="#1f77b4", linewidth=1.8, label="XFOIL")
        if ref:
            ax.plot([p[0] for p in ref], [p[2] for p in ref],
                    "o", color="#d62728", markersize=5, label="Report 824")
        ax.set_xlabel("α (deg)")
        ax.set_ylabel("C_D")
        ax.set_title(f"NACA {naca}: Drag coefficient")
        ax.grid(alpha=0.3)

        # CL vs CD
        ax = axes[row][2]
        ax.plot(cd, cl, color="#1f77b4", linewidth=1.8, label="XFOIL")
        if ref:
            ax.plot([p[2] for p in ref], [p[1] for p in ref],
                    "o", color="#d62728", markersize=5, label="Report 824")
        ax.set_xlabel("C_D")
        ax.set_ylabel("C_L")
        ax.set_title(f"NACA {naca}: Drag polar")
        ax.grid(alpha=0.3)
        ax.axhline(0, color="k", linewidth=0.4)

    fig.suptitle(
        f"yacht-cfd validation against NACA Report 824   (Re = {re:.0e})",
        fontsize=14, y=0.995,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.985])
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=120)
    print(f"Wrote {output}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Run the V&V harness across canonical NACA sections."
    )
    ap.add_argument("--re", type=float, default=3e6,
                    help="Reynolds number (default: 3e6)")
    ap.add_argument("--alpha", type=float, nargs=3,
                    metavar=("MIN", "MAX", "STEP"),
                    default=[-10.0, 18.0, 0.5],
                    help="Alpha sweep (default: -10 18 0.5)")
    ap.add_argument("--sections", nargs="+", default=SECTIONS,
                    help=f"NACA designations (default: {' '.join(SECTIONS)})")
    ap.add_argument("--root", type=Path, default=Path("projects"),
                    help="Projects folder (default: ./projects)")
    ap.add_argument("--output", type=Path, default=Path("docs/validation.png"),
                    help="Output figure path (default: docs/validation.png)")
    ap.add_argument("--force", action="store_true",
                    help="Regenerate even if polar.csv already exists")
    args = ap.parse_args()

    print(f"Validating {len(args.sections)} sections at Re={args.re:.2e}, "
          f"α from {args.alpha[0]}° to {args.alpha[1]}° step {args.alpha[2]}°\n")

    polars: dict[str, list[dict]] = {}
    for naca in args.sections:
        project_name = f"validate_naca{naca}"
        csv_path = ensure_polar(project_name, naca, args.re,
                                tuple(args.alpha), args.root, args.force)
        polars[naca] = load_polar(csv_path)
        print(f"[{naca}] {len(polars[naca])} converged points\n")

    plot_validation(args.sections, polars, args.output, args.re)


if __name__ == "__main__":
    main()