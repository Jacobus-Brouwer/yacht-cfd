"""
new_design.py — create a self-contained project folder for one yacht design.

Each design lives in projects/<name>/ with:
  parameters.json — the inputs that generated this design
  section.dat     — Selig 2D coordinates
  geometry.stl    — 3D extruded STL ready for snappyHexMesh

Re-running with an existing name fails loudly rather than overwriting silently.

Examples:
    python scripts/new_design.py main_keel \\
        --naca 0012 --chord 1.0 --tip-chord 0.6 --span 1.5 --twist -3

    python scripts/new_design.py test_rudder \\
        --naca 0015 --chord 0.4 --span 0.8
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running as `python scripts/new_design.py …` from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from geometry.sections import NACA4, write_dat, write_stl


def create_design(name: str, params: dict, root: Path = Path("projects")) -> Path:
    """
    Create a project folder containing the inputs and generated geometry.
    Returns the path to the created folder.
    """
    folder = root / name
    if folder.exists():
        raise FileExistsError(f"Project already exists: {folder}")
    folder.mkdir(parents=True)

    # Record inputs so the design is reproducible
    (folder / "parameters.json").write_text(json.dumps(params, indent=2) + "\n")

    # Generate the geometry
    foil = NACA4.from_designation(params["naca"])
    x, y = foil.surface(params.get("points", 200), closed_te=True)

    write_dat(params["naca"], x, y, params["chord"], folder / "section.dat")
    write_stl(
        x, y,
        params["chord"],
        params.get("tip_chord", params["chord"]),
        params.get("span", 1.0),
        params.get("twist", 0.0),
        folder / "geometry.stl",
    )
    return folder


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Create a new yacht-design project folder.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("name", help="Project name (folder becomes projects/<name>/)")
    ap.add_argument("--naca", required=True, help="NACA 4-digit code, e.g. 0012")
    ap.add_argument("--chord", type=float, required=True, help="Root chord [m]")
    ap.add_argument("--tip-chord", type=float, default=None,
                    help="Tip chord [m] (default = root chord)")
    ap.add_argument("--span", type=float, default=1.0, help="Span [m]")
    ap.add_argument("--twist", type=float, default=0.0, help="Tip twist [deg]")
    ap.add_argument("--points", type=int, default=200, help="Surface points")
    ap.add_argument("--root", type=Path, default=Path("projects"),
                    help="Projects folder (default: ./projects)")
    args = ap.parse_args()

    params = {
        "naca": args.naca,
        "chord": args.chord,
        "tip_chord": args.tip_chord if args.tip_chord is not None else args.chord,
        "span": args.span,
        "twist": args.twist,
        "points": args.points,
    }

    try:
        folder = create_design(args.name, params, root=args.root)
    except FileExistsError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)

    print(f"Created {folder}/")
    for path in sorted(folder.iterdir()):
        size = path.stat().st_size
        print(f"  {path.name:<20} {size:>8} bytes")


if __name__ == "__main__":
    main()