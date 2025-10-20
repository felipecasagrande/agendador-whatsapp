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
# 🧠 INTERPRETAÇÃO DE TEXTO (IA OpenAI)
# ======================================================
def interpretar_prompt(prompt: str):
    """
    Usa GPT-4o-mini para interpretar frases e retornar:
    titulo, data, hora, duracao_min, participantes, descricao, colorId
    """
    tz = pytz.timezone(TZ)
    hoje = datetime.now(tz).date()

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
            {"input": "comprar suco dia 23/10/2025",
             "output": {"titulo": "Comprar suco", "data": "2025-10-23", "hora": ""}},
            {"input": "❤️⏳🏠 de 21h25 até 22h25 enviar para convidado britto.marilia@gmail.com",
             "output": {"titulo": "❤️⏳🏠", "data": "hoje", "hora": "21:25", "duracao_min": 60, "participantes": ["britto.marilia@gmail.com"], "descricao": ""}}
        ]

        prompt_base = (
            "Você é um assistente que interpreta frases de agendamento em português e responde **somente** em JSON válido.\n"
            "Identifique:\n"
            "• Título (texto principal)\n"
            "• Data (AAAA-MM-DD ou 'hoje'/'amanhã')\n"
            "• Hora inicial ('HH:MM') — ou deixe vazio se não houver\n"
            "• Duração (em minutos)\n"
            "• Participantes (e-mails citados)\n"
            "• Descrição (detalhes extras)\n\n"
            "Formato JSON:\n"
            "{\n"
            '  "titulo": "texto",\n'
            '  "data": "AAAA-MM-DD ou hoje/amanhã",\n'
            '  "hora": "HH:MM ou vazio",\n'
            '  "duracao_min": número,\n'
            '  "participantes": [],\n'
            '  "descricao": ""\n'
            "}\n\n"
            f"Exemplos:\n{json.dumps(exemplos, ensure_ascii=False, indent=2)}\n\n"
            f"Agora processe esta frase:\n'{prompt}'"
        )

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "Responda apenas com JSON puro e válido, sem comentários."},
                {"role": "user", "content": prompt_base},
            ],
            "temperature": 0.1,
        }

        print(f"🧠 Enviando para IA → {prompt}")
        response = httpx.post("https://api.openai.com/v1/chat/completions", headers=headers, json=body, timeout=30)
        data = response.json()

        conteudo = data["choices"][0]["message"]["content"].strip()
        if conteudo.startswith("```"):
            conteudo = conteudo.replace("```json", "").replace("```", "").strip()

        parsed = json.loads(conteudo)

        # Corrige “hoje” / “amanhã”
        if parsed.get("data") == "hoje":
            parsed["data"] = hoje.strftime("%Y-%m-%d")
        elif parsed.get("data") in ("amanha", "amanhã"):
            parsed["data"] = (hoje + timedelta(days=1)).strftime("%Y-%m-%d")

        # 💌 Regra personalizada: "convide amor"
        if "convide amor" in prompt.lower():
            convidados = parsed.get("participantes", [])
            if "britto.marilia@gmail.com" not in convidados:
                convidados.append("britto.marilia@gmail.com")
            parsed["participantes"] = convidados

        # 🗓️ Se não houver data, define como hoje
        if not parsed.get("data"):
            parsed["data"] = hoje.strftime("%Y-%m-%d")

        # ⏰ Se não houver hora, trata como evento de dia inteiro
        if not parsed.get("hora"):
            parsed["hora"] = ""

        # 🎨 Detecta cor personalizada ou usa azul padrão
        cor_map = {
            "#azul": "1",
            "#roxo": "3",
            "#verde": "10",
            "#amarelo": "5",
            "#laranja": "6",
            "#rosa": "9",
            "#cinza": "8",
            "#vermelho": "11"
        }
        parsed["colorId"] = "1"  # padrão azul
        for tag, code in cor_map.items():
            if tag in prompt.lower():
                parsed["colorId"] = code
                break

        print("🧩 Saída final da IA:")
        print(json.dumps(parsed, indent=2, ensure_ascii=False))
        return parsed

    except Exception as e:
        print(f"❌ Erro ao interpretar prompt: {e}")
        raise


# ======================================================
# 📆 CRIAÇÃO DO EVENTO NO GOOGLE CALENDAR
# ======================================================
def criar_evento(titulo, data_inicio, hora_inicio, duracao_min, participantes, descricao, color_id=None):
    """Cria evento no Google Calendar (suporta cores e eventos de dia inteiro)"""
    fuso = pytz.timezone(TZ)
    hoje = datetime.now(fuso).date()

    if isinstance(data_inicio, str):
        if data_inicio.lower() == "hoje":
            data_inicio = hoje.strftime("%Y-%m-%d")
        elif data_inicio.lower() in ("amanha", "amanhã"):
            data_inicio = (hoje + timedelta(days=1)).strftime("%Y-%m-%d")

    service = get_calendar_service()

    # Evento de dia inteiro
    if not hora_inicio or str(hora_inicio).strip() == "":
        data_fim = (datetime.strptime(data_inicio, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        body = {
            "summary": titulo or "Evento",
            "description": descricao or "",
            "start": {"date": data_inicio},
            "end": {"date": data_fim},
            "attendees": [{"email": e} for e in (participantes or []) if "@" in e],
            "transparency": "opaque",
            "reminders": {"useDefault": False},
        }
        if color_id:
            body["colorId"] = color_id

        ev = service.events().insert(calendarId="primary", body=body).execute()
        print(f"✅ Evento de dia inteiro criado: {ev.get('htmlLink')}")
        return ev

    # Evento com hora definida
    inicio = fuso.localize(datetime.strptime(f"{data_inicio} {hora_inicio}", "%Y-%m-%d %H:%M"))
    fim = inicio + timedelta(minutes=int(duracao_min or 60))
    body = {
        "summary": titulo or "Evento",
        "description": descricao or "",
        "start": {"dateTime": inicio.isoformat(), "timeZone": TZ},
        "end": {"dateTime": fim.isoformat(), "timeZone": TZ},
        "attendees": [{"email": e} for e in (participantes or []) if "@" in e],
        "reminders": {"useDefault": True},
    }
    if color_id:
        body["colorId"] = color_id

    ev = service.events().insert(calendarId="primary", body=body).execute()
    print(f"✅ Evento criado: {ev.get('htmlLink')}")
    return ev
