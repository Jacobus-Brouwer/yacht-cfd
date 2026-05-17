Context. This wraps AVL the same way scripts/xfoil_polar.py wraps XFOIL. Read that first — it's the pattern. Project conventions in CLAUDE.md.
Goal. Two new files:

yacht_cfd/geometry/avl_surface.py — generates an AVL geometry file (.avl format) from parameters.json. Trapezoidal planform, NACA section at root and tip, linear chord/twist interpolation. Pure function: params → string.
scripts/avl_loading.py — wraps the AVL binary. Interface: run(geometry_file, alphas: list[float], Re: float, V: float) → DataFrame in the cache schema (see docs/dev/cache-schema.md).

AVL command sequence (interactive subprocess, same pattern as XFOIL):
LOAD <case.avl>
OPER
M           (modify operating parameters)
V <V>       (set velocity)
...
A A <alpha> (set alpha)
X           (execute analysis)
FT          (print total forces — parse from stdout)
FS          (print strip forces — parse from stdout)
[repeat A A / X / FT / FS for each alpha in batch]
QUIT
Parse FT block for integrated CL, CD, Cm. Parse FS block for per-station strip data: y, chord, area, cl, cd, cm, ai (induced alpha). One AVL invocation per geometry, batched over the alpha list.
Output schema. Long-form rows matching the results.parquet schema. One row per scalar output. Integrated quantities get station_y=NaN. Strip quantities get the station's y position. Solver field is "avl", solver_version is read from AVL's startup banner.
Error handling. AVL exits cleanly on QUIT. If it crashes mid-sweep, return whatever was successfully parsed and log a warning with the failing alpha. Don't raise — failed runs should be visible in the cache as missing rows, not as crashes that kill the optimiser later.
Test. tests/test_avl_wrapper.py against tests/fixtures/naca0012_rectangular_wing.avl (build this fixture by hand — a simple rectangular wing with known reference solution). Sweep alpha = [-5, 0, 5]. Assert integrated CL within 1% of reference. Assert strip data has the right number of stations and correct y range.
Don't. Don't write a save file then parse it (the XFOIL gfortran bug doesn't apply to AVL but the stdout-parsing pattern is cleaner anyway). Don't add a TUI or plotting. Don't touch the cache schema — that's separate work.
