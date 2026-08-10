from src.parser import parse_text
sample='''Banfield - Mais de 15.5 3.40
Time da Casa - Chutes
% Banfield
Belgrano
'''
r=parse_text(sample)
print(r)
assert r['event']=='Banfield x Belgrano', r
assert r['market']=='Time da Casa - Chutes', r
assert r['selection']=='Banfield - Mais de 15.5', r
assert abs(r['odds']-3.4)<1e-9, r
