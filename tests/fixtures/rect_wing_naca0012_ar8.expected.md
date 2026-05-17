For a rectangular wing with NACA 0012 sections at AR=8, the theory is Prandtl's lifting line theory, which gives the 3D lift-curve slope analytically:
a_3D = a_0 / (1 + a_0/(π·AR))
where a_0 is the 2D lift-curve slope of the section. AVL is inviscid potential flow, so use the theoretical a_0 = 2π per radian (not the viscous ~5.7 from real NACA 0012 wind tunnel data — that includes viscous boundary layer losses that AVL doesn't model).
For AR=8:
a_3D = 2π / (1 + 2π/(π·8))
     = 2π / 1.25
     = 5.03 per radian
     = 0.0878 per degree
So your expected values:

α = 0°: CL = 0 exactly (NACA 0012 is symmetric, no lift at zero incidence)
α = 5°: CL = 0.0878 × 5 = 0.439
α = −5°: CL = −0.439

AVL should reproduce these within ~1–2%. The small discrepancy is because lifting line theory assumes elliptic spanwise loading; a rectangular planform isn't quite elliptic, so there's a few-percent correction. If AVL gives you CL = 0.43 at α=5°, your wrapper works. If it gives you CL = 0.6 or 0.2, something's wrong — wrong panel count, wrong reference area, wrong parsing.
For induced drag at the same operating point:
CDi = CL² / (π·AR·e)
with e ≈ 0.94 for rectangular AR=8: at α=5°, CDi ≈ 0.439²/(π·8·0.94) ≈ 0.00817.
The source for these formulas is Prandtl's lifting line theory — covered in Anderson's Fundamentals of Aerodynamics Chapter 5, Houghton & Carpenter's Aerodynamics for Engineering Students Chapter 5, or any standard undergraduate aero textbook. You almost certainly already have this in your first-year course materials, or you can re-derive it from the formula above in 30 seconds.
