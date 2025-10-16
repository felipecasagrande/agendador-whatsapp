from openai import OpenAI
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import dateparser
import pytz
import json
import re
import os


SCOPES = ['https://www.googleapis.com/auth/calendar']
TZ = "America/Sao_Paulo"

# OpenAI client (ler da env)
OPENAI_TOKEN = os.getenv("OPENAI_TOKEN", "")
client = OpenAI(api_key=OPENAI_TOKEN) if OPENAI_TOKEN else None

def _write_google_files_from_env():
    creds_txt = os.getenv("GOOGLE_CREDENTIALS_JSON")
    token_txt = os.getenv("GOOGLE_TOKEN_JSON")
    if creds_txt and not os.path.exists("credentials.json"):
        with open("credentials.json","w",encoding="utf-8") as f:
            f.write(creds_txt)
    if token_txt and not os.path.exists("token.json"):
        with open("token.json","w",encoding="utf-8") as f:
            f.write(token_txt)

def get_calendar_service():
    _write_google_files_from_env()
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists("credentials.json"):
                raise FileNotFoundError("credentials.json ausente. Forneça via arquivo ou GOOGLE_CREDENTIALS_JSON.")
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            # Em Render não há navegador; prefira gerar token localmente e usar GOOGLE_TOKEN_JSON.
            creds = flow.run_console()
        with open("token.json","w",encoding="utf-8") as f:
            f.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)

def interpretar_prompt(prompt: str) -> dict:
    if not client:
        # fallback mínimo se não houver token OpenAI (usa título genérico)
        return {"titulo":"Reunião","duracao_min":60,"participantes":[],"descricao":""}
    system = """
    Responda SOMENTE JSON no formato:
    {"titulo":"Reunião com ...","duracao_min":60,"participantes":["email@dominio"],"descricao":""}
    - Se não houver duração, use 60.
    - Se não houver e-mails, deixe participantes = [].
    - NÃO inclua campos de data/hora.
    """
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"system","content":system},{"role":"user","content":prompt}],
        temperature=0.2
    )
    content = resp.choices[0].message.content
    try:
        data = json.loads(content)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", content)
        if not m: raise ValueError("IA não retornou JSON válido.")
        data = json.loads(m.group(0))
    data.setdefault("titulo","Reunião")
    data.setdefault("duracao_min",60)
    data.setdefault("participantes",[])
    data.setdefault("descricao","")
    return data

WEEKDAYS_PT = {
    "segunda": 0, "segunda-feira": 0,
    "terca": 1, "terça": 1, "terça-feira": 1, "terca-feira": 1,
    "quarta": 2, "quarta-feira": 2,
    "quinta": 3, "quinta-feira": 3,
    "sexta": 4, "sexta-feira": 4,
    "sabado": 5, "sábado": 5,
    "domingo": 6
}

def _norm(s:str)->str:
    return (s.lower().replace("às","as").replace("hrs","h").replace("hs","h").strip())

def resolver_datetime_pt(texto: str, default_time="14:00", tz_str=TZ):
    tz = pytz.timezone(tz_str)
    now = datetime.now(tz)
    t = _norm(texto)
    base_local = now.replace(tzinfo=None)

    # tenta primeiro com dateparser
    dt = dateparser.parse(
        t,
        languages=["pt"],
        settings={
            "RETURN_AS_TIMEZONE_AWARE": False,
            "PREFER_DATES_FROM": "future",
            "RELATIVE_BASE": base_local
        }
    )

    # 🔒 Fallback robusto (garante dt != None)
    if dt is None:
        print(f"⚠️ [resolver_datetime_pt] dateparser falhou para '{t}', aplicando fallback manual.")
        if "amanha" in t or "amanhã" in t:
            match = re.search(r"\b(\d{1,2})(?::|h)?(\d{2})?\b", t)
            hour = int(match.group(1)) if match else int(default_time.split(":")[0])
            minute = int(match.group(2) or 0) if match else int(default_time.split(":")[1])
            dt = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        else:
            # procura por dia da semana
            dow = next((WEEKDAYS_PT[k] for k in WEEKDAYS_PT if k in t), None)
            if dow is not None:
                days_ahead = (dow - now.weekday()) % 7
                if days_ahead == 0:
                    days_ahead = 7
                match = re.search(r"\b(\d{1,2})(?::|h)?(\d{2})?\b", t)
                hour = int(match.group(1)) if match else int(default_time.split(":")[0])
                minute = int(match.group(2) or 0) if match else int(default_time.split(":")[1])
                dt = (now + timedelta(days=days_ahead)).replace(hour=hour, minute=minute, second=0, microsecond=0)
            else:
                # fallback genérico
                hour, minute = map(int, default_time.split(":"))
                dt = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)

    # segurança — garante que dt existe
    if dt is None:
        raise ValueError(f"❌ Não foi possível interpretar data/hora em '{texto}'")

    # garante que "amanhã" vire realmente o próximo dia
    if ("amanha" in t or "amanhã" in t) and dt.date() == now.date():
        dt = dt + timedelta(days=1)

    parsed = tz.localize(dt)
    date_iso = parsed.strftime("%Y-%m-%d")
    time_iso = parsed.strftime("%H:%M")

    print(f"✅ [resolver_datetime_pt] Texto='{texto}' → {date_iso} {time_iso}")
    return date_iso, time_iso



def criar_evento(titulo, data_inicio, hora_inicio, duracao_min, participantes, descricao):
    # CORREÇÃO APLICADA AQUI: usar fuso horário corretamente
    fuso_brasilia = pytz.timezone("America/Sao_Paulo")
    
    # Criar datetime naive e depois localizar com o fuso horário
    inicio_naive = datetime.strptime(f"{data_inicio} {hora_inicio}", "%Y-%m-%d %H:%M")
    start_datetime = fuso_brasilia.localize(inicio_naive)
    
    # Calcular fim do evento
    end_datetime = start_datetime + timedelta(minutes=int(duracao_min or 60))
    
    # Converter para ISO format
    start_iso = start_datetime.isoformat()
    end_iso = end_datetime.isoformat()

    service = get_calendar_service()
    body = {
        "summary": titulo or "Reunião",
        "description": descricao or "",
        "start": {"dateTime": start_iso, "timeZone": TZ},
        "end": {"dateTime": end_iso, "timeZone": TZ},
        "attendees": [{"email": e} for e in (participantes or []) if "@" in e],
    }
    ev = service.events().insert(calendarId="primary", body=body).execute()
    return ev
