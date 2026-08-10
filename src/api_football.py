import os
import re
import unicodedata
from datetime import datetime, timedelta
from difflib import SequenceMatcher
import requests

API_BASE = "https://v3.football.api-sports.io"

def _secret_key():
    try:
        import streamlit as st
        key = st.secrets.get("API_FOOTBALL_KEY")
        if key:
            return str(key).strip()
    except Exception:
        pass
    return os.getenv("API_FOOTBALL_KEY", "").strip()

def api_enabled():
    return bool(_secret_key())

def _norm(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.lower()
    value = re.sub(r"\b(fc|cf|sc|ac|afc|club|de|do|da|the)\b", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())

def _sim(a, b):
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    ratio = SequenceMatcher(None, a, b).ratio()
    containment = min(len(a), len(b)) / max(len(a), len(b)) if a in b or b in a else 0
    return max(ratio, containment)

def _split_event(event):
    parts = re.split(r"\s+x\s+", str(event or ""), flags=re.I)
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else ("", "")

def _request_fixtures(day):
    key = _secret_key()
    if not key:
        return []
    r = requests.get(
        f"{API_BASE}/fixtures",
        headers={"x-apisports-key": key},
        params={"date": day},
        timeout=12,
    )
    r.raise_for_status()
    payload = r.json()
    return payload.get("response", []) if isinstance(payload, dict) else []

def enrich_from_api(parsed, min_confidence=0.72):
    data = dict(parsed or {})
    if not api_enabled():
        data["_api_status"] = "API-Football não configurada"
        return data

    home_ocr, away_ocr = _split_event(data.get("event"))
    if not home_ocr or not away_ocr:
        data["_api_status"] = "Evento insuficiente para consultar API"
        return data

    try:
        base_date = datetime.strptime(str(data.get("bet_date")), "%Y-%m-%d").date()
    except Exception:
        base_date = datetime.utcnow().date()

    best = None
    best_score = 0.0
    best_day = None

    for offset in (0, -1, 1):
        day = (base_date + timedelta(days=offset)).isoformat()
        try:
            fixtures = _request_fixtures(day)
        except Exception as exc:
            data["_api_status"] = f"Falha API-Football: {type(exc).__name__}"
            return data

        for item in fixtures:
            teams = item.get("teams", {})
            home = (teams.get("home") or {}).get("name", "")
            away = (teams.get("away") or {}).get("name", "")
            normal = (_sim(home_ocr, home) + _sim(away_ocr, away)) / 2
            swapped = (_sim(home_ocr, away) + _sim(away_ocr, home)) / 2
            score = max(normal, swapped)
            if score > best_score:
                best_score, best, best_day = score, item, day
        if best_score >= 0.88:
            break

    if not best or best_score < min_confidence:
        data["_api_status"] = f"Partida não confirmada pela API ({best_score:.0%})"
        return data

    teams = best.get("teams", {})
    league = best.get("league", {})
    fixture = best.get("fixture", {})
    home = (teams.get("home") or {}).get("name", "")
    away = (teams.get("away") or {}).get("name", "")
    if home and away:
        data["event"] = f"{home} x {away}"

    data["competition"] = str(league.get("name") or data.get("competition", "")).strip()
    data["_api_country"] = str(league.get("country") or "").strip()
    data["_api_fixture_id"] = fixture.get("id")
    data["_api_confidence"] = round(best_score, 3)
    data["_api_status"] = f"API confirmou a partida ({best_score:.0%})"
    data["_api_day"] = best_day
    return data


def _request_fixture_by_id(fixture_id):
    key=_secret_key()
    if not key or not fixture_id:
        return None
    r=requests.get(
        f"{API_BASE}/fixtures",
        headers={"x-apisports-key":key},
        params={"id":fixture_id},
        timeout=12,
    )
    r.raise_for_status()
    payload=r.json()
    items=payload.get("response",[]) if isinstance(payload,dict) else []
    return items[0] if items else None

def _request_statistics(fixture_id):
    key=_secret_key()
    if not key or not fixture_id:
        return []
    r=requests.get(
        f"{API_BASE}/fixtures/statistics",
        headers={"x-apisports-key":key},
        params={"fixture":fixture_id},
        timeout=12,
    )
    r.raise_for_status()
    payload=r.json()
    return payload.get("response",[]) if isinstance(payload,dict) else []

def _parse_line(selection):
    m=re.search(r'\b(over|under)\s+(\d+(?:[.,]\d+)?)',str(selection or ''),re.I)
    if not m:
        return None,None
    return m.group(1).lower(), float(m.group(2).replace(',','.'))

def _asian_total_result(side, line, value):
    """Retorna WIN/HALF WIN/VOID/HALF LOSS/LOSS para linhas asiáticas .0/.25/.5/.75."""
    def single(l):
        if side=='over':
            if value>l:return 'WIN'
            if value==l:return 'VOID'
            return 'LOSS'
        else:
            if value<l:return 'WIN'
            if value==l:return 'VOID'
            return 'LOSS'

    frac=round(line-int(line),2)
    if frac in (0.25,0.75):
        low=(int(line) if frac==0.25 else int(line)+0.5)
        high=(int(line)+0.5 if frac==0.25 else int(line)+1.0)
        a,b=single(low),single(high)
        pair={a,b}
        if a==b:return a
        if pair=={'WIN','VOID'}:return 'HALF WIN'
        if pair=={'LOSS','VOID'}:return 'HALF LOSS'
        return None
    return single(line)

def _stat_value(stats, team_name, stat_type):
    for block in stats:
        team=((block.get("team") or {}).get("name") or "")
        if _sim(team,team_name)>=0.75:
            for item in block.get("statistics",[]):
                if str(item.get("type","")).lower()==stat_type.lower():
                    val=item.get("value")
                    try:return float(val or 0)
                    except:return None
    return None

def suggest_settlement(bet):
    """Sugere resultado sem gravar. Usa placar e, quando necessário, estatísticas da partida."""
    if not api_enabled():
        return {"status":"API-Football não configurada","suggestion":None}

    # Reencontra a partida pela data/nome se não houver fixture_id salvo.
    parsed={"event":bet.get("event",""),"competition":bet.get("competition",""),"bet_date":bet.get("bet_date","")}
    enriched=enrich_from_api(parsed)
    fixture_id=enriched.get("_api_fixture_id")
    if not fixture_id:
        return {"status":enriched.get("_api_status","Partida não encontrada"),"suggestion":None}

    try:
        fixture=_request_fixture_by_id(fixture_id)
    except Exception as exc:
        return {"status":f"Falha ao consultar partida: {type(exc).__name__}","suggestion":None}
    if not fixture:
        return {"status":"Partida não encontrada","suggestion":None}

    short=str(((fixture.get("fixture") or {}).get("status") or {}).get("short") or "")
    if short not in {"FT","AET","PEN"}:
        return {"status":f"Partida ainda não finalizada ({short or 'status desconhecido'})","suggestion":None}

    home=((fixture.get("teams") or {}).get("home") or {}).get("name","")
    away=((fixture.get("teams") or {}).get("away") or {}).get("name","")
    goals=fixture.get("goals") or {}
    hg=float(goals.get("home") or 0)
    ag=float(goals.get("away") or 0)

    market=str(bet.get("market") or "")
    selection=str(bet.get("selection") or "")
    side,line=_parse_line(selection)
    if side is None:
        return {"status":"Seleção não padronizada como Over/Under","suggestion":None}

    value=None
    detail=""

    ml=market.lower()
    if "gols" in ml:
        value=hg+ag
        detail=f"{int(hg)}-{int(ag)} • total {value:g} gols"

    elif "chutes no alvo" in ml or "chutes" in ml:
        try:
            stats=_request_statistics(fixture_id)
        except Exception as exc:
            return {"status":f"Falha ao consultar estatísticas: {type(exc).__name__}","suggestion":None}

        stat_type="Shots on Goal" if "chutes no alvo" in ml else "Total Shots"
        if "time da casa" in ml:
            team=home
        elif "time visitante" in ml:
            team=away
        else:
            return {"status":"Mercado de chutes sem indicar time da casa/visitante","suggestion":None}
        value=_stat_value(stats,team,stat_type)
        if value is None:
            return {"status":f"Estatística {stat_type} não disponível","suggestion":None}
        detail=f"{team}: {value:g} {stat_type}"

    elif "escanteios" in ml or "corners" in ml:
        try:
            stats=_request_statistics(fixture_id)
        except Exception as exc:
            return {"status":f"Falha ao consultar estatísticas: {type(exc).__name__}","suggestion":None}
        hv=_stat_value(stats,home,"Corner Kicks") or 0
        av=_stat_value(stats,away,"Corner Kicks") or 0
        value=hv+av
        detail=f"{home} {hv:g} + {away} {av:g} = {value:g} escanteios"

    else:
        return {"status":"Mercado ainda sem liquidação automática","suggestion":None}

    suggestion=_asian_total_result(side,line,value)
    return {
        "status":"Sugestão calculada",
        "suggestion":suggestion,
        "fixture_id":fixture_id,
        "detail":detail,
        "line":line,
        "side":side,
        "value":value,
    }
