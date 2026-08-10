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
