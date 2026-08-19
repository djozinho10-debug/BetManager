import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
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
    # Remove apenas sufixos/palavras muito comuns de clubes; preserva termos que
    # podem diferenciar equipes (ex.: Union, City, United, Spartans).
    value = re.sub(r"\b(fc|cf|sc|ac|afc|club|futbol|football|futebol)\b", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def _strip_ocr_noise(value):
    """Limpa rótulos de mercado que às vezes ficam colados ao nome do time."""
    value = str(value or "").strip()
    # Prefixos comuns observados nos prints.
    patterns = [
        r"^partida\s*[-:|]?\s*",
        r"^(?:total\s+de\s+)?(?:gols?|chutes?|remates?|escanteios?|corners)\s*[-:|]?\s*",
        r"^(?:time\s+da\s+casa|time\s+visitante)\s*[-:|]?\s*",
        r"^(?:(?:mais|menos)\s+de|over|under)\s+\d+(?:[.,]\d+)?\s*",
        r"^\d+(?:[.,]\d+)?\s*",
    ]
    previous = None
    while value and value != previous:
        previous = value
        for pat in patterns:
            value = re.sub(pat, "", value, flags=re.I).strip(" -:|•")
    # Rodapés de bilhete colados ao visitante.
    value = re.split(
        r"\b(?:aposta|retornos?\s+potenciais?|valor|stake|odd|ganho|retorno|reutilizar\s+sele[cç][oõ]es)\b",
        value,
        maxsplit=1,
        flags=re.I,
    )[0]
    return " ".join(value.split()).strip()


def _token_score(a, b):
    """Score tolerante a nomes abreviados: Philadelphia ~ Philadelphia Union."""
    na, nb = _norm(_strip_ocr_noise(a)), _norm(_strip_ocr_noise(b))
    if not na or not nb:
        return 0.0

    ratio = SequenceMatcher(None, na, nb).ratio()
    ta, tb = na.split(), nb.split()
    sa, sb = set(ta), set(tb)
    common = sa & sb

    # Cobertura do texto OCR e do nome oficial.
    cov_a = len(common) / max(1, len(sa))
    cov_b = len(common) / max(1, len(sb))
    token = 0.72 * cov_a + 0.28 * cov_b

    # Prefixo/substring exatos são muito úteis quando o print omite FC/Union/etc.
    compact_a, compact_b = na.replace(" ", ""), nb.replace(" ", "")
    partial = 0.0
    if na in nb or nb in na:
        shorter = min(len(compact_a), len(compact_b))
        longer = max(len(compact_a), len(compact_b))
        partial = 0.82 + 0.18 * (shorter / max(1, longer))

    # Um token longo idêntico costuma ser um ótimo identificador do clube.
    distinctive = 0.0
    if common:
        longest = max(len(x) for x in common)
        if longest >= 8:
            distinctive = 0.90 if cov_a >= 0.5 else 0.82
        elif longest >= 5 and cov_a == 1.0:
            distinctive = 0.84

    return min(1.0, max(ratio, token, partial, distinctive))


def _sim(a, b):
    return _token_score(a, b)


def _split_event(event):
    event = str(event or "").strip()
    # Aceita x, X, ×, vs e versus.
    parts = re.split(r"\s+(?:x|×|vs\.?|versus)\s+", event, maxsplit=1, flags=re.I)
    if len(parts) != 2:
        return "", ""
    return _strip_ocr_noise(parts[0]), _strip_ocr_noise(parts[1])


def _fixture_scores(home_ocr, away_ocr, item):
    teams = item.get("teams", {})
    home = (teams.get("home") or {}).get("name", "")
    away = (teams.get("away") or {}).get("name", "")

    h_h, a_a = _sim(home_ocr, home), _sim(away_ocr, away)
    h_a, a_h = _sim(home_ocr, away), _sim(away_ocr, home)
    normal = (h_h + a_a) / 2
    swapped = (h_a + a_h) / 2
    if normal >= swapped:
        return normal, h_h, a_a, False
    return swapped, h_a, a_h, True

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

    # Já devolve o evento limpo para a ficha, mesmo antes da confirmação.
    data["event"] = f"{home_ocr} x {away_ocr}"

    try:
        base_date = datetime.strptime(str(data.get("bet_date")), "%Y-%m-%d").date()
    except Exception:
        base_date = datetime.utcnow().date()

    candidates = []
    # Primeiro o dia informado. Só amplia para +/-1 se não houver match forte.
    for offset in (0, -1, 1):
        day = (base_date + timedelta(days=offset)).isoformat()
        try:
            fixtures = _request_fixtures(day)
        except Exception as exc:
            data["_api_status"] = f"Falha API-Football: {type(exc).__name__}"
            return data

        for item in fixtures:
            score, side1, side2, swapped = _fixture_scores(home_ocr, away_ocr, item)
            candidates.append((score, min(side1, side2), side1, side2, item, day, swapped))

        day_best = max((x[0] for x in candidates if x[5] == day), default=0.0)
        if offset == 0 and day_best >= 0.90:
            break
        if offset == -1 and max((x[0] for x in candidates), default=0.0) >= 0.90:
            break

    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    if not candidates:
        data["_api_status"] = "Partida não encontrada na API"
        return data

    best_score, best_min_side, side1, side2, best, best_day, swapped = candidates[0]
    second_score = candidates[1][0] if len(candidates) > 1 else 0.0
    margin = best_score - second_score

    # Match inteligente:
    # - score alto confirma direto;
    # - score médio confirma quando AMBOS os times casam bem e o melhor
    #   candidato se destaca do segundo colocado.
    strong = best_score >= 0.84 and best_min_side >= 0.68
    balanced = best_score >= min_confidence and best_min_side >= 0.72 and margin >= 0.025
    very_clear_sides = side1 >= 0.82 and side2 >= 0.82 and best_score >= 0.78
    confirmed = strong or balanced or very_clear_sides

    data["_api_confidence"] = round(best_score, 3)
    data["_api_side_scores"] = (round(side1, 3), round(side2, 3))

    if not confirmed:
        data["_api_status"] = (
            f"Partida não confirmada pela API ({best_score:.0%})"
            f" • times {side1:.0%}/{side2:.0%}"
        )
        return data

    teams = best.get("teams", {})
    league = best.get("league", {})
    fixture = best.get("fixture", {})
    home = (teams.get("home") or {}).get("name", "")
    away = (teams.get("away") or {}).get("name", "")
    if home and away:
        data["event"] = f"{home} x {away}"

    data["competition"] = str(league.get("name") or data.get("competition", "")).strip()
    data["country"] = str(league.get("country") or data.get("country", "")).strip()
    data["_api_country"] = data["country"]
    data["_api_fixture_id"] = fixture.get("id")
    data["_api_confidence"] = round(best_score, 3)
    data["_api_status"] = (
        f"API confirmou a partida ({best_score:.0%})"
        f" • times {side1:.0%}/{side2:.0%}"
    )
    data["_api_day"] = best_day

    # A API devolve kickoff com referência temporal. Normalizamos sempre para
    # America/Sao_Paulo e reutilizamos a mesma fixture (sem chamada extra).
    try:
        br_tz = ZoneInfo("America/Sao_Paulo")
        kickoff = None
        ts = fixture.get("timestamp")
        if ts is not None:
            kickoff = datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(br_tz)
        elif fixture.get("date"):
            kickoff = datetime.fromisoformat(str(fixture.get("date")).replace("Z", "+00:00"))
            if kickoff.tzinfo is None:
                kickoff = kickoff.replace(tzinfo=timezone.utc)
            kickoff = kickoff.astimezone(br_tz)
        if kickoff:
            data["bet_date"] = kickoff.date().isoformat()
            data["_api_game_time_br"] = kickoff.strftime("%H:%M")
            data["_api_game_datetime_br"] = kickoff.replace(tzinfo=None).isoformat(timespec="minutes")
            data["_api_status"] += f" • início {kickoff.strftime('%d/%m às %H:%M')} (Brasília)"
    except Exception:
        pass
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
