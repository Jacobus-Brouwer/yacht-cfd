# yacht-cfd

A personal project working toward an open-source replacement for Maxsurf,
focused on yacht and performance-craft design.

The long-term goal is a complete design loop: parametric geometry →
CFD (OpenFOAM) → VPP → optimisation → repeat, producing theoretically
optimal foils, keels, rudders, and bulbs for a given set of design
conditions.

## Status

Currently a NACA 4-digit section generator with both 2D coordinate (.dat)
and 3D STL output, plus a matplotlib-based visual verifier.

Near-term roadmap: extend geometry coverage to keel sections, rudder
sections (with balance ratio), and bulbs; wire to XFOIL for cheap polar
validation; scaffold the OpenFOAM and VPP pipelines.

## Example output

![NACA 2412 section](docs/2412.png)
![Tapered, twisted keel](docs/keel.png)