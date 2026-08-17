import os
import base64
import threading
import time
from datetime import datetime, timedelta
import requests
import streamlit as st
from sqlalchemy import text
from src.db import ENGINE

_worker_started = False
_lock = threading.Lock()


def _secret(name, default=''):
    try:
        v = st.secrets.get(name, default)
    except Exception:
        v = os.getenv(name, default)
    return str(v or '').strip()


def telegram_config():
    return _secret('TELEGRAM_BOT_TOKEN'), _secret('TELEGRAM_CHAT_ID', '-5329496686')


def configured():
    token, chat = telegram_config()
    return bool(token and chat)


def send_message(message: str, chat_id: str | None = None):
    token, default_chat = telegram_config()
    target = (chat_id or default_chat).strip()
    if not token or not target:
        raise RuntimeError('Configure TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID nos Secrets.')
    r = requests.post(
        f'https://api.telegram.org/bot{token}/sendMessage',
        json={'chat_id': target, 'text': message, 'parse_mode': 'HTML', 'disable_web_page_preview': True},
        timeout=15,
    )
    r.raise_for_status()
    payload = r.json()
    if not payload.get('ok'):
        raise RuntimeError(payload.get('description', 'Falha no Telegram'))
    return payload['result'].get('message_id')



def send_photo_data_url(data_url: str, caption: str = '', reply_to_message_id=None, chat_id: str | None = None):
    """Envia ao Telegram o print original colado/enviado em Importar aposta."""
    token, default_chat = telegram_config()
    target = (chat_id or default_chat).strip()
    if not token or not target:
        raise RuntimeError('Configure TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID nos Secrets.')
    if not data_url or ',' not in data_url:
        return None
    header, encoded = data_url.split(',', 1)
    mime = 'image/jpeg' if 'jpeg' in header.lower() or 'jpg' in header.lower() else 'image/png'
    ext = 'jpg' if mime == 'image/jpeg' else 'png'
    raw = base64.b64decode(encoded)
    data = {'chat_id': target}
    if caption:
        data['caption'] = caption[:1024]
        data['parse_mode'] = 'HTML'
    if reply_to_message_id:
        try:
            data['reply_parameters'] = '{"message_id":%d}' % int(reply_to_message_id)
        except Exception:
            pass
    r = requests.post(
        f'https://api.telegram.org/bot{token}/sendPhoto',
        data=data,
        files={'photo': (f'aposta.{ext}', raw, mime)},
        timeout=25,
    )
    r.raise_for_status()
    payload = r.json()
    if not payload.get('ok'):
        raise RuntimeError(payload.get('description', 'Falha ao enviar print no Telegram'))
    return payload['result'].get('message_id')

def format_bet(row, reminder=False):
    title = '⏰ <b>JOGO COMEÇA EM 10 MINUTOS</b>' if reminder else '🔥 <b>NOVA ENTRADA</b>'
    parts = [title, '']
    if row.get('event'): parts.append(f"⚽ <b>{row['event']}</b>")
    if row.get('competition'): parts.append(f"🏆 {row['competition']}")
    if row.get('market'): parts.append(f"🎯 {row['market']}")
    if row.get('selection'): parts.append(f"📌 {row['selection']}")
    if not reminder:
        parts.append(f"💰 Odd: <b>{float(row.get('odds') or 1):.2f}</b>")
        parts.append(f"📊 Stake: <b>{float(row.get('units') or 1):g}u</b>")
    if row.get('game_time'):
        try:
            dt = datetime.fromisoformat(str(row['game_time']))
            parts.append(f"🕐 Início: <b>{dt.strftime('%d/%m %H:%M')}</b>")
        except Exception:
            pass
    if row.get('bookmaker'): parts.append(f"🏦 {row['bookmaker']}")
    if row.get('user_name'): parts.append(f"👤 Tipster: {row['user_name']}")
    return '\n'.join(parts)


def dispatch_bet(bet_id: int, image_data_url: str | None = None):
    with ENGINE.begin() as conn:
        row = conn.execute(text('SELECT * FROM bets WHERE id=:id'), {'id': bet_id}).mappings().first()
        if not row: raise RuntimeError('Aposta não encontrada.')
        mid = send_message(format_bet(dict(row)))
        conn.execute(text('UPDATE bets SET telegram_sent=1, telegram_message_id=:mid WHERE id=:id'), {'mid': str(mid), 'id': bet_id})
        if image_data_url:
            send_photo_data_url(image_data_url, caption='📸 <b>Print original da entrada</b>', reply_to_message_id=mid)
    return mid



def format_result(row, previous_result=None):
    result = str(row.get('result') or '').upper()
    labels = {
        'WIN': '✅ <b>GREEN</b>',
        'HALF WIN': '🟢 <b>HALF GREEN</b>',
        'VOID': '⚪ <b>VOID</b>',
        'HALF LOSS': '🟠 <b>HALF RED</b>',
        'LOSS': '❌ <b>RED</b>',
    }
    headline = labels.get(result, f'📌 <b>{result}</b>')
    title = '🔄 <b>RESULTADO ATUALIZADO</b>' if previous_result and str(previous_result).upper() != result else '📊 <b>RESULTADO DA ENTRADA</b>'
    parts = [title, '', headline, '']
    if row.get('event'): parts.append(f"⚽ <b>{row['event']}</b>")
    if row.get('market'): parts.append(f"🎯 {row['market']}")
    if row.get('selection'): parts.append(f"📌 {row['selection']}")
    if row.get('odds') is not None: parts.append(f"💰 Odd: <b>{float(row.get('odds') or 1):.2f}</b>")
    if row.get('units') is not None: parts.append(f"📊 Stake: <b>{float(row.get('units') or 1):g}u</b>")
    if row.get('profit_units') is not None:
        profit = float(row.get('profit_units') or 0)
        parts.append(f"💵 Resultado: <b>{profit:+.2f}u</b>")
    if row.get('user_name'): parts.append(f"👤 Tipster: {row['user_name']}")
    return '\n'.join(parts)


def dispatch_result(bet_id: int, force: bool = False):
    with ENGINE.begin() as conn:
        row = conn.execute(text('SELECT * FROM bets WHERE id=:id'), {'id': bet_id}).mappings().first()
        if not row:
            raise RuntimeError('Aposta não encontrada.')
        row = dict(row)
        result = str(row.get('result') or '').upper()
        if result == 'PENDENTE':
            return None
        if not int(row.get('telegram_sent') or 0):
            raise RuntimeError('A entrada ainda não foi enviada ao Telegram.')
        previous = str(row.get('telegram_result') or '').upper() or None
        if previous == result and not force:
            return row.get('telegram_result_message_id')
        reply_to = row.get('telegram_message_id')
        token, default_chat = telegram_config()
        if not token or not default_chat:
            raise RuntimeError('Configure TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID nos Secrets.')
        payload = {
            'chat_id': default_chat,
            'text': format_result(row, previous_result=previous),
            'parse_mode': 'HTML',
            'disable_web_page_preview': True,
        }
        if reply_to:
            try:
                payload['reply_parameters'] = {'message_id': int(reply_to)}
            except Exception:
                pass
        r = requests.post(f'https://api.telegram.org/bot{token}/sendMessage', json=payload, timeout=15)
        r.raise_for_status()
        data = r.json()
        if not data.get('ok'):
            raise RuntimeError(data.get('description', 'Falha no Telegram'))
        mid = data['result'].get('message_id')
        conn.execute(text('UPDATE bets SET telegram_result=:result, telegram_result_message_id=:mid WHERE id=:id'), {'result': result, 'mid': str(mid), 'id': bet_id})
        return mid

def _check_reminders():
    now = datetime.now()
    horizon = now + timedelta(minutes=10, seconds=59)
    with ENGINE.connect() as conn:
        rows = conn.execute(text("SELECT * FROM bets WHERE telegram_sent=1 AND reminder_10m=1 AND reminder_sent=0 AND game_time IS NOT NULL")).mappings().all()
    for raw in rows:
        row = dict(raw)
        try:
            game_time = datetime.fromisoformat(str(row['game_time']))
        except Exception:
            continue
        target = game_time - timedelta(minutes=10)
        if target <= now <= horizon and game_time > now:
            try:
                send_message(format_bet(row, reminder=True))
                with ENGINE.begin() as conn:
                    conn.execute(text('UPDATE bets SET reminder_sent=1 WHERE id=:id AND reminder_sent=0'), {'id': row['id']})
            except Exception:
                pass


def _worker():
    while True:
        try: _check_reminders()
        except Exception: pass
        time.sleep(20)


def start_worker():
    global _worker_started
    with _lock:
        if _worker_started: return
        threading.Thread(target=_worker, daemon=True, name='telegram-reminders').start()
        _worker_started = True
