import pandas as pd
from src.reports import prepare, group_report
base = dict(bet_date='2026-08-11', odds=1.8, units=1, profit_units=.8, source_stake_money=0, result='WIN')
df=pd.DataFrame([
 dict(base,id=1,market='Gols +/-',selection='Over 2.5'),
 dict(base,id=2,market='Gols +/-',selection='Under 2.75'),
 dict(base,id=3,market='Gols +/-',selection='Mais de 3.0'),
 dict(base,id=4,market='Gols +/-',selection='Menos de 2.5'),
])
p=prepare(df)
assert set(p.market)=={'Over Gols','Under Gols'}, p[['market','selection']]
g=group_report(df,'market')
assert 'Gols +/-' not in set(g.market), g
print(g[['market','apostas']].to_string(index=False))
