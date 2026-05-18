"""
avl_loading.py — wrap the AVL binary and return aerodynamic results.

Interface
---------
    run(geometry_file, alphas, Re, V) -> list[dict]

Each dict in the returned list is one row in the results table:
  - Integrated (FT) rows have station_y = float('nan').
  - Strip (FS) rows have station_y = the strip's Yle position.
  - The schema matches what pd.DataFrame(rows) would produce once pandas
    is added to the stack.

Schema columns
--------------
  alpha          float   angle of attack [deg]
  solver         str     "avl"
  solver_version str     from AVL's startup banner, e.g. "3.52"
  station_y      float   NaN for totals; strip Yle [m] for strip rows
  CL             float   integrated lift coefficient      (NaN for strip rows)
  CD             float   integrated drag coefficient      (NaN for strip rows)
  CDind          float   induced drag coefficient         (NaN for strip rows)
  Cm             float   pitching-moment coefficient      (NaN for strip rows)
  chord          float   strip chord [m]                  (NaN for total rows)
  area           float   strip panel area [m²]            (NaN for total rows)
  cl             float   strip section lift coefficient   (NaN for total rows)
  cd             float   strip section drag coefficient   (NaN for total rows)
  cm             float   strip section pitching moment    (NaN for total rows)
  ai             float   strip induced angle of attack [deg] (NaN for total rows)

Command sequence sent to AVL (one invocation per geometry)
----------------------------------------------------------
  LOAD <geometry.avl>
  OPER
  M
  V <V>          — set airspeed
                 — blank exits M submenu
  [for each alpha:]
  A A <alpha>    — set angle of attack
  X              — execute; AVL prints FT forces automatically
  ft             — reprint FT block (blank → screen output)
                 — blank for ft filename prompt
  fs             — print FS strip forces (blank → screen output)
                 — blank for fs filename prompt
  [end repeat]
                 — blank exits OPER
  QUIT

Notes
-----
  - PACC is not used; all data is parsed from stdout.
  - Re is accepted for schema compatibility but is unused by AVL (inviscid).
  - Paths are kept relative to CWD to avoid Fortran's ~64-char filename limit
    (the same bug as XFOIL; see xfoil_polar.py for context).
  - If AVL crashes mid-sweep, successfully parsed rows are returned and a
    warnings.warn is issued for each alpha that produced no FT data.

Examples
--------
    from pathlib import Path
    from scripts.avl_loading import run

    rows = run(Path("projects/main_keel/keel.avl"),
               alphas=[-5, 0, 5, 10], Re=3e6, V=3.0)
    integrated = [r for r in rows if r["station_y"] != r["station_y"]]
    print(integrated[0]["CL"])
"""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import sys
import warnings
from pathlib import Path


AVL_TIMEOUT_SECONDS = 300

_NAN = float("nan")

# ── regex patterns ────────────────────────────────────────────────────────────
_RE_VERSION = re.compile(
    r"Athena Vortex Lattice\s+Program\s+Version\s+([\d.]+)"
)
_RE_FT_ALPHA = re.compile(r"Alpha\s*=\s*([-+]?\d+\.\d+)")
_RE_CLTOT = re.compile(r"CLtot\s*=\s*([-+]?\d+\.\d+)")
_RE_CDTOT = re.compile(r"CDtot\s*=\s*([-+]?\d+\.\d+)")
_RE_CDIND = re.compile(r"CDind\s*=\s*([-+]?\d+\.\d+)")
_RE_CMTOT = re.compile(r"Cmtot\s*=\s*([-+]?\d+\.\d+)")

# Strip data header sentinel
_STRIP_HDR = "Strip Forces referred to Strip Area, Chord"
# Strip data line: leading int j followed by 14 floats
_RE_STRIP_ROW = re.compile(
    r"^\s+(\d+)"                    # j
    + (r"\s+([-+]?\d+\.\d+)" * 14) # Xle Yle Zle Chord Area c_cl ai cl_norm cl cd cdv cm_c/4 cm_LE CPx
)
# Indices into the 14 float captures (0-based after j):
# 0:Xle 1:Yle 2:Zle 3:Chord 4:Area 5:c_cl 6:ai 7:cl_norm 8:cl 9:cd 10:cdv 11:cm_c/4 12:cm_LE 13:CPx
_I_YLE, _I_CHORD, _I_AREA = 1, 3, 4
_I_AI, _I_CL, _I_CD, _I_CM = 6, 8, 9, 11

_FT_SENTINEL = "Vortex Lattice Output -- Total Forces"
_FS_SENTINEL = "Surface and Strip Forces by surface"


# ── internal helpers ──────────────────────────────────────────────────────────

def _avl_version(stdout: str) -> str:
    """Extract version string from AVL's startup banner."""
    m = _RE_VERSION.search(stdout)
    return m.group(1) if m else "unknown"


def _safe_load_path(p: Path) -> str:
    """
    Return a relative-path string for the AVL LOAD command.

    AVL (Fortran) has a ~64-character filename buffer.  Absolute paths that
    include the full repo path easily exceed this.  A relative path from CWD
    is always short enough.
    """
    try:
        return str(Path(os.path.relpath(p)))
    except ValueError:
        # relpath can fail on Windows when source and target are on different
        # drives; fall back to absolute in that unlikely case.
        return str(p)


def build_avl_commands(
    geometry_file: Path,
    V: float,
    alphas: list[float],
) -> str:
    """
    Build the stdin command string for one AVL run over the given alpha list.

    AVL is interactive: every 'ft' and 'fs' command prompts for a filename;
    an empty line selects screen (stdout) output.  The blank after each
    prompt is explicit in the returned string.
    """
    load_path = _safe_load_path(geometry_file)
    cmds: list[str] = [
        f"LOAD {load_path}",
        "OPER",
        "M",           # enter parameter-modify submenu
        f"V {V:.6f}",  # set airspeed
        "",            # blank exits M submenu
    ]
    for alpha in alphas:
        cmds += [
            f"A A {alpha:.6f}",  # set alpha constraint
            "X",                 # execute; prints FT automatically
            "ft",                # re-print FT (blank → screen)
            "",
            "fs",                # print FS strip forces (blank → screen)
            "",
        ]
    cmds += [
        "",       # blank exits OPER
        "QUIT",
        "",
    ]
    return "\n".join(cmds) + "\n"


def _parse_ft_block(lines: list[str], start: int) -> dict | None:
    """
    Parse one FT block beginning at *start* (the line containing the sentinel).
    Returns a partial integrated-row dict, or None on parse failure.
    """
    alpha = cl = cd = cdind = cm = _NAN
    for line in lines[start:start + 60]:
        if not math.isnan(alpha) and _RE_FT_ALPHA.search(line):
            pass  # alpha already set; skip later occurrences
        m = _RE_FT_ALPHA.search(line)
        if m and math.isnan(alpha):
            alpha = float(m.group(1))
        m = _RE_CLTOT.search(line)
        if m:
            cl = float(m.group(1))
        m = _RE_CDTOT.search(line)
        if m:
            cd = float(m.group(1))
        m = _RE_CDIND.search(line)
        if m:
            cdind = float(m.group(1))
        m = _RE_CMTOT.search(line)
        if m:
            cm = float(m.group(1))
        # End of FT block
        if line.strip() == "-" * 63:
            break
    if math.isnan(alpha) or math.isnan(cl):
        return None
    return {
        "alpha": alpha,
        "station_y": _NAN,
        "CL": cl, "CD": cd, "CDind": cdind, "Cm": cm,
        "chord": _NAN, "area": _NAN,
        "cl": _NAN, "cd": _NAN, "cm": _NAN, "ai": _NAN,
    }


def _parse_fs_block(
    lines: list[str],
    start: int,
    alpha: float,
) -> list[dict]:
    """
    Parse one FS block beginning at *start* (the line containing the sentinel).
    Returns a list of strip-row dicts, one per data line across all surfaces.
    """
    rows: list[dict] = []
    in_strip_section = False
    for line in lines[start:]:
        if _STRIP_HDR in line:
            in_strip_section = True
            continue
        if in_strip_section:
            m = _RE_STRIP_ROW.match(line)
            if m:
                floats = [float(m.group(i + 2)) for i in range(14)]
                rows.append({
                    "alpha": alpha,
                    "station_y": floats[_I_YLE],
                    "CL": _NAN, "CD": _NAN, "CDind": _NAN, "Cm": _NAN,
                    "chord": floats[_I_CHORD],
                    "area":  floats[_I_AREA],
                    "cl":    floats[_I_CL],
                    "cd":    floats[_I_CD],
                    "cm":    floats[_I_CM],
                    "ai":    floats[_I_AI],
                })
            elif line.strip().startswith("-" * 20):
                # End of FS block
                break
    return rows


def parse_avl_stdout(stdout: str, version: str) -> list[dict]:
    """
    Walk AVL's stdout and return a flat list of result dicts.

    FT blocks appear twice per alpha (once from X, once from explicit ft);
    the last value for each alpha is kept — both are identical so it doesn't
    matter which wins.  FS blocks are associated with the alpha of the most
    recently seen FT block.
    """
    lines = stdout.splitlines()

    # integrated: keyed by rounded alpha to deduplicate double-prints
    integrated: dict[float, dict] = {}
    current_alpha = _NAN

    strip_rows: list[dict] = []

    for i, line in enumerate(lines):
        if _FT_SENTINEL in line:
            row = _parse_ft_block(lines, i)
            if row is not None:
                key = round(row["alpha"], 4)
                row.update(solver="avl", solver_version=version)
                integrated[key] = row
                current_alpha = row["alpha"]

        elif _FS_SENTINEL in line and not math.isnan(current_alpha):
            strips = _parse_fs_block(lines, i, current_alpha)
            for s in strips:
                s.update(solver="avl", solver_version=version)
            strip_rows.extend(strips)

    return list(integrated.values()) + strip_rows


# ── public API ────────────────────────────────────────────────────────────────

def run(
    geometry_file: Path,
    alphas: list[float],
    Re: float,
    V: float,
) -> list[dict]:
    """
    Run AVL on *geometry_file* across *alphas* and return a flat result table.

    Parameters
    ----------
    geometry_file : Path
        Path to the .avl geometry file (absolute or relative to CWD).
    alphas : list[float]
        Angles of attack to evaluate [deg].
    Re : float
        Reynolds number — accepted for schema compatibility, not used by AVL
        (inviscid solver).
    V : float
        Free-stream velocity [m/s or consistent units].  Affects dynamic
        pressure; non-dimensional coefficients are independent of V for an
        inviscid run with no profile drag override.

    Returns
    -------
    list[dict]
        One dict per row.  Integrated-total rows have station_y=NaN; strip
        rows have station_y=Yle.  Suitable for pd.DataFrame(rows) once pandas
        is available.  Missing scalars carry float('nan').

    Warnings
    --------
    Issues warnings.warn for any alpha in *alphas* that produced no FT data,
    e.g. if AVL crashed partway through the sweep.  Does not raise.
    """
    if shutil.which("avl") is None:
        raise RuntimeError(
            "avl not found in PATH.  On Gentoo: sudo emerge sci-physics/avl"
        )

    commands = build_avl_commands(geometry_file, V, alphas)

    try:
        result = subprocess.run(
            ["avl"],
            input=commands,
            capture_output=True,
            text=True,
            timeout=AVL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"AVL timed out after {AVL_TIMEOUT_SECONDS}s"
        )

    version = _avl_version(result.stdout)
    rows = parse_avl_stdout(result.stdout, version)

    # Warn for any alpha that got no integrated result
    parsed_alphas = {
        round(r["alpha"], 4)
        for r in rows
        if math.isnan(r["station_y"])
    }
    for alpha in alphas:
        if round(alpha, 4) not in parsed_alphas:
            warnings.warn(
                f"avl_loading: no converged result for alpha={alpha:.4f}; "
                "check AVL stdout for geometry or execution errors.",
                RuntimeWarning,
                stacklevel=2,
            )

    return rows


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    import csv

    ap = argparse.ArgumentParser(
        description="Run AVL on a project's geometry.avl and print results."
    )
    ap.add_argument("project", help="Project name under projects/")
    ap.add_argument("--V", type=float, default=3.0,
                    help="Airspeed [m/s] (default: 3.0)")
    ap.add_argument("--re", type=float, default=3e6,
                    help="Reynolds number (default: 3e6, stored only)")
    ap.add_argument("--alpha", type=float, nargs=3,
                    metavar=("MIN", "MAX", "STEP"),
                    default=[-10.0, 15.0, 1.0])
    ap.add_argument("--root", type=Path, default=Path("projects"))
    args = ap.parse_args()

    amin, amax, astep = args.alpha
    alphas = []
    a = amin
    while a <= amax + 1e-9:
        alphas.append(round(a, 6))
        a += astep

    geom = args.root / args.project / "geometry.avl"
    if not geom.exists():
        print(f"No geometry.avl at {geom}", file=sys.stderr)
        sys.exit(1)

    rows = run(geom, alphas, Re=args.re, V=args.V)
    integrated = [r for r in rows if math.isnan(r["station_y"])]
    if not integrated:
        print("No converged points.", file=sys.stderr)
        sys.exit(2)

    out = args.root / args.project / "polar.csv"
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
