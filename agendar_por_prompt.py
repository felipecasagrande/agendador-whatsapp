import os
import json
import re
import pytz
import httpx
import dateparser
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request


# ======================================================
# 🔧 CONFIGURAÇÕES GERAIS
# ======================================================
SCOPES = ["https://www.googleapis.com/auth/calendar"]
TZ = "America/Sao_Paulo"
OPENAI_TOKEN = os.getenv("OPENAI_TOKEN", "")
client = None

if OPENAI_TOKEN:
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_TOKEN)


# ======================================================
# 🔐 GOOGLE CREDENTIALS
# ======================================================
def _write_google_files_from_env():
    """Cria os arquivos de credenciais do Google a partir das variáveis de ambiente"""
    creds_txt = os.getenv("GOOGLE_CREDENTIALS_JSON")
    token_txt = os.getenv("GOOGLE_TOKEN_JSON")

    if creds_txt and not os.path.exists("credentials.json"):
        with open("credentials.json", "w", encoding="utf-8") as f:
            f.write(creds_txt)

    if token_txt and not os.path.exists("token.json"):
        with open("token.json", "w", encoding="utf-8") as f:
            f.write(token_txt)


def get_calendar_service():
    """Autentica e retorna o serviço do Google Calendar"""
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


# ======================================================
# 🧠 INTERPRETAÇÃO DE TEXTO (IA OpenAI)
# ======================================================
def interpretar_prompt(prompt: str):
    """
    Interpreta o texto do usuário (ex: 'reunião com João amanhã às 15h')
    e retorna um dicionário com título, data e hora interpretados.
    """
    tz = pytz.timezone(TZ)
    hoje = datetime.now(tz).date()
    ano_atual = hoje.year

    try:
        if not OPENAI_TOKEN:
            raise ValueError("OPENAI_TOKEN não definido no ambiente.")

        headers = {
            "Authorization": f"Bearer {OPENAI_TOKEN}",
            "Content-Type": "application/json",
        }

        body = {
            "model": "gpt-4o-mini",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Você é um assistente que extrai informações estruturadas de eventos "
                        "(título, data, hora, duração, participantes, descrição) de frases em português."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Extraia da frase abaixo as informações estruturadas:\n\n"
                        f"Frase: '{prompt}'\n\n"
                        "Responda APENAS em JSON com os campos: "
                        "titulo, data (AAAA-MM-DD), hora (HH:MM), duracao_min, participantes (lista) e descricao."
                    ),
                },
            ],
            "temperature": 0.2,
        }

        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=body,
            timeout=20,
        )
        data = response.json()
        conteudo = data["choices"][0]["message"]["content"].strip()
        parsed = json.loads(conteudo)

        # Campos principais
        data_str = parsed.get("data")
        hora_str = parsed.get("hora")

        # 🔧 Correção de ano
        if data_str:
            try:
                dt = datetime.strptime(data_str, "%Y-%m-%d")
                if dt.year < ano_atual:
                    dt = dt.replace(year=ano_atual)
                    parsed["data"] = dt.strftime("%Y-%m-%d")
                    print(f"🔧 Corrigido ano → {parsed['data']}")
            except Exception:
                pass

        # 🔧 Correção para “hoje” e “amanhã”
        if "hoje" in prompt.lower():
            parsed["data"] = hoje.strftime("%Y-%m-%d")
            print(f"🔧 Corrigido 'hoje' → {parsed['data']}")
        elif "amanha" in prompt.lower() or "amanhã" in prompt.lower():
            parsed["data"] = (hoje + timedelta(days=1)).strftime("%Y-%m-%d")
            print(f"🔧 Corrigido 'amanhã' → {parsed['data']}")

        print("🧩 Saída da IA:", json.dumps(parsed, indent=2, ensure_ascii=False))
        return parsed

    except Exception as e:
        print(f"❌ Erro ao interpretar prompt: {e}")
        return {
            "titulo": prompt,
            "data": None,
            "hora": None,
            "duracao_min": 60,
            "participantes": [],
            "descricao": "",
        }


# ======================================================
# 📅 FALLBACK MANUAL (quando a IA falha)
# ======================================================
def resolver_datetime_pt(texto: str, default_time="14:00", tz_str=TZ):
    """
    Interpreta datas/horas em português mesmo sem IA (fallback)
    Exemplo: "reunião dia 23 às 16h30" → 2025-10-23 16:30
    """
    tz = pytz.timezone(tz_str)
    now = datetime.now(tz)
    t = texto.lower().replace("às", "as").replace("hrs", "h").replace("hs", "h").strip()

    # 1️⃣ Tenta direto via dateparser
    dt = dateparser.parse(
        t,
        languages=["pt"],
        settings={
            "RETURN_AS_TIMEZONE_AWARE": False,
            "PREFER_DATES_FROM": "future",
            "RELATIVE_BASE": now.replace(tzinfo=None),
        },
    )

    # 2️⃣ Se falhar, tenta regex para "dia 23", "às 16h10", etc.
    if dt is None:
        print(f"⚠️ [resolver_datetime_pt] dateparser falhou para '{t}', aplicando regex manual.")

        dia_match = re.search(r"\bdia\s*(\d{1,2})\b", t)
        dia_num = int(dia_match.group(1)) if dia_match else None

        hora_match = re.search(r"(\d{1,2})(?:[:h](\d{2}))?", t)
        hour = int(hora_match.group(1)) if hora_match else int(default_time.split(":")[0])
        minute = int(hora_match.group(2) or 0) if hora_match else int(default_time.split(":")[1])

        ano, mes = now.year, now.month
        if dia_num:
            if dia_num < now.day:
                mes += 1
                if mes > 12:
                    mes, ano = 1, ano + 1
            try:
                dt = datetime(ano, mes, dia_num, hour, minute)
            except ValueError:
                dt = now + timedelta(days=1)
        else:
            if "amanha" in t or "amanhã" in t:
                dt = (now + timedelta(days=1)).replace(hour=hour, minute=minute)
            else:
                dt = now.replace(hour=hour, minute=minute)

    # 3️⃣ Normaliza para timezone Brasil
    parsed = tz.localize(dt) if dt.tzinfo is None else dt.astimezone(tz)
    print(f"✅ [resolver_datetime_pt] '{texto}' → {parsed.strftime('%Y-%m-%d %H:%M')}")
    return parsed.strftime("%Y-%m-%d"), parsed.strftime("%H:%M")


# ======================================================
# 📆 CRIAÇÃO DO EVENTO NO GOOGLE CALENDAR
# ======================================================
def criar_evento(titulo, data_inicio, hora_inicio, duracao_min, participantes, descricao):
    """Cria evento no Google Calendar"""
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
