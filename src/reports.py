import pandas as pd


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    # Normalização definitiva do mercado de gols.
    # Reclassifica registros antigos salvos como Gols +/- usando qualquer indicação
    # de Over/Under (inclusive Mais de/Menos de) encontrada na seleção.
    if 'market' in out.columns and 'selection' in out.columns:
        _m = out['market'].fillna('').astype(str).str.strip().str.lower()
        _sel = out['selection'].fillna('').astype(str).str.strip().str.lower()
        _generic = _m.str.contains(r'gols\s*\+?\s*/?\s*-', regex=True, na=False)

        _over = _sel.str.contains(r'\b(over|mais\s+de)\b', regex=True, na=False)
        _under = _sel.str.contains(r'\b(under|menos\s+de)\b', regex=True, na=False)

        out.loc[_generic & _over, 'market'] = 'Over Gols'
        out.loc[_generic & _under, 'market'] = 'Under Gols'

        # Não deixa o rótulo antigo aparecer nos relatórios.
        # Casos legados sem direção identificável ficam explicitamente marcados.
        _m2 = out['market'].fillna('').astype(str).str.strip().str.lower()
        _still_generic = _m2.str.contains(r'gols\s*\+?\s*/?\s*-', regex=True, na=False)
        out.loc[_still_generic, 'market'] = 'Gols — revisar Over/Under'
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
        'pending': int((d['result'] == 'PENDENTE').sum()),
        'best_streak': streak_summary(d)['best_green'],
        'worst_streak': streak_summary(d)['best_red'],
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


def combo_report(df: pd.DataFrame, fields=None, min_bets: int = 3) -> pd.DataFrame:
    """
    Cruza dimensões do histórico e retorna combinações com volume mínimo.
    Ex.: market + competition + odd_band.
    """
    fields = fields or ['market','competition','odd_band']
    d = prepare(df)
    if d.empty:
        return pd.DataFrame()

    settled = d[d['result'].isin(['WIN','HALF WIN','VOID','HALF LOSS','LOSS'])].copy()
    valid = [f for f in fields if f in settled.columns]
    if settled.empty or not valid:
        return pd.DataFrame()

    g = settled.groupby(valid, dropna=False).agg(
        apostas=('id','count'),
        unidades=('units','sum'),
        lucro_u=('profit_units','sum'),
        odd_media=('odds','mean'),
        wins_eq=('result', lambda x: (x == 'WIN').sum() + 0.5*(x == 'HALF WIN').sum()),
    ).reset_index()

    g = g[g['apostas'] >= int(min_bets)].copy()
    if g.empty:
        return g

    g['roi_%'] = (g['lucro_u'] / g['unidades'] * 100).where(g['unidades'] != 0, 0)
    g['acerto_%'] = (g['wins_eq'] / g['apostas'] * 100).where(g['apostas'] != 0, 0)

    for c in ['unidades','lucro_u','odd_media','roi_%','acerto_%']:
        g[c] = pd.to_numeric(g[c], errors='coerce').fillna(0).round(2)

    # Score simples: recompensa lucro/ROI, mas pondera por amostra.
    g['score'] = (
        g['lucro_u'] * 2
        + g['roi_%'] * 0.08
        + g['apostas'].clip(upper=20) * 0.12
    ).round(2)
    return g.sort_values(['score','lucro_u','roi_%'], ascending=False)


def performance_alerts(df: pd.DataFrame, min_bets: int = 3) -> dict:
    d = prepare(df)
    result = {
        'best_combo': None,
        'worst_combo': None,
        'best_market': None,
        'worst_market': None,
        'best_competition': None,
        'worst_competition': None,
        'best_odd_band': None,
        'worst_odd_band': None,
    }
    if d.empty:
        return result

    combos = combo_report(d, ['market','competition','odd_band'], min_bets=min_bets)
    if not combos.empty:
        result['best_combo'] = combos.iloc[0].to_dict()
        result['worst_combo'] = combos.sort_values(['lucro_u','roi_%']).iloc[0].to_dict()

    for field, bk, wk in [
        ('market','best_market','worst_market'),
        ('competition','best_competition','worst_competition'),
        ('odd_band','best_odd_band','worst_odd_band'),
    ]:
        rep = group_report(d, field)
        rep = rep[rep['apostas'] >= min_bets] if not rep.empty else rep
        if not rep.empty:
            result[bk] = rep.iloc[0].to_dict()
            result[wk] = rep.sort_values(['lucro_u','roi_%']).iloc[0].to_dict()
    return result


def streak_summary(df: pd.DataFrame) -> dict:
    """Resumo de sequências considerando resultados liquidados em ordem cronológica."""
    d = prepare(df)
    base = {'current_type':'—','current':0,'best_green':0,'best_red':0,'last10_profit':0.0,'last10_record':'—'}
    if d.empty:
        return base
    settled = d[d['result'].isin(['WIN','HALF WIN','VOID','HALF LOSS','LOSS'])].copy()
    if settled.empty:
        return base
    settled = settled.sort_values(['bet_date','id'])
    # VOID quebra a sequência; HALF WIN/LOSS entram no respectivo lado.
    seq=[]
    for r in settled['result'].astype(str):
        if r in ('WIN','HALF WIN'): seq.append('GREEN')
        elif r in ('LOSS','HALF LOSS'): seq.append('RED')
        else: seq.append('VOID')
    best_g=best_r=cur=0; cur_type=None
    run_type=None; run=0
    for x in seq:
        if x == 'VOID':
            run_type=None; run=0
            continue
        if x == run_type: run += 1
        else: run_type=x; run=1
        if x == 'GREEN': best_g=max(best_g,run)
        else: best_r=max(best_r,run)
    for x in reversed(seq):
        if x == 'VOID': break
        if cur_type is None: cur_type=x; cur=1
        elif x == cur_type: cur += 1
        else: break
    last=settled.tail(10)
    g=sum(r in ('WIN','HALF WIN') for r in last['result'])
    r=sum(r in ('LOSS','HALF LOSS') for r in last['result'])
    v=sum(r == 'VOID' for r in last['result'])
    return {
        'current_type': cur_type or '—', 'current':cur,
        'best_green':best_g, 'best_red':best_r,
        'last10_profit':float(last['profit_units'].sum()),
        'last10_record':f'{g}G • {r}R • {v}V'
    }
