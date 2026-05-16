"""
naca.py — NACA 4-digit airfoil generator.

Produces 2D coordinates (Selig .dat format) and 3D extruded STL meshes
suitable for snappyHexMesh in OpenFOAM.

Examples:
    # 2D coordinates for NACA 2412 at unit chord
    python naca.py 2412 --dat 2412.dat

    # 3D STL: NACA 0012, 1 m chord, 0.5 m span, no twist
    python naca.py 0012 --chord 1.0 --span 0.5 --stl 0012.stl

    # Tapered, twisted foil (e.g. a keel)
    python naca.py 0012 --chord 1.0 --tip-chord 0.6 --span 1.5 --twist -3 --stl keel.stl
"""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass
class NACA4:
    """NACA 4-digit airfoil. m, p, t are all fractions of chord."""
    m: float  # max camber, e.g. 0.02 for "2412"
    p: float  # position of max camber, e.g. 0.4 for "2412"
    t: float  # max thickness, e.g. 0.12 for "2412"

    @classmethod
    def from_designation(cls, designation: str) -> NACA4:
        designation = designation.strip().lstrip("naca").lstrip("NACA").strip()
        if len(designation) != 4 or not designation.isdigit():
            raise ValueError(f"Expected 4-digit NACA designation, got '{designation}'")
        return cls(
            m=int(designation[0]) / 100.0,
            p=int(designation[1]) / 10.0,
            t=int(designation[2:]) / 100.0,
        )

    def thickness(self, x: float, closed_te: bool = True) -> float:
        """Half-thickness y_t at chordwise position x ∈ [0, 1]."""
        # Last coefficient: -0.1036 closes the TE exactly; -0.1015 is the original (~0.21% gap).
        a4 = -0.1036 if closed_te else -0.1015
        return 5.0 * self.t * (
            0.2969 * math.sqrt(x)
            - 0.1260 * x
            - 0.3516 * x ** 2
            + 0.2843 * x ** 3
            + a4 * x ** 4
        )

    def camber(self, x: float) -> tuple[float, float]:
        """Camber line height y_c and slope dy_c/dx at x ∈ [0, 1]."""
        if self.m == 0 or self.p == 0:
            return 0.0, 0.0
        if x < self.p:
            yc = (self.m / self.p ** 2) * (2 * self.p * x - x ** 2)
            dyc = (2 * self.m / self.p ** 2) * (self.p - x)
        else:
            yc = (self.m / (1 - self.p) ** 2) * ((1 - 2 * self.p) + 2 * self.p * x - x ** 2)
            dyc = (2 * self.m / (1 - self.p) ** 2) * (self.p - x)
        return yc, dyc

    def surface(self, n_points: int = 200, closed_te: bool = True) -> tuple[list[float], list[float]]:
        """
        Return (x, y) coordinates traversing the airfoil in Selig order:
        TE upper → LE → TE lower.
        Cosine spacing clusters points at leading and trailing edges.
        """
        xs = [0.5 * (1 - math.cos(math.pi * i / (n_points - 1))) for i in range(n_points)]
        upper_x, upper_y, lower_x, lower_y = [], [], [], []
        for x in xs:
            yt = self.thickness(x, closed_te)
            yc, dyc = self.camber(x)
            theta = math.atan(dyc)
            upper_x.append(x - yt * math.sin(theta))
            upper_y.append(yc + yt * math.cos(theta))
            lower_x.append(x + yt * math.sin(theta))
            lower_y.append(yc - yt * math.cos(theta))
        # Selig: TE upper → LE → TE lower. Skip the duplicated LE point.
        x_out = list(reversed(upper_x)) + lower_x[1:]
        y_out = list(reversed(upper_y)) + lower_y[1:]
        return x_out, y_out


def write_dat(designation: str, x: list[float], y: list[float], chord: float, path: Path) -> None:
    """Write Selig-format .dat file, scaled to chord."""
    with path.open("w") as f:
        f.write(f"NACA {designation}\n")
        for xi, yi in zip(x, y):
            f.write(f"{xi * chord:.6f}  {yi * chord:.6f}\n")


def write_stl(
    x: list[float],
    y: list[float],
    root_chord: float,
    tip_chord: float,
    span: float,
    twist_deg: float,
    path: Path,
) -> None:
    """
    Write an ASCII STL of a linearly-tapered, linearly-twisted foil.
    Root is at z=0 with zero twist, tip is at z=span scaled to tip_chord with `twist_deg`.
    """
    n = len(x)

    def section(z: float, chord: float, twist_rad: float) -> list[tuple[float, float, float]]:
        c, s = math.cos(twist_rad), math.sin(twist_rad)
        return [
            (chord * (xi * c - yi * s),
             chord * (xi * s + yi * c),
             z)
            for xi, yi in zip(x, y)
        ]

    root = section(0.0, root_chord, 0.0)
    tip = section(span, tip_chord, math.radians(twist_deg))

    tris: list[tuple[tuple[float, float, float], ...]] = []
    for i in range(n - 1):
        a, b = root[i], root[i + 1]
        c, d = tip[i], tip[i + 1]
        tris.append((a, b, d))
        tris.append((a, d, c))

    def cap(pts: list[tuple[float, float, float]], flip: bool) -> None:
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        cz = pts[0][2]
        centre = (cx, cy, cz)
        for i in range(n - 1):
            a, b = pts[i], pts[i + 1]
            tris.append((centre, b, a) if flip else (centre, a, b))

    cap(root, flip=True)   # root face points in -z
    cap(tip, flip=False)   # tip face points in +z

    with path.open("w") as f:
        f.write("solid foil\n")
        for tri in tris:
            a, b, c = tri
            ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
            vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
            nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            mag = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            f.write(f"  facet normal {nx/mag:.6f} {ny/mag:.6f} {nz/mag:.6f}\n")
            f.write("    outer loop\n")
            for p in (a, b, c):
                f.write(f"      vertex {p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\n")
            f.write("    endloop\n  endfacet\n")
        f.write("endsolid foil\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate NACA 4-digit airfoil geometry.")
    ap.add_argument("designation", help="NACA 4-digit code, e.g. 2412")
    ap.add_argument("--chord", type=float, default=1.0, help="Root chord [m] (default 1.0)")
    ap.add_argument("--tip-chord", type=float, default=None,
                    help="Tip chord for tapered foils [m] (default = same as root)")
    ap.add_argument("--span", type=float, default=1.0, help="Span for STL extrude [m] (default 1.0)")
    ap.add_argument("--twist", type=float, default=0.0, help="Tip twist [deg] (default 0)")
    ap.add_argument("--points", type=int, default=200, help="Points per surface (default 200)")
    ap.add_argument("--open-te", action="store_true",
                    help="Use original NACA TE (small gap) instead of closed TE")
    ap.add_argument("--dat", type=Path, help="Write Selig .dat file")
    ap.add_argument("--stl", type=Path, help="Write extruded STL file")
    args = ap.parse_args()

    foil = NACA4.from_designation(args.designation)
    x, y = foil.surface(args.points, closed_te=not args.open_te)

    wrote = False
    if args.dat:
        write_dat(args.designation, x, y, args.chord, args.dat)
        print(f"Wrote {args.dat}")
        wrote = True
    if args.stl:
        tip_chord = args.tip_chord if args.tip_chord is not None else args.chord
        write_stl(x, y, args.chord, tip_chord, args.span, args.twist, args.stl)
        print(f"Wrote {args.stl}")
        wrote = True
    if not wrote:
        # Sanity dump
        print(f"NACA {args.designation}: m={foil.m}, p={foil.p}, t={foil.t}")
        print(f"{len(x)} points")
        for xi, yi in list(zip(x, y))[:: max(1, len(x) // 10)]:
            print(f"  {xi:.4f}  {yi:.4f}")


if __name__ == "__main__":
    main()