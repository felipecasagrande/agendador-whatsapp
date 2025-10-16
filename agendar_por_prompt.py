from openai import OpenAI
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from datetime import datetime, timedelta
import dateparser
import pytz
import json
import re
import os

# --------------------------------------------------------
# CONFIGURAÇÕES GERAIS
# --------------------------------------------------------
SCOPES = ['https://www.googleapis.com/auth/calendar']
TZ = "America/Sao_Paulo"

OPENAI_TOKEN = os.getenv("OPENAI_TOKEN", "")
client = OpenAI(api_key=OPENAI_TOKEN) if OPENAI_TOKEN else None


# --------------------------------------------------------
# GOOGLE CREDENTIALS (carrega via variáveis de ambiente)
# --------------------------------------------------------
def _write_google_files_from_env():
    creds_txt = os.getenv("GOOGLE_CREDENTIALS_JSON")
    token_txt = os.getenv("GOOGLE_TOKEN_JSON")
    if creds_txt and not os.path.exists("credentials.json"):
        with open("credentials.json", "w", encoding="utf-8") as f:
            f.write(creds_txt)
    if token_txt and not os.path.exists("token.json"):
        with open("token.json", "w", encoding="utf-8") as f:
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
                raise FileNotFoundError("credentials.json ausente. Forneça via GOOGLE_CREDENTIALS_JSON.")
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_console()
        with open("token.json", "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)


# --------------------------------------------------------
# INTERPRETAÇÃO DO TEXTO (OpenAI)
# --------------------------------------------------------
def interpretar_prompt(prompt: str) -> dict:
    if not client:
        return {"titulo": "Reunião", "duracao_min": 60, "participantes": [], "descricao": ""}

    system = """
    Responda SOMENTE JSON no formato:
    {"titulo":"Reunião com ...","duracao_min":60,"participantes":["email@dominio"],"descricao":""}
    - Se não houver duração, use 60.
    - Se não houver e-mails, deixe participantes = [].
    - NÃO inclua campos de data/hora.
    """
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        temperature=0.2,
    )
    content = resp.choices[0].message.content
    try:
        data = json.loads(content)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            raise ValueError("IA não retornou JSON válido.")
        data = json.loads(m.group(0))

    data.setdefault("titulo", "Reunião")
    data.setdefault("duracao_min", 60)
    data.setdefault("participantes", [])
    data.setdefault("descricao", "")
    return data


# --------------------------------------------------------
# INTERPRETAÇÃO DE DATA/HORA (PORTUGUÊS)
# --------------------------------------------------------
WEEKDAYS_PT = {
    "segunda": 0, "segunda-feira": 0,
    "terca": 1, "terça": 1, "terça-feira": 1, "terca-feira": 1,
    "quarta": 2, "quarta-feira": 2,
    "quinta": 3, "quinta-feira": 3,
    "sexta": 4, "sexta-feira": 4,
    "sabado": 5, "sábado": 5,
    "domingo": 6,
}


def _norm(s: str) -> str:
    return (s.lower()
              .replace("às", "as")
              .replace("hrs", "h")
              .replace("hs", "h")
              .strip())


def resolver_datetime_pt(texto: str, default_time="14:00", tz_str=TZ):
    tz = pytz.timezone(tz_str)
    now = datetime.now(tz)
    t = _norm(texto)
    base_local = now.replace(tzinfo=None)

    dt = dateparser.parse(
        t,
        languages=["pt"],
        settings={
            "RETURN_AS_TIMEZONE_AWARE": False,
            "PREFER_DATES_FROM": "future",
            "RELATIVE_BASE": base_local,
        },
    )

    # fallback manual
    if dt is None:
        print(f"⚠️ [resolver_datetime_pt] dateparser falhou para '{t}', aplicando fallback manual.")
        if "amanha" in t or "amanhã" in t:
            match = re.search(r"\b(\d{1,2})(?::|h)?(\d{2})?\b", t)
            hour = int(match.group(1)) if match else int(default_time.split(":")[0])
            minute = int(match.group(2) or 0) if match else int(default_time.split(":")[1])
            dt = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        else:
            dow = next((WEEKDAYS_PT[k] for k in WEEKDAYS_PT if k in t), None)
            if dow is not None:
                days_ahead = (dow - now.weekday()) % 7 or 7
                match = re.search(r"\b(\d{1,2})(?::|h)?(\d{2})?\b", t)
                hour = int(match.group(1)) if match else int(default_time.split(":")[0])
                minute = int(match.group(2) or 0) if match else int(default_time.split(":")[1])
                dt = (now + timedelta(days=days_ahead)).replace(hour=hour, minute=minute, second=0, microsecond=0)
            else:
                hour, minute = map(int, default_time.split(":"))
                dt = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)

    if dt is None:
        raise ValueError(f"❌ Não foi possível interpretar data/hora em '{texto}'")

    if ("amanha" in t or "amanhã" in t) and dt.date() == now.date():
        dt = dt + timedelta(days=1)

    # ---- 🔧 CORREÇÃO FINAL ----
    if dt.tzinfo is None:
        parsed = tz.localize(dt)
    else:
        parsed = dt.astimezone(tz)

    date_iso = parsed.strftime("%Y-%m-%d")
    time_iso = parsed.strftime("%H:%M")

    print(f"✅ [resolver_datetime_pt] Texto='{texto}' → {date_iso} {time_iso}")
    return date_iso, time_iso


# --------------------------------------------------------
# CRIAÇÃO DO EVENTO NO GOOGLE CALENDAR
# --------------------------------------------------------
def criar_evento(titulo, data_inicio, hora_inicio, duracao_min, participantes, descricao):
    fuso_brasilia = pytz.timezone(TZ)
    inicio_naive = datetime.strptime(f"{data_inicio} {hora_inicio}", "%Y-%m-%d %H:%M")
    start_datetime = fuso_brasilia.localize(inicio_naive)
    end_datetime = start_datetime + timedelta(minutes=int(duracao_min or 60))

    body = {
        "summary": titulo or "Reunião",
        "description": descricao or "",
        "start": {"dateTime": start_datetime.isoformat(), "timeZone": TZ},
        "end": {"dateTime": end_datetime.isoformat(), "timeZone": TZ},
        "attendees": [{"email": e} for e in (participantes or []) if "@" in e],
    }

    service = get_calendar_service()
    ev = service.events().insert(calendarId="primary", body=body).execute()
    return ev
