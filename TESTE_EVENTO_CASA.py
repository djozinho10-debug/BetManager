from src.parser import _clean_event_name, parse_text

assert _clean_event_name("44 Banfield x É Belgrano")=="Banfield x Belgrano"
assert _clean_event_name("12 Libertad FC x Universidad Católica del Ecuador")=="Libertad FC x Universidad Católica del Ecuador"

sample="""Banfield - Mais de 15.5 3.40
Time da Casa - Chutes
44 Banfield
É Belgrano
"""
r=parse_text(sample)
print(r)
assert r["event"]=="Banfield x Belgrano", r
assert r["selection"]=="Over 15.5", r
assert r["market"]=="Time da Casa - Chutes", r
