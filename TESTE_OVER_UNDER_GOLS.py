import pandas as pd
from src.reports import prepare
from src.parser import parse_text

df = pd.DataFrame([
    {"id":1,"market":"Gols +/-","selection":"Over 2.5","bet_date":"2026-08-11","odds":1.8,"units":1,"profit_units":0,"source_stake_money":0,"result":"PENDENTE"},
    {"id":2,"market":"Gols +/-","selection":"Under 2.75","bet_date":"2026-08-11","odds":1.8,"units":1,"profit_units":0,"source_stake_money":0,"result":"PENDENTE"},
])
d = prepare(df)
print(d[["market","selection"]])
assert d.loc[0,"market"] == "Over Gols"
assert d.loc[1,"market"] == "Under Gols"

a = parse_text("""Mais de 2.5 1.80
Gols +/-
Time A
Time B""")
b = parse_text("""Menos de 2.5 1.80
Gols +/-
Time A
Time B""")
print(a["market"], a["selection"])
print(b["market"], b["selection"])
assert a["market"] == "Over Gols"
assert b["market"] == "Under Gols"
