import os
import re
import json
import pytz
import httpx
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


# ======================================================
# 🔐 GOOGLE CREDENTIALS
# ======================================================
def _write_google_files_from_env():
    """Cria os arquivos de credenciais a partir das variáveis do Render"""
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
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_console()
        with open("token.json", "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


# ======================================================
# 🧠 INTERPRETAÇÃO DE TEXTO (IA OpenAI — sem fallback)
# ======================================================
def interpretar_prompt(prompt: str):
    """
    Usa GPT-4o-mini para interpretar frases e retornar:
    titulo, data, hora, duracao_min, participantes, descricao
    """
    tz = pytz.timezone(TZ)
    hoje = datetime.now(tz).date()
    ano_atual = hoje.year

    try:
        token = os.getenv("OPENAI_TOKEN", "").strip()
        if not token:
            raise ValueError("OPENAI_TOKEN ausente no ambiente.")
        print(f"✅ Token OpenAI ativo (prefixo): {token[:15]}")

        exemplos = [
            {"input": "reunião com João amanhã às 10h30",
             "output": {"titulo": "Reunião com João", "data": "amanhã", "hora": "10:30"}},
            {"input": "jantar com Maria hoje às 20h",
             "output": {"titulo": "Jantar com Maria", "data": "hoje", "hora": "20:00"}},
            {"input": "call com equipe dia 22 às 09h45",
             "output": {"titulo": "Call com equipe", "data": "2025-10-22", "hora": "09:45"}}
        ]

        prompt_base = (
            "Você é um assistente que interpreta frases de agendamento em português e responde **somente** em JSON.\n"
            "O formato deve ser:\n"
            "{\n"
            '  "titulo": "texto",\n'
            '  "data": "AAAA-MM-DD",\n'
            '  "hora": "HH:MM",\n'
            '  "duracao_min": número,\n'
            '  "participantes": [],\n'
            '  "descricao": ""\n'
            "}\n\n"
            f"Exemplos:\n{json.dumps(exemplos, ensure_ascii=False, indent=2)}\n\n"
            f"Agora processe esta frase:\n'{prompt}'"
        )

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        body = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "Retorne apenas JSON válido, sem comentários ou explicações."},
                {"role": "user", "content": prompt_base},
            ],
            "temperature": 0.1,
        }

        print(f"🧠 Enviando para IA → {prompt}")
        response = httpx.post("https://api.openai.com/v1/chat/completions", headers=headers, json=body, timeout=30)
        data = response.json()

        if "error" in data:
            print("❌ Erro IA:", json.dumps(data, indent=2, ensure_ascii=False))
            raise ValueError(data["error"]["message"])

        conteudo = data["choices"][0]["message"]["content"].strip()
        if conteudo.startswith("```"):
            conteudo = conteudo.replace("```json", "").replace("```", "").strip()

        parsed = json.loads(conteudo)

        # Corrige “hoje” / “amanhã”
        if "hoje" in prompt.lower():
            parsed["data"] = hoje.strftime("%Y-%m-%d")
        elif "amanha" in prompt.lower() or "amanhã" in prompt.lower():
            parsed["data"] = (hoje + timedelta(days=1)).strftime("%Y-%m-%d")

        print("🧩 Saída final da IA:")
        print(json.dumps(parsed, indent=2, ensure_ascii=False))
        return parsed

    except Exception as e:
        print(f"❌ Erro ao interpretar prompt: {e}")
        raise


# ======================================================
# 📆 CRIAÇÃO DO EVENTO NO GOOGLE CALENDAR
# ======================================================
# ======================================================
# 📆 CRIAÇÃO DO EVENTO NO GOOGLE CALENDAR (com suporte a eventos de dia inteiro)
# ======================================================
def criar_evento(titulo, data_inicio, hora_inicio, duracao_min, participantes, descricao):
    """Cria evento no Google Calendar (com suporte a dia inteiro)"""
    fuso = pytz.timezone(TZ)

    service = get_calendar_service()

    # 🧠 Se hora for vazia → evento de dia inteiro
    if not hora_inicio or str(hora_inicio).strip() == "":
        body = {
            "summary": titulo or "Evento",
            "description": descricao or "",
            "start": {"date": data_inicio},   # 👈 usa "date", não "dateTime"
            "end": {"date": data_inicio},     # evento de um dia
            "attendees": [{"email": e} for e in (participantes or []) if "@" in e],
        }
        ev = service.events().insert(calendarId="primary", body=body).execute()
        print(f"✅ Evento de dia inteiro criado: {ev.get('htmlLink')}")
        return ev

    # ⏰ Caso normal com horário definido
    inicio = fuso.localize(datetime.strptime(f"{data_inicio} {hora_inicio}", "%Y-%m-%d %H:%M"))
    fim = inicio + timedelta(minutes=int(duracao_min or 60))

    body = {
        "summary": titulo or "Evento",
        "description": descricao or "",
        "start": {"dateTime": inicio.isoformat(), "timeZone": TZ},
        "end": {"dateTime": fim.isoformat(), "timeZone": TZ},
        "attendees": [{"email": e} for e in (participantes or []) if "@" in e],
    }

    ev = service.events().insert(calendarId="primary", body=body).execute()
    print(f"✅ Evento criado: {ev.get('htmlLink')}")
    return ev
