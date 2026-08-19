import os
import base64
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
import re
from urllib.parse import urlparse
import streamlit as st
from io import BytesIO
from PIL import Image
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




def extract_bet_link(text_value: str | None):
    """Extrai o primeiro link http/https encontrado em Observações."""
    text_value = str(text_value or '')
    match = re.search(r'https?://[^\s<>"\']+', text_value, flags=re.IGNORECASE)
    if not match:
        return ''
    # Remove pontuação comum que pode ter sido colada logo depois do link.
    return match.group(0).rstrip('.,;:!?)]}')


def _bet_button(row):
    """Cria o botão usando o link salvo ou, como fallback, o link das Observações."""
    url = str(row.get('bet_link') or '').strip() or extract_bet_link(row.get('notes'))
    if not url:
        return None
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc:
            return None
    except Exception:
        return None

    host = parsed.netloc.lower()
    bookmaker = str(row.get('bookmaker') or '').strip().lower()
    if 'bet365' in host or bookmaker == 'bet365':
        label = '🎯 ABRIR NA BET365'
    elif 'betano' in host or bookmaker == 'betano':
        label = '🎯 ABRIR NA BETANO'
    elif 'betfair' in host or bookmaker in ('bolsa', 'betfair'):
        label = '📈 ABRIR NA BOLSA'
    elif 'pinnacle' in host or bookmaker == 'pinnacle':
        label = '🎯 ABRIR NA PINNACLE'
    else:
        label = '🎯 ABRIR APOSTA'
    return {'inline_keyboard': [[{'text': label, 'url': url}]]}

def send_message(message: str, chat_id: str | None = None, reply_markup=None):
    token, default_chat = telegram_config()
    target = (chat_id or default_chat).strip()
    if not token or not target:
        raise RuntimeError('Configure TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID nos Secrets.')
    r = requests.post(
        f'https://api.telegram.org/bot{token}/sendMessage',
        json={**{'chat_id': target, 'text': message, 'parse_mode': 'HTML', 'disable_web_page_preview': True}, **({'reply_markup': reply_markup} if reply_markup else {})},
        timeout=15,
    )
    r.raise_for_status()
    payload = r.json()
    if not payload.get('ok'):
        raise RuntimeError(payload.get('description', 'Falha no Telegram'))
    return payload['result'].get('message_id')



def _image_bytes_from_data_url(data_url: str):
    """Normaliza PNG/JPG/WEBP/etc para JPEG antes de enviar ao Telegram."""
    if not data_url or ',' not in data_url:
        raise RuntimeError('Print da aposta não encontrado na sessão.')
    try:
        _header, encoded = data_url.split(',', 1)
        raw = base64.b64decode(encoded)
        with Image.open(BytesIO(raw)) as img:
            img = img.convert('RGB')
            out = BytesIO()
            img.save(out, format='JPEG', quality=92, optimize=True)
            return out.getvalue()
    except Exception as exc:
        raise RuntimeError(f'Não consegui preparar o print para o Telegram: {exc}') from exc


def normalize_image_data_url(data_url: str) -> str:
    """Converte o print para JPEG/base64 compacto para poder persistir no banco."""
    raw = _image_bytes_from_data_url(data_url)
    return 'data:image/jpeg;base64,' + base64.b64encode(raw).decode('ascii')


def send_photo_data_url(data_url: str, caption: str = '', reply_to_message_id=None, chat_id: str | None = None, reply_markup=None):
    """Envia ao Telegram o print original colado/enviado em Importar aposta."""
    token, default_chat = telegram_config()
    target = (chat_id or default_chat).strip()
    if not token or not target:
        raise RuntimeError('Configure TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID nos Secrets.')

    raw = _image_bytes_from_data_url(data_url)
    data = {'chat_id': target}
    if caption:
        data['caption'] = caption[:1024]
        data['parse_mode'] = 'HTML'
    if reply_markup:
        data['reply_markup'] = __import__('json').dumps(reply_markup, ensure_ascii=False)
    if reply_to_message_id:
        # reply_to_message_id continua amplamente aceito pelo endpoint e evita
        # incompatibilidades de serialização de reply_parameters em multipart.
        data['reply_to_message_id'] = str(reply_to_message_id)
        data['allow_sending_without_reply'] = 'true'

    r = requests.post(
        f'https://api.telegram.org/bot{token}/sendPhoto',
        data=data,
        files={'photo': ('aposta.jpg', raw, 'image/jpeg')},
        timeout=30,
    )
    try:
        payload = r.json()
    except Exception:
        payload = {}
    if not r.ok or not payload.get('ok'):
        raise RuntimeError(payload.get('description') or f'Falha ao enviar print no Telegram (HTTP {r.status_code})')
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
    # Primeiro busca os dados; chamadas de rede ficam fora da transação do banco.
    with ENGINE.connect() as conn:
        row = conn.execute(text('SELECT * FROM bets WHERE id=:id'), {'id': bet_id}).mappings().first()
    if not row:
        raise RuntimeError('Aposta não encontrada.')

    formatted = format_bet(dict(row))

    # Se a aposta veio de "Importar aposta", o sinal inteiro vai como legenda
    # do próprio print. Se a sessão já acabou, usa o print persistido no banco.
    stored_image = str(row.get('source_image') or '').strip()
    image_to_send = image_data_url or stored_image
    if image_to_send:
        mid = send_photo_data_url(image_to_send, caption=formatted, reply_markup=_bet_button(dict(row)))
    else:
        mid = send_message(formatted, reply_markup=_bet_button(dict(row)))

    # Só marca como enviada depois que Telegram confirmar a mensagem/foto.
    with ENGINE.begin() as conn:
        conn.execute(
            text('UPDATE bets SET telegram_sent=1, telegram_message_id=:mid WHERE id=:id'),
            {'mid': str(mid), 'id': bet_id},
        )
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
<<<<<<< HEAD
    # game_time é salvo como horário local de Brasília (sem offset).
    # O Streamlit Cloud pode rodar em UTC, então nunca usamos datetime.now() puro.
    br_tz = ZoneInfo('America/Sao_Paulo')
    now_br = datetime.now(br_tz).replace(tzinfo=None)

=======
    # game_time é salvo como horário LOCAL de Brasília (sem offset).
    # O Streamlit Cloud roda normalmente em UTC, portanto datetime.now() sem
    # timezone fazia o lembrete disparar ~3h antes. Comparamos tudo explicitamente
    # em America/Sao_Paulo para evitar diferença entre servidor e usuário.
    br_tz = ZoneInfo("America/Sao_Paulo")
    now = datetime.now(br_tz)
    horizon = now + timedelta(minutes=10, seconds=59)
>>>>>>> 15b3d7fc0d882dbe55f51898ca73a5e860466f8e
    with ENGINE.connect() as conn:
        rows = conn.execute(text(
            "SELECT * FROM bets WHERE telegram_sent=1 AND reminder_10m=1 "
            "AND reminder_sent=0 AND game_time IS NOT NULL"
        )).mappings().all()

    for raw in rows:
        row = dict(raw)
        try:
<<<<<<< HEAD
            game_time = datetime.fromisoformat(str(row['game_time'])).replace(tzinfo=None)
=======
            game_time = datetime.fromisoformat(str(row['game_time']))
            if game_time.tzinfo is None:
                # Valores atuais do banco já representam hora de Brasília.
                game_time = game_time.replace(tzinfo=br_tz)
            else:
                game_time = game_time.astimezone(br_tz)
>>>>>>> 15b3d7fc0d882dbe55f51898ca73a5e860466f8e
        except Exception:
            continue

        target = game_time - timedelta(minutes=10)
<<<<<<< HEAD
        # Janela curta: aceita até 2 minutos de atraso (worker/deploy), mas nunca
        # antecipa o lembrete. Isso também evita reaproveitar apostas antigas.
        if not (target <= now_br < target + timedelta(minutes=2) and game_time > now_br):
            continue

        # LOCK ATÔMICO: 0=pendente, 2=enviando, 1=enviado.
        # Duas instâncias do Streamlit podem executar o worker ao mesmo tempo;
        # apenas uma consegue trocar 0 -> 2 e fica autorizada a enviar.
        with ENGINE.begin() as conn:
            claimed = conn.execute(
                text('UPDATE bets SET reminder_sent=2 WHERE id=:id AND reminder_sent=0'),
                {'id': row['id']},
            )
            if claimed.rowcount != 1:
                continue

        try:
            reply_to = row.get('telegram_message_id')
            image_data = row.get('bet_image_data')
            if image_data:
                send_photo_data_url(
                    image_data,
                    caption=format_bet(row, reminder=True),
                    reply_to_message_id=reply_to,
                    reply_markup=_bet_button(row),
                )
            else:
                # Fallback para apostas antigas, que não possuem print salvo.
                token, default_chat = telegram_config()
                payload = {
                    'chat_id': default_chat,
                    'text': format_bet(row, reminder=True),
                    'parse_mode': 'HTML',
                    'disable_web_page_preview': True,
                }
                if _bet_button(row):
                    payload['reply_markup'] = _bet_button(row)
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

            with ENGINE.begin() as conn:
                conn.execute(text('UPDATE bets SET reminder_sent=1 WHERE id=:id'), {'id': row['id']})
        except Exception:
            # Libera para nova tentativa apenas se o envio falhar de verdade.
            with ENGINE.begin() as conn:
                conn.execute(text('UPDATE bets SET reminder_sent=0 WHERE id=:id AND reminder_sent=2'), {'id': row['id']})
=======
        if target <= now <= horizon and game_time > now:
            try:
                # O lembrete reaproveita o print original salvo no banco e também
                # o botão gerado pelo link encontrado em Observações.
                reminder_text = format_bet(row, reminder=True)
                stored_image = str(row.get('source_image') or '').strip()
                if stored_image:
                    send_photo_data_url(stored_image, caption=reminder_text, reply_markup=_bet_button(row))
                else:
                    send_message(reminder_text, reply_markup=_bet_button(row))
                with ENGINE.begin() as conn:
                    conn.execute(text('UPDATE bets SET reminder_sent=1 WHERE id=:id AND reminder_sent=0'), {'id': row['id']})
            except Exception:
                pass
>>>>>>> 15b3d7fc0d882dbe55f51898ca73a5e860466f8e


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
