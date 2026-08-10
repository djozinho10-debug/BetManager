from src.parser import parse_text, _standardize_selection
assert _standardize_selection("Banfield - Mais de 15.5")=="Over 15.5"
assert _standardize_selection("Menos de 2.5,3.0")=="Under 2.75"
assert _standardize_selection("Mais de 2.0,2.5")=="Over 2.25"
assert _standardize_selection("Under 3.0,3.5")=="Under 3.25"
assert _standardize_selection("Over 9.5")=="Over 9.5"

a=parse_text("""Banfield - Mais de 15.5 3.40
Time da Casa - Chutes
% Banfield
Belgrano""")
print(a)
assert a["selection"]=="Over 15.5",a
assert a["market"]=="Time da Casa - Chutes",a
assert a["event"]=="Banfield x Belgrano",a
assert abs(a["odds"]-3.4)<1e-9,a

b=parse_text("""Menos de 2.5,3.0 1.85
Gols +/-
Time A
Time B""")
print(b)
assert b["selection"]=="Under 2.75",b
