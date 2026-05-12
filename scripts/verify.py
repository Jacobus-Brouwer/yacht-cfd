"""
verify.py — visual sanity check for naca.py output.

Plots the 2D section (with camber line) and a 3D rendering of the extruded
foil side-by-side. matplotlib-only — no numpy, no extra deps.

Examples:
    python scripts/verify.py 2412
    python scripts/verify.py 0012 --chord 1.0 --tip-chord 0.6 --span 1.5 --twist -3
    python scripts/verify.py 4415 --save docs/4415.png
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import math

import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from geometry.sections import NACA4


def plot_section(ax, foil: NACA4, designation: str) -> None:
    x, y = foil.surface(200)
    ax.plot(x, y, linewidth=1.6, color="#1f77b4", label="surface")
    xs = [i / 100 for i in range(101)]
    yc = [foil.camber(xi)[0] for xi in xs]
    ax.plot(xs, yc, "--", color="#1f77b4", alpha=0.45, label="camber")
    ax.set_aspect("equal")
    ax.grid(alpha=0.3)
    ax.axhline(0, color="k", linewidth=0.4)
    ax.set_xlabel("x/c")
    ax.set_ylabel("y/c")
    ax.set_title(f"NACA {designation} — 2D section")
    ax.legend(loc="upper right", fontsize=9)


def plot_3d(ax, foil: NACA4, root_chord: float, tip_chord: float,
            span: float, twist_deg: float) -> None:
    x, y = foil.surface(120)

    def section(z: float, chord: float, twist_rad: float):
        c, s = math.cos(twist_rad), math.sin(twist_rad)
        return [(chord * (xi * c - yi * s),
                 chord * (xi * s + yi * c),
                 z) for xi, yi in zip(x, y)]

    root = section(0.0, root_chord, 0.0)
    tip = section(span, tip_chord, math.radians(twist_deg))

    faces = []
    for i in range(len(root) - 1):
        faces.append([root[i], root[i + 1], tip[i + 1], tip[i]])
    faces.append(root)
    faces.append(tip)

    poly = Poly3DCollection(faces, facecolor="#1f77b4", alpha=0.75,
                            edgecolor="k", linewidth=0.15)
    ax.add_collection3d(poly)

    all_pts = [p for f in faces for p in f]
    xs = [p[0] for p in all_pts]
    ys = [p[1] for p in all_pts]
    zs = [p[2] for p in all_pts]
    x_range = max(xs) - min(xs)
    z_range = max(zs) - min(zs)
    ax.set_xlim(min(xs), max(xs))
    ax.set_ylim(min(ys) * 4, max(ys) * 4)
    ax.set_zlim(min(zs), max(zs))
    ax.set_box_aspect([x_range, max(x_range, z_range) * 0.25, z_range])
    ax.set_xlabel("x [m] (chord)")
    ax.set_ylabel("y [m] (thickness, exaggerated)")
    ax.set_zlabel("z [m] (span)")
    ax.set_title("3D extrusion")
    ax.view_init(elev=22, azim=-135)


def main() -> None:
    ap = argparse.ArgumentParser(description="Visual verifier for naca.py output.")
    ap.add_argument("designation", help="NACA 4-digit code")
    ap.add_argument("--chord", type=float, default=1.0)
    ap.add_argument("--tip-chord", type=float, default=None)
    ap.add_argument("--span", type=float, default=1.0)
    ap.add_argument("--twist", type=float, default=0.0)
    ap.add_argument("--save", help="Save to file instead of opening a window")
    args = ap.parse_args()

    foil = NACA4.from_designation(args.designation)
    tip_chord = args.tip_chord if args.tip_chord is not None else args.chord

    fig = plt.figure(figsize=(14, 5))
    ax1 = fig.add_subplot(1, 2, 1)
    plot_section(ax1, foil, args.designation)
    ax2 = fig.add_subplot(1, 2, 2, projection="3d")
    plot_3d(ax2, foil, args.chord, tip_chord, args.span, args.twist)
    plt.tight_layout()

    if args.save:
        plt.savefig(args.save, dpi=110)
        print(f"Wrote {args.save}")
    else:
        plt.show()


if __name__ == "__main__":
    main()