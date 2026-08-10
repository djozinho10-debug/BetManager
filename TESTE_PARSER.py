from src.parser import parse_text
sample="""Menos de 2,5 3,0 1.700
Gols + -
Libertad FC
Universidad Católica del Ecuador
"""
r=parse_text(sample)
assert r["event"]=="Libertad FC x Universidad Católica del Ecuador", r
assert r["market"]=="Gols +/-", r
assert r["selection"].lower().startswith("menos de 2,5"), r
assert abs(r["odds"]-1.7)<1e-9, r
print(r)
