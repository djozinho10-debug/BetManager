import pandas as pd


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    # Histórico antigo: separa automaticamente Gols +/- conforme a seleção.
    if 'market' in out.columns and 'selection' in out.columns:
        generic = out['market'].fillna('').astype(str).eq('Gols +/-')
        sel = out['selection'].fillna('').astype(str).str.lower()
        out.loc[generic & sel.str.startswith('over '), 'market'] = 'Over Gols'
        out.loc[generic & sel.str.startswith('under '), 'market'] = 'Under Gols'
    out['bet_date'] = pd.to_datetime(out['bet_date'], errors='coerce')
    for c in ['odds','units','profit_units','source_stake_money']:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors='coerce').fillna(0)
    out['month'] = out['bet_date'].dt.to_period('M').astype(str)
    out['odd_band'] = pd.cut(out['odds'], [0,1.49,1.69,1.89,2.09,2.49,999], labels=['<1.50','1.50–1.69','1.70–1.89','1.90–2.09','2.10–2.49','2.50+'])
    return out


def max_drawdown_units(df: pd.DataFrame) -> float:
    d = prepare(df)
    settled = d[d['result'].isin(['WIN','HALF WIN','VOID','HALF LOSS','LOSS'])].sort_values(['bet_date','id'])
    if settled.empty:
        return 0.0
    curve = settled['profit_units'].cumsum()
    peak = curve.cummax().clip(lower=0)
    dd = curve - peak
    return float(dd.min())


def kpis(df: pd.DataFrame):
    d = prepare(df)
    if d.empty:
        return {'bets':0,'units':0,'profit_units':0,'roi':0,'yield':0,'hit_rate':0,'avg_odds':0,'drawdown':0}
    settled = d[d['result'].isin(['WIN','HALF WIN','VOID','HALF LOSS','LOSS'])]
    units = settled['units'].sum()
    profit = settled['profit_units'].sum()
    roi = (profit / units * 100) if units else 0
    return {
        'bets': len(d), 'units': float(units), 'profit_units': float(profit), 'roi': float(roi), 'yield': float(roi),
        'hit_rate': float((((settled['result'].eq('WIN')).astype(float) + 0.5*(settled['result'].eq('HALF WIN')).astype(float)).mean()*100) if len(settled) else 0),
        'avg_odds': float(settled['odds'].mean() if len(settled) else 0),
        'drawdown': max_drawdown_units(d),
    }


def group_report(df: pd.DataFrame, field: str) -> pd.DataFrame:
    d = prepare(df)
    if d.empty or field not in d.columns:
        return pd.DataFrame()
    settled = d[d['result'].isin(['WIN','HALF WIN','VOID','HALF LOSS','LOSS'])].copy()
    if settled.empty:
        return pd.DataFrame()
    g = settled.groupby(field, dropna=False).agg(
        apostas=('id','count'), unidades=('units','sum'), lucro_u=('profit_units','sum'),
        odd_media=('odds','mean'), wins_eq=('result', lambda x: (x == 'WIN').sum() + 0.5*(x == 'HALF WIN').sum()),
    ).reset_index()
    g['roi_%'] = (g['lucro_u'] / g['unidades'] * 100).where(g['unidades'] != 0, 0).round(2)
    g['acerto_%'] = (g['wins_eq'] / g['apostas'] * 100).round(2)
    g['lucro_u'] = g['lucro_u'].round(2)
    g['unidades'] = g['unidades'].round(2)
    g['odd_media'] = g['odd_media'].round(2)
    return g.sort_values('lucro_u', ascending=False)
