import re, os, shutil
from pathlib import Path
from datetime import date
from PIL import Image, ImageOps, ImageEnhance, ImageFilter

BOOKMAKERS = ['Betano', 'Bet365', 'Sportingbet', 'KTO', 'Novibet', 'Superbet', 'Betfair', 'Betnacional']

def _configure_tesseract():
    import pytesseract
    found = shutil.which('tesseract')
    if found:
        pytesseract.pytesseract.tesseract_cmd = found
        return found
    candidates = [
        os.environ.get('TESSERACT_CMD',''),
        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
        r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
        str(Path.home()/r'AppData\Local\Programs\Tesseract-OCR\tesseract.exe'),
    ]
    for p in candidates:
        if p and Path(p).exists():
            pytesseract.pytesseract.tesseract_cmd = p
            return p
    raise RuntimeError('OCR não encontrado. Execute novamente o INICIAR.bat para instalar/configurar o Tesseract.')

def _prepare_image(image: Image.Image) -> Image.Image:
    img=image.convert('L')
    if img.width < 1400:
        scale=max(1.0,1400/img.width)
        img=img.resize((int(img.width*scale),int(img.height*scale)))
    img=ImageOps.autocontrast(img)
    img=ImageEnhance.Contrast(img).enhance(1.45)
    img=ImageEnhance.Sharpness(img).enhance(1.25)
    return img.filter(ImageFilter.SHARPEN)

def image_to_text(image: Image.Image) -> str:
    try:
        import pytesseract
        _configure_tesseract()
        prepared=_prepare_image(image)
        try:
            langs=set(pytesseract.get_languages(config=''))
        except Exception:
            langs={'eng'}
        lang='por+eng' if {'por','eng'}.issubset(langs) else ('por' if 'por' in langs else 'eng')

        # Faz duas leituras: uma orientada a bloco e outra a linhas.
        t1=pytesseract.image_to_string(prepared, lang=lang, config='--oem 3 --psm 6')
        t2=pytesseract.image_to_string(prepared, lang=lang, config='--oem 3 --psm 11')
        # Mantém a versão com mais conteúdo útil.
        return t1 if len(t1.strip()) >= len(t2.strip()) else t2
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f'Falha ao ler o print com OCR: {exc}') from exc

def _num(value: str) -> float:
    s=value.strip().replace('R$','').replace(' ','')
    # odds geralmente usam ponto decimal; dinheiro BR geralmente usa vírgula.
    if ',' in s:
        s=s.replace('.','').replace(',','.')
    try:return float(s)
    except:return 0.0

def _clean_line(line: str) -> str:
    line=re.sub(r'^[%º°•·●○◦*|:;,_~^`´"“”!?+=<>#/\\]+','',line.strip())
    line=re.sub(r'\s+',' ',line).strip()
    return line

def _looks_like_team(line: str) -> bool:
    if not line or len(line) < 3 or len(line) > 80:return False
    low=line.lower()
    banned=['menos de','mais de','gols','odd','aposta','stake','retorno','valor','simples',
            'dupla','tripla','múltipla','multipla','ao vivo','pré-jogo','pre-jogo',
            'handicap','escanteios','resultado final','ambas marcam']
    if any(x in low for x in banned): return False
    if re.fullmatch(r'[\d\s.,+\-]+',line): return False
    return bool(re.search(r'[A-Za-zÀ-ÿ]{2,}',line))

def parse_text(text: str) -> dict:
    raw_lines=[_clean_line(x) for x in text.splitlines()]
    lines=[x for x in raw_lines if x]
    clean=' '.join(lines)
    low=clean.lower()

    bookmaker=next((b for b in BOOKMAKERS if b.lower() in low), '')

    # ODD: aceita 1.70, 1.700, 2,05 etc. Prioriza números plausíveis no fim da linha da seleção.
    odds=1.0
    odd_candidates=[]
    for line in lines:
        for m in re.finditer(r'(?<!\d)(\d{1,2}[.,]\d{2,3})(?!\d)',line):
            val_str=m.group(1)
            # 2,500 dentro de "2,5 3,0" não deve virar odd; aceitamos faixa plausível.
            val=_num(val_str)
            if 1.01 <= val <= 100:
                odd_candidates.append((line,m.start(),val))
    if odd_candidates:
        # prefere linha que contenha a seleção over/under/hc
        preferred=[x for x in odd_candidates if re.search(r'(menos de|mais de|over|under|handicap|hc)',x[0],re.I)]
        odds=(preferred or odd_candidates)[-1][2]

    # Seleção / linha principal
    selection=''
    selection_line=''
    for line in lines:
        m=re.search(r"([A-Za-zÀ-ÿ0-9 .'\-]{2,60}?)\s*-\s*((?:menos de|mais de|over|under)\s+\d+(?:[.,]\d+)?)",line,re.I)
        if m:
            selection=f"{_clean_line(m.group(1))} - {m.group(2).strip()}"
            selection_line=line
            break
        m=re.search(r'((?:menos de|mais de|over|under)\s+\d+(?:[.,]\d+)?)',line,re.I)
        if m:
            selection=m.group(1).strip()
            selection_line=line
            break
        m=re.search(r'((?:handicap|hc)\s*[+\-]?\s*\d+(?:[.,]\d+)?)',line,re.I)
        if m:
            selection=m.group(1).strip()
            selection_line=line
            break

    # Mercado
    market=''
    lowclean=clean.lower()
    if re.search(r'chutes?\s+no\s+alvo|remates?\s+no\s+alvo|finaliza(?:ç|c)ões?\s+no\s+alvo',lowclean,re.I):
        market='Time da Casa - Chutes no Alvo' if 'time da casa' in lowclean else ('Time Visitante - Chutes no Alvo' if 'time visitante' in lowclean else 'Chutes no Alvo')
    elif re.search(r'\bchutes?\b|\bremates?\b|finaliza(?:ç|c)ões?',lowclean,re.I):
        market='Time da Casa - Chutes' if 'time da casa' in lowclean else ('Time Visitante - Chutes' if 'time visitante' in lowclean else 'Chutes')
    elif re.search(r'escanteios|corners',lowclean,re.I):
        market='Escanteios'
    elif re.search(r'handicap|\bhc\b',lowclean,re.I):
        market='Handicap'
    elif re.search(r'ambas\s+marcam|btts',lowclean,re.I):
        market='Ambas marcam'
    elif re.search(r'resultado\s+final|moneyline|vencedor',lowclean,re.I):
        market='Resultado final'
    elif any(re.search(r'gols?\s*[+\-]',x,re.I) for x in lines) or re.search(r'(menos de|mais de|over|under)\s+\d',lowclean,re.I):
        market='Gols +/-'

    # Times: primeiro tenta "A x B"; depois procura duas linhas com cara de nome de equipe.
    event=''
    versus=re.search(r'([A-Za-zÀ-ÿ0-9 .\'\-]{2,60})\s+(?:x|vs\.?|v)\s+([A-Za-zÀ-ÿ0-9 .\'\-]{2,60})',clean,re.I)
    if versus:
        event=f"{versus.group(1).strip()} x {versus.group(2).strip()}"
    else:
        team_lines=[]
        # Em bilhetes como o exemplo, as equipes vêm após a linha de mercado.
        start=0
        for i,line in enumerate(lines):
            if re.search(r'gols?|chutes?|remates?|finaliza|escanteios|corners|handicap|resultado',line,re.I):
                start=i+1
        for line in lines[start:]:
            if _looks_like_team(line):
                # remove emojis/resíduos já tratados; não aceita linha de seleção
                team_lines.append(line)
            if len(team_lines)>=2: break
        if len(team_lines)<2:
            team_lines=[x for x in lines if _looks_like_team(x)]
        if len(team_lines)>=2:
            event=f"{team_lines[-2]} x {team_lines[-1]}"

    # Stake em reais apenas informativa
    source_stake_money=0.0
    stake_match=re.search(r'(?:aposta|valor|stake)\s*[:\-]?\s*R?\$?\s*([\d\.]+,\d{2}|\d+(?:\.\d{2})?)',clean,re.I)
    if stake_match: source_stake_money=_num(stake_match.group(1))

    # Normaliza seleção em português se OCR captou "Menos de"
    selection=re.sub(r'\s+',' ',selection).strip()

    return {
        'user_name':'',
        'bet_date':str(date.today()),
        'bookmaker':bookmaker,
        'competition':'',
        'event':event,
        'market':market,
        'selection':selection,
        'bet_type':'Simples',
        'timing':'Pré-jogo',
        'odds':odds,
        'units':1.0,
        'source_stake_money':source_stake_money,
        'result':'PENDENTE',
        'profit_units':0.0,
        'notes':'',
        'source_text':text,
    }
