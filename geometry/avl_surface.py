"""
avl_surface.py — generate an AVL geometry file (.avl) from a parameters dict.

The parameters dict follows the same schema as parameters.json used throughout
yacht-cfd (naca, chord, tip_chord, span, twist).  The output is a pure string
in AVL .avl format ready to write to disk.

Surface conventions
-------------------
  - Trapezoidal planform: root section at y=0, tip at y=span.
  - YDUPLICATE mirrors the surface about y=0, giving bilateral symmetry
    (appropriate for a fin/keel modelled as a lifting surface).
    iYsym in the header is kept at 0; the surface-level YDUPLICATE handles
    symmetry, as AVL forbids having both set simultaneously.
  - Sections use NACA 4-digit profiles at both root and tip.
  - Twist is applied linearly: root ainc=0, tip ainc=twist (deg, nose-up +ve).

Reference quantities (used for non-dimensionalising AVL outputs)
----------------------------------------------------------------
  Sref  = trapezoidal planform area of the *semi-span* surface
          = (c_root + c_tip) / 2 * span
  Cref  = mean aerodynamic chord
  Bref  = full span = 2 * span   (includes YDUPLICATE mirror)
  Xref  = Yref = Zref = 0.0     (moment reference at root leading edge)

Examples
--------
    from geometry.avl_surface import geometry_to_avl
    avl_text = geometry_to_avl({"naca": "0012", "chord": 1.0, "span": 1.5})
    Path("keel.avl").write_text(avl_text)
"""
from __future__ import annotations


def _mean_aero_chord(c_root: float, c_tip: float) -> float:
    """Mean aerodynamic chord for a linearly tapered (trapezoidal) wing."""
    if abs(c_root - c_tip) < 1e-12:
        return c_root
    taper = c_tip / c_root
    return (2.0 / 3.0) * c_root * (1.0 + taper + taper ** 2) / (1.0 + taper)


def geometry_to_avl(params: dict, name: str | None = None) -> str:
    """
    Build an AVL geometry string from a parameters dict.

    Parameters
    ----------
    params : dict
        Keys used:
            naca       (str)   NACA 4-digit designation, e.g. "0012"
            chord      (float) root chord [m]
            tip_chord  (float) tip chord [m]; defaults to root chord if absent
            span       (float) semi-span [m]; defaults to 1.0
            twist      (float) tip geometric twist [deg]; defaults to 0.0
    name : str, optional
        Configuration and surface name embedded in the file.
        Defaults to "naca<designation>" derived from params.

    Returns
    -------
    str
        Complete AVL geometry file content ready to write to disk.
    """
    naca = str(params["naca"]).strip()
    c_root = float(params["chord"])
    c_tip = float(params.get("tip_chord", c_root))
    span = float(params.get("span", 1.0))
    twist = float(params.get("twist", 0.0))

    if name is None:
        name = f"naca{naca}"

    s_ref = (c_root + c_tip) / 2.0 * span
    c_ref = _mean_aero_chord(c_root, c_tip)
    b_ref = 2.0 * span  # full span thanks to YDUPLICATE

    # AVL format rules that bit us during development:
    #   - NACA keyword must be on its own line; the 4-digit code on the next.
    #   - No blank line between SECTION blocks (causes a read error).
    #   - Blank lines between SURFACE-level directives (YDUPLICATE etc.) are fine.
    lines = [
        name,
        "0.0",                                                  # Mach
        "0   0   0.0",  # iYsym=0: YDUPLICATE handles surface symmetry
        f"{s_ref:.6f}  {c_ref:.6f}  {b_ref:.6f}",              # Sref  Cref  Bref
        "0.0  0.0  0.0",                                        # Xref  Yref  Zref
        "",
        "SURFACE",
        name,
        "12  1.0  20  -1.5",  # Nchord Cspace Nspan Sspace (-1.5 = cosine spanwise)
        "",
        "YDUPLICATE",
        "0.0",
        "",
        # Root section — no blank before next SECTION
        "SECTION",
        f"0.0  0.0  0.0  {c_root:.6f}  0.0",
        "NACA",
        naca,
        # Tip section — directly after root, no intervening blank
        "SECTION",
        f"0.0  {span:.6f}  0.0  {c_tip:.6f}  {twist:.6f}",
        "NACA",
        naca,
    ]
    return "\n".join(lines) + "\n"
