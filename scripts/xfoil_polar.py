"""
xfoil_polar.py — run XFOIL on a project's section.dat and save the polar.

Reads a project folder under projects/<name>/, runs XFOIL across an alpha
range at a given Reynolds number, parses the output, and writes:
  xfoil_input.dat  — sanitized .dat fed to XFOIL
  xfoil_stdout.log — XFOIL's full stdout (saved every run, parser source)
  polar.csv        — parsed polar as CSV for pandas / plotting

PACC (XFOIL's polar accumulator) is deliberately not used. This XFOIL build
hits a Fortran runtime EOF bug after the first point gets written to a PACC
save file, which kills XFOIL mid-sweep. The polar dump file is a Fortran
binary format and not friendly to parse. So we just send ALFA commands one
at a time and parse the converged results directly from XFOIL's stdout.

The sweep is bracketed around zero: 0 upward to alpha_max, INIT, then 0
downward to alpha_min. This primes convergence and prevents a near-stall
BL state from polluting the negative-alpha sweep.

Requires xfoil in PATH. On Gentoo:
    sudo emerge sci-physics/xfoil

Examples:
    python scripts/xfoil_polar.py main_keel --re 3e6
    python scripts/xfoil_polar.py test_rudder --re 1e6 --alpha -10 12 0.5
"""
from __future__ import annotations

import argparse
import csv
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path


XFOIL_TIMEOUT_SECONDS = 600

# Regexes for parsing XFOIL stdout
RE_ALFA_CL = re.compile(r"a\s*=\s*(-?\d+\.\d+)\s+CL\s*=\s*(-?\d+\.\d+)")
RE_CM_CD = re.compile(
    r"Cm\s*=\s*(-?\d+\.\d+)\s+CD\s*=\s*(-?\d+\.\d+)\s*=>\s*"
    r"CDf\s*=\s*(-?\d+\.\d+)\s+CDp\s*=\s*(-?\d+\.\d+)"
)
RE_XTR_TOP = re.compile(r"Side\s+1\s+free\s+transition\s+at\s+x/c\s*=\s*(\d+\.\d+)")
RE_XTR_BOT = re.compile(r"Side\s+2\s+free\s+transition\s+at\s+x/c\s*=\s*(\d+\.\d+)")


def sanitize_dat(input_dat: Path, output_dat: Path) -> int:
    """Drop consecutive-duplicate and loop-closure-duplicate points so XFOIL
    doesn't create zero-length panels."""
    with input_dat.open() as f:
        lines = f.readlines()
    if not lines:
        raise ValueError(f"{input_dat} is empty")

    name = lines[0]
    points: list[tuple[float, float]] = []
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            x, y = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        if points:
            px, py = points[-1]
            if abs(x - px) < 1e-9 and abs(y - py) < 1e-9:
                continue
        points.append((x, y))

    if len(points) >= 2:
        fx, fy = points[0]
        lx, ly = points[-1]
        if abs(fx - lx) < 1e-9 and abs(fy - ly) < 1e-9:
            points = points[:-1]

    with output_dat.open("w") as f:
        f.write(name)
        for x, y in points:
            f.write(f"{x:.6f}  {y:.6f}\n")
    return len(points)


def alpha_schedule(alpha_min: float, alpha_max: float, alpha_step: float) -> list[float]:
    """Build the list of alphas to visit, bracketed around zero.
    Uses math.nan as an INIT marker between the upward and downward sweeps."""
    step = abs(alpha_step)
    schedule: list[float] = []

    if alpha_min < 0 < alpha_max:
        a = 0.0
        while a <= alpha_max + 1e-9:
            schedule.append(round(a, 6))
            a += step
        schedule.append(math.nan)
        a = -step
        while a >= alpha_min - 1e-9:
            schedule.append(round(a, 6))
            a -= step
    elif alpha_min >= 0:
        a = alpha_min
        while a <= alpha_max + 1e-9:
            schedule.append(round(a, 6))
            a += step
    else:
        a = alpha_max
        while a >= alpha_min - 1e-9:
            schedule.append(round(a, 6))
            a -= step
    return schedule


def build_xfoil_commands(
    clean_dat: Path,
    re: float,
    alphas: list[float],
    mach: float,
    max_iter: int,
) -> str:
    cmds = [
        "PLOP", "G", "",
        f"LOAD {clean_dat.resolve()}", "",
        "PANE",
        "OPER",
        f"VISC {re}",
        f"MACH {mach}",
        f"ITER {max_iter}",
    ]
    for a in alphas:
        if math.isnan(a):
            cmds.append("INIT")
            continue
        cmds.append(f"ALFA {a}")
    cmds += ["", "QUIT", ""]
    return "\n".join(cmds) + "\n"


def parse_stdout(stdout: str) -> list[dict]:
    """
    Parse converged results from XFOIL stdout. Each iteration of the BL
    solver prints transition locations followed by a CL line and a Cm/CD
    line. We track the most recent values; the LAST set recorded for each
    alpha (just before XFOIL moves on to the next ALFA) is the converged
    answer.
    """
    results: dict[float, dict] = {}
    pending_xtr_top = 1.0
    pending_xtr_bot = 1.0
    pending_alpha = None
    pending_cl = None

    for line in stdout.splitlines():
        m = RE_XTR_TOP.search(line)
        if m:
            pending_xtr_top = float(m.group(1))
            continue
        m = RE_XTR_BOT.search(line)
        if m:
            pending_xtr_bot = float(m.group(1))
            continue
        m = RE_ALFA_CL.search(line)
        if m:
            pending_alpha = float(m.group(1))
            pending_cl = float(m.group(2))
            continue
        m = RE_CM_CD.search(line)
        if m and pending_alpha is not None and pending_cl is not None:
            cm = float(m.group(1))
            cd = float(m.group(2))
            cdp = float(m.group(4))
            results[round(pending_alpha, 4)] = {
                "alpha": pending_alpha,
                "CL": pending_cl,
                "CD": cd,
                "CDp": cdp,
                "CM": cm,
                "Top_Xtr": pending_xtr_top,
                "Bot_Xtr": pending_xtr_bot,
            }

    rows = list(results.values())
    rows.sort(key=lambda r: r["alpha"])
    return rows


def run_xfoil(
    section_dat: Path,
    stdout_log: Path,
    re: float,
    alpha_min: float,
    alpha_max: float,
    alpha_step: float,
    *,
    mach: float = 0.0,
    max_iter: int = 200,
) -> str:
    if shutil.which("xfoil") is None:
        raise RuntimeError(
            "xfoil not found in PATH. On Gentoo: sudo emerge sci-physics/xfoil"
        )

    clean_dat = stdout_log.with_name("xfoil_input.dat")
    sanitize_dat(section_dat, clean_dat)

    alphas = alpha_schedule(alpha_min, alpha_max, alpha_step)
    commands = build_xfoil_commands(clean_dat, re, alphas, mach=mach, max_iter=max_iter)

    try:
        result = subprocess.run(
            ["xfoil"],
            input=commands,
            capture_output=True,
            text=True,
            timeout=XFOIL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"XFOIL timed out after {XFOIL_TIMEOUT_SECONDS}s — narrow the alpha range"
        )

    stdout_log.write_text(result.stdout)
    return result.stdout


def write_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        raise ValueError("no rows to write")
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Run XFOIL on a yacht-cfd project's section.dat.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("project", help="Project name under projects/")
    ap.add_argument("--re", type=float, default=3e6,
                    help="Reynolds number (default: 3e6, the NACA Report 824 reference)")
    ap.add_argument("--alpha", type=float, nargs=3, metavar=("MIN", "MAX", "STEP"),
                    default=[-5.0, 15.0, 0.5],
                    help="Alpha sweep min max step in degrees (default: -5 15 0.5)")
    ap.add_argument("--root", type=Path, default=Path("projects"),
                    help="Projects folder (default: ./projects)")
    args = ap.parse_args()

    project = args.root / args.project
    section_dat = project / "section.dat"
    if not section_dat.exists():
        print(f"No section.dat at {section_dat}", file=sys.stderr)
        sys.exit(1)

    stdout_log = project / "xfoil_stdout.log"
    csv_polar = project / "polar.csv"

    print(f"Running XFOIL on {section_dat} at Re={args.re:.2e}, "
          f"alpha {args.alpha[0]}° to {args.alpha[1]}° step {args.alpha[2]}°")
    try:
        stdout = run_xfoil(section_dat, stdout_log, args.re, *args.alpha)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        sys.exit(2)

    rows = parse_stdout(stdout)
    if not rows:
        print(f"No converged points found. Check {stdout_log} for XFOIL's output.",
              file=sys.stderr)
        sys.exit(3)

    write_csv(rows, csv_polar)
    print(f"Wrote {csv_polar}: {len(rows)} converged points "
          f"({rows[0]['alpha']:.2f}° to {rows[-1]['alpha']:.2f}°)")
    cl_max = max(rows, key=lambda r: r["CL"])
    cd_min = min(rows, key=lambda r: r["CD"])
    print(f"  CL_max  = {cl_max['CL']:.3f} at alpha = {cl_max['alpha']:.2f}°")
    print(f"  CD_min  = {cd_min['CD']:.5f} at alpha = {cd_min['alpha']:.2f}°")


if __name__ == "__main__":
    main()