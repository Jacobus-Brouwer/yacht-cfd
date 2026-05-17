"""
plot_polar.py — plot a project's XFOIL polar with reference data overlay.

Reads projects/<name>/polar.csv and writes projects/<name>/polar.png:
  Three subplots:
    1. CL vs alpha
    2. CD vs alpha
    3. CL vs CD (the drag polar)
  Reference data from Abbott & von Doenhoff "Theory of Wing Sections"
  (NACA Report 824) overlaid for the canonical sections at Re=3e6,
  smooth surface, when the section matches.

Examples:
    python scripts/plot_polar.py main_keel
    python scripts/plot_polar.py main_keel --no-reference
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt


# Reference data digitised from Abbott & von Doenhoff "Theory of Wing Sections"
# (1959 Dover reprint of NACA Report 824), smooth-surface measurements at Re=3e6.
# Columns: alpha, CL, CD, CM_c/4.
# Sparse — these are anchor points read off the published curves, not exhaustive.
# Used purely for "does our polar pass through these points within tolerance?"
REPORT_824 = {
    "0012": [
        # (alpha, CL,    CD,      CM)
        (-8.0,  -0.85,   0.0114, -0.001),
        (-4.0,  -0.43,   0.0066, -0.001),
        ( 0.0,   0.000,  0.0055,  0.000),
        ( 4.0,   0.43,   0.0066,  0.000),
        ( 8.0,   0.85,   0.0114, -0.001),
        (12.0,   1.25,   0.0192, -0.001),
        (16.0,   1.45,   0.0334, -0.003),  # near stall
    ],
    "2412": [
        (-8.0,  -0.65,   0.0124, -0.040),
        (-4.0,  -0.20,   0.0080, -0.043),
        ( 0.0,   0.250,  0.0067, -0.047),
        ( 4.0,   0.68,   0.0084, -0.046),
        ( 8.0,   1.05,   0.0136, -0.045),
        (12.0,   1.40,   0.0220, -0.044),
        (16.0,   1.58,   0.0380, -0.040),
    ],
    "4412": [
        (-8.0,  -0.40,   0.0150, -0.090),
        (-4.0,   0.05,   0.0094, -0.092),
        ( 0.0,   0.50,   0.0082, -0.095),
        ( 4.0,   0.93,   0.0098, -0.094),
        ( 8.0,   1.32,   0.0148, -0.092),
        (12.0,   1.55,   0.0232, -0.087),
        (14.0,   1.62,   0.0290, -0.080),  # near stall
    ],
    "0015": [
        (-8.0,  -0.84,   0.0132, -0.001),
        (-4.0,  -0.42,   0.0080, -0.001),
        ( 0.0,   0.000,  0.0069,  0.000),
        ( 4.0,   0.42,   0.0080,  0.000),
        ( 8.0,   0.84,   0.0132, -0.001),
        (12.0,   1.20,   0.0214, -0.002),
        (16.0,   1.40,   0.0380, -0.004),  # past stall onset
    ],
}


def load_polar(csv_path: Path) -> list[dict]:
    with csv_path.open() as f:
        return [
            {k: float(v) for k, v in row.items()}
            for row in csv.DictReader(f)
        ]


def load_naca_designation(project_dir: Path) -> str | None:
    """Try to read the NACA designation from parameters.json so we know
    which reference data (if any) to overlay."""
    params_path = project_dir / "parameters.json"
    if not params_path.exists():
        return None
    try:
        return json.loads(params_path.read_text()).get("naca")
    except (json.JSONDecodeError, OSError):
        return None


def plot_polar(rows: list[dict], naca: str | None, output: Path,
               show_reference: bool = True) -> None:
    alpha = [r["alpha"] for r in rows]
    cl = [r["CL"] for r in rows]
    cd = [r["CD"] for r in rows]

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))

    ref = REPORT_824.get(naca) if (show_reference and naca) else None
    ref_label = f"NACA Report 824 (Re=3×10⁶)" if ref else None

    # CL vs alpha
    ax = axes[0]
    ax.plot(alpha, cl, color="#1f77b4", linewidth=2.4, label="XFOIL (this run)")
    if ref:
        ax.plot([p[0] for p in ref], [p[1] for p in ref],
                "o", color="#d62728", markersize=6, label=ref_label)
    ax.set_xlabel("α (degrees)")
    ax.set_ylabel("C_L")
    ax.set_title("Lift coefficient")
    ax.grid(alpha=0.3)
    ax.axhline(0, color="k", linewidth=0.4)
    ax.axvline(0, color="k", linewidth=0.4)
    ax.legend(fontsize=9, loc="best")

    # CD vs alpha (note: log-scale Y looks nicer but keep linear for first version)
    ax = axes[1]
    ax.plot(alpha, cd, color="#1f77b4", linewidth=2.4, label="XFOIL (this run)")
    if ref:
        ax.plot([p[0] for p in ref], [p[2] for p in ref],
                "o", color="#d62728", markersize=6, label=ref_label)
    ax.set_xlabel("α (degrees)")
    ax.set_ylabel("C_D")
    ax.set_title("Drag coefficient")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=9, loc="best")

    # CL vs CD (drag polar)
    ax = axes[2]
    ax.plot(cd, cl, color="#1f77b4", linewidth=2.4, label="XFOIL (this run)")
    if ref:
        ax.plot([p[2] for p in ref], [p[1] for p in ref],
                "o", color="#d62728", markersize=6, label=ref_label)
    ax.set_xlabel("C_D")
    ax.set_ylabel("C_L")
    ax.set_title("Drag polar")
    ax.grid(alpha=0.3)
    ax.axhline(0, color="k", linewidth=0.4)
    ax.legend(fontsize=9, loc="best")

    title_bits = []
    if naca:
        title_bits.append(f"NACA {naca}")
    title_bits.append(f"{len(rows)} converged points")
    fig.suptitle(" — ".join(title_bits), fontsize=13)
    fig.tight_layout()

    fig.savefig(output, dpi=120)
    print(f"Wrote {output}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Plot a project's XFOIL polar.")
    ap.add_argument("project", help="Project name under projects/")
    ap.add_argument("--root", type=Path, default=Path("projects"),
                    help="Projects folder (default: ./projects)")
    ap.add_argument("--no-reference", action="store_true",
                    help="Skip NACA Report 824 reference overlay even if available")
    args = ap.parse_args()

    project = args.root / args.project
    csv_path = project / "polar.csv"
    if not csv_path.exists():
        print(f"No polar.csv at {csv_path} — run scripts/xfoil_polar.py first",
              file=sys.stderr)
        sys.exit(1)

    rows = load_polar(csv_path)
    if not rows:
        print(f"polar.csv at {csv_path} is empty", file=sys.stderr)
        sys.exit(1)

    naca = load_naca_designation(project)
    output = project / "polar.png"
    plot_polar(rows, naca, output, show_reference=not args.no_reference)


if __name__ == "__main__":
    main()