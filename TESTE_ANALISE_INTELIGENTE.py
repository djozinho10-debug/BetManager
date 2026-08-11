import pandas as pd
from src.reports import combo_report, performance_alerts

rows=[]
for i in range(1,7):
    rows.append(dict(
        id=i,user_name='A',bet_date='2026-08-10',bookmaker='Betano',
        competition='Liga A',event='A x B',market='Over Gols',selection='Over 2.5',
        bet_type='Simples',timing='Pré-jogo',odds=1.90,units=1,
        source_stake_money=0,result='WIN' if i<=4 else 'LOSS',
        profit_units=.9 if i<=4 else -1,notes='',source_text=''
    ))
df=pd.DataFrame(rows)
c=combo_report(df,['market','competition','odd_band'],min_bets=3)
assert not c.empty
a=performance_alerts(df,min_bets=3)
assert a['best_market'] is not None
print(c.head().to_string(index=False))
