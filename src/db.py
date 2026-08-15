import os
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

LOCAL_DB = Path(__file__).resolve().parents[1] / 'data' / 'betmanager_v2.db'


def _database_url():
    """Retorna (url, origem). No Cloud, prioriza st.secrets."""
    secret_url = None
    try:
        secret_url = st.secrets.get("DATABASE_URL")
    except Exception:
        secret_url = None

    if secret_url:
        url = str(secret_url).strip()
        origin = "Streamlit Secrets"
    else:
        env_url = os.getenv("DATABASE_URL", "").strip()
        if env_url:
            url = env_url
            origin = "Variável de ambiente"
        else:
            url = f"sqlite:///{LOCAL_DB}"
            origin = "SQLite local"

    # Aceita também a URI original do Supabase sem exigir edição manual.
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url, origin


def _engine():
    url, origin = _database_url()
    kwargs = {'pool_pre_ping': True}
    if url.startswith('sqlite:'):
        LOCAL_DB.parent.mkdir(parents=True, exist_ok=True)
        kwargs['connect_args'] = {'check_same_thread': False}
    else:
        # Supabase/Postgres: falha rápido e exige conexão segura.
        kwargs['connect_args'] = {'connect_timeout': 10, 'sslmode': 'require'}
    return create_engine(url, future=True, **kwargs), origin


ENGINE, DATABASE_SOURCE = _engine()
DATABASE_ERROR = None

SCHEMA = '''
CREATE TABLE IF NOT EXISTS bets (
    id INTEGER PRIMARY KEY,
    user_name VARCHAR(120) NOT NULL,
    bet_date VARCHAR(20) NOT NULL,
    bookmaker VARCHAR(120),
    competition VARCHAR(180),
    country VARCHAR(120),
    event VARCHAR(250) NOT NULL,
    market VARCHAR(180),
    selection VARCHAR(250),
    bet_type VARCHAR(40),
    timing VARCHAR(40),
    odds DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    units DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    source_stake_money DOUBLE PRECISION NOT NULL DEFAULT 0,
    result VARCHAR(20) NOT NULL DEFAULT 'PENDENTE',
    profit_units DOUBLE PRECISION NOT NULL DEFAULT 0,
    notes TEXT,
    source_text TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
'''


def init_db():
    global DATABASE_ERROR
    try:
        with ENGINE.begin() as conn:
            if ENGINE.dialect.name == 'postgresql':
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS bets (
                        id BIGSERIAL PRIMARY KEY,
                        user_name VARCHAR(120) NOT NULL,
                        bet_date VARCHAR(20) NOT NULL,
                        bookmaker VARCHAR(120),
                        competition VARCHAR(180),
                        country VARCHAR(120),
                        event VARCHAR(250) NOT NULL,
                        market VARCHAR(180),
                        selection VARCHAR(250),
                        bet_type VARCHAR(40),
                        timing VARCHAR(40),
                        odds DOUBLE PRECISION NOT NULL DEFAULT 1.0,
                        units DOUBLE PRECISION NOT NULL DEFAULT 1.0,
                        source_stake_money DOUBLE PRECISION NOT NULL DEFAULT 0,
                        result VARCHAR(20) NOT NULL DEFAULT 'PENDENTE',
                        profit_units DOUBLE PRECISION NOT NULL DEFAULT 0,
                        notes TEXT,
                        source_text TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
            else:
                conn.execute(text(SCHEMA))

            # Migração segura para bases já existentes.
            try:
                conn.execute(text("ALTER TABLE bets ADD COLUMN country VARCHAR(120)"))
            except Exception:
                pass
        DATABASE_ERROR = None
    except Exception as exc:
        DATABASE_ERROR = f"{type(exc).__name__}: {exc}"
        raise


def add_bet(data: dict):
    cols = [
        'user_name','bet_date','bookmaker','competition','country','event','market','selection',
        'bet_type','timing','odds','units','source_stake_money','result','profit_units','notes','source_text'
    ]
    sql = text(f"INSERT INTO bets ({','.join(cols)}) VALUES ({','.join(':'+c for c in cols)})")
    params = {c: data.get(c) for c in cols}
    with ENGINE.begin() as conn:
        conn.execute(sql, params)


def update_result(bet_id: int, result: str):
    result = result.upper()
    with ENGINE.begin() as conn:
        row = conn.execute(text('SELECT odds, units FROM bets WHERE id=:id'), {'id': bet_id}).fetchone()
        if not row:
            return
        odds, units = float(row[0]), float(row[1])
        if result == 'WIN':
            profit = units * (odds - 1)
        elif result == 'HALF WIN':
            profit = units * (odds - 1) / 2
        elif result == 'HALF LOSS':
            profit = -units / 2
        elif result == 'LOSS':
            profit = -units
        else:
            profit = 0.0
        conn.execute(
            text('UPDATE bets SET result=:result, profit_units=:profit WHERE id=:id'),
            {'result': result, 'profit': profit, 'id': bet_id}
        )


def update_bet(bet_id: int, data: dict):
    cols=['user_name','bet_date','bookmaker','competition','country','event','market','selection','bet_type','timing','odds','units','notes']
    data=dict(data); data['id']=bet_id
    with ENGINE.begin() as conn:
        conn.execute(text('UPDATE bets SET '+','.join(f'{c}=:{c}' for c in cols)+' WHERE id=:id'), data)
        row=conn.execute(text('SELECT result, odds, units FROM bets WHERE id=:id'), {'id':bet_id}).fetchone()
        if row:
            r,odds,units=row
            profit = units*(odds-1) if r=='WIN' else units*(odds-1)/2 if r=='HALF WIN' else -units/2 if r=='HALF LOSS' else -units if r=='LOSS' else 0
            conn.execute(text('UPDATE bets SET profit_units=:p WHERE id=:id'), {'p':profit,'id':bet_id})

def update_country(bet_id: int, country: str):
    with ENGINE.begin() as conn:
        conn.execute(
            text('UPDATE bets SET country=:country WHERE id=:id'),
            {'country': country, 'id': bet_id}
        )


def delete_bet(bet_id: int):
    with ENGINE.begin() as conn:
        conn.execute(text('DELETE FROM bets WHERE id=:id'), {'id': bet_id})


def get_bets(user_name: str | None = None):
    query = 'SELECT * FROM bets'
    params = {}
    if user_name and user_name != 'TODOS':
        query += ' WHERE user_name=:user_name'
        params['user_name'] = user_name
    query += ' ORDER BY bet_date DESC, id DESC'
    with ENGINE.connect() as conn:
        return pd.read_sql_query(text(query), conn, params=params)


def get_users():
    with ENGINE.connect() as conn:
        rows = conn.execute(text('SELECT DISTINCT user_name FROM bets ORDER BY user_name')).fetchall()
    return [r[0] for r in rows]


def database_mode():
    return 'PostgreSQL Cloud' if ENGINE.dialect.name == 'postgresql' else 'SQLite local'

def database_source():
    return DATABASE_SOURCE
