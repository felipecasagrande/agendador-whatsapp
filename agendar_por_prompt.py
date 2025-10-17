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

def interpretar_prompt(prompt: str):
    """
    Interpreta o texto do usuário (ex: 'reunião com João amanhã às 15h')
    e retorna um dicionário com título, data e hora interpretados.
    """
    tz = pytz.timezone("America/Sao_Paulo")
    hoje = datetime.now(tz).date()
    ano_atual = hoje.year

    try:
        # 🧠 Chamada para IA interpretar prompt
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }

        body = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "Você é um assistente que extrai dados de eventos (título, data, hora) de frases em português."},
                {"role": "user", "content": f"Extraia da frase abaixo as informações estruturadas:\n\nFrase: '{prompt}'\n\nResponda em JSON com os campos: titulo, data (AAAA-MM-DD), hora (HH:MM), duracao_min, participantes (lista) e descricao."}
            ],
            "temperature": 0.2
        }

        response = httpx.post("https://api.openai.com/v1/chat/completions", headers=headers, json=body, timeout=20)
        data = response.json()

        conteudo = data["choices"][0]["message"]["content"].strip()
        parsed = json.loads(conteudo)

        # Campos principais
        data_str = parsed.get("data")
        hora_str = parsed.get("hora")

        # ---------------------------
        # 🔧 CORREÇÃO DE ANO
        # ---------------------------
        if data_str:
            try:
                dt = datetime.strptime(data_str, "%Y-%m-%d")
                if dt.year < ano_atual:
                    dt = dt.replace(year=ano_atual)
                    parsed["data"] = dt.strftime("%Y-%m-%d")
                    print(f"🔧 Corrigido ano da data para {parsed['data']}")
            except Exception:
                pass

        # ---------------------------
        # 🔧 CORREÇÃO "HOJE" / "AMANHÃ"
        # ---------------------------
        if "hoje" in prompt.lower():
            parsed["data"] = hoje.strftime("%Y-%m-%d")
            print(f"🔧 Corrigido 'hoje' → {parsed['data']}")
        elif "amanha" in prompt.lower() or "amanhã" in prompt.lower():
            parsed["data"] = (hoje + timedelta(days=1)).strftime("%Y-%m-%d")
            print(f"🔧 Corrigido 'amanhã' → {parsed['data']}")

        # ---------------------------
        # ✅ LOG FINAL
        # ---------------------------
        print("🧩 Saída da IA:", json.dumps(parsed, indent=2, ensure_ascii=False))
        return parsed

    except Exception as e:
        print(f"❌ Erro ao interpretar prompt: {e}")
        return {"titulo": prompt, "data": None, "hora": None, "duracao_min": 60, "participantes": [], "descricao": ""}


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

    # 1️⃣ Tenta interpretar diretamente
    dt = dateparser.parse(
        t,
        languages=["pt"],
        settings={
            "RETURN_AS_TIMEZONE_AWARE": False,
            "PREFER_DATES_FROM": "future",
            "RELATIVE_BASE": base_local,
        },
    )

    # 2️⃣ Se o parser não entendeu, aplica regras manuais
    if dt is None:
        print(f"⚠️ [resolver_datetime_pt] dateparser falhou para '{t}', aplicando fallback manual.")

        # --- CORREÇÃO: caso "hoje" esteja no texto ---
        if "hoje" in t:
            match = re.search(r"\b(\d{1,2})(?::|h)?(\d{2})?\b", t)
            hour = int(match.group(1)) if match else int(default_time.split(":")[0])
            minute = int(match.group(2) or 0) if match else int(default_time.split(":")[1])
            dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        elif "amanha" in t or "amanhã" in t:
            match = re.search(r"\b(\d{1,2})(?::|h)?(\d{2})?\b", t)
            hour = int(match.group(1)) if match else int(default_time.split(":")[0])
            minute = int(match.group(2) or 0) if match else int(default_time.split(":")[1])
            dt = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)

        else:
            # fallback genérico para outras palavras
            hour, minute = map(int, default_time.split(":"))
            dt = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)

    # 3️⃣ Ajuste de coerência
    if "amanha" in t or "amanhã" in t:
        if dt.date() == now.date():
            dt = dt + timedelta(days=1)

    if dt.tzinfo is None:
        parsed = tz.localize(dt)
    else:
        parsed = dt.astimezone(tz)

    print(f"✅ [resolver_datetime_pt] Texto='{texto}' → {parsed.strftime('%Y-%m-%d %H:%M')}")
    return parsed.strftime("%Y-%m-%d"), parsed.strftime("%H:%M")


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
