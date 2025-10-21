import os
import re
import json
import pytz
import httpx
import calendar
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
    """Cria arquivos de credenciais a partir das variáveis do ambiente (Render)"""
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
# 🧩 INTERPRETAÇÃO DE DATAS SIMPLES (fallback local)
# ======================================================
def interpretar_data_local(prompt: str) -> str | None:
    """Tenta identificar datas simples no texto, como:
    - 'fim do mês'
    - 'amanhã'
    - 'dia 25'
    - 'dia 25 de outubro de 2025'
    Retorna uma string no formato YYYY-MM-DD
    """
    tz = pytz.timezone(TZ)
    hoje = datetime.now(tz)
    texto = prompt.lower().strip()

    # "amanhã"
    if "amanhã" in texto or "amanha" in texto:
        return (hoje + timedelta(days=1)).strftime("%Y-%m-%d")

    # "depois de amanhã"
    if "depois de amanhã" in texto:
        return (hoje + timedelta(days=2)).strftime("%Y-%m-%d")

    # "fim do mês" ou "último dia do mês"
    if "fim do mês" in texto or "último dia do mês" in texto:
        ultimo_dia = calendar.monthrange(hoje.year, hoje.month)[1]
        return hoje.replace(day=ultimo_dia).strftime("%Y-%m-%d")

    # "dia 25"
    m_dia = re.search(r"dia\s*(\d{1,2})", texto)
    if m_dia:
        dia = int(m_dia.group(1))
        # detecta mês opcional
        meses = {
            "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4, "maio": 5, "junho": 6,
            "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12
        }
        m_mes = re.search(r"de\s*(janeiro|fevereiro|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)", texto)
        mes = meses[m_mes.group(1)] if m_mes else hoje.month
        m_ano = re.search(r"(\d{4})", texto)
        ano = int(m_ano.group(1)) if m_ano else hoje.year
        try:
            return datetime(ano, mes, dia).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return None


# ======================================================
# 🧠 INTERPRETAÇÃO DE TEXTO (IA OpenAI + fallback local)
# ======================================================
def interpretar_prompt(prompt: str):
    """
    Usa GPT-4o-mini para interpretar frases e retornar:
    titulo, data, hora, duracao_min, participantes, descricao
    """
    tz = pytz.timezone(TZ)
    hoje = datetime.now(tz).date()
    data_local = interpretar_data_local(prompt)

    try:
        token = os.getenv("OPENAI_TOKEN", "").strip()
        if not token:
            raise ValueError("OPENAI_TOKEN ausente no ambiente.")
        print(f"✅ Token OpenAI ativo (prefixo): {token[:10]}...")

        exemplos = [
            {"input": "reunião com João amanhã às 10h30",
             "output": {"titulo": "Reunião com João", "data": "amanhã", "hora": "10:30"}},
            {"input": "dentista dia 25 de outubro de 2025",
             "output": {"titulo": "Dentista", "data": "2025-10-25", "hora": ""}},
            {"input": "reunião fim do mês",
             "output": {"titulo": "Reunião", "data": "fim do mês", "hora": ""}},
            {"input": "❤️⏳🏠 às 21h25 convidar britto.marilia@gmail.com",
             "output": {"titulo": "❤️⏳🏠", "data": "hoje", "hora": "21:25", "participantes": ["britto.marilia@gmail.com"]}}
        ]

        prompt_base = (
            "Você é um assistente que interpreta frases de agendamento em português e responde **somente** em JSON válido.\n"
            "Identifique:\n"
            "• Título\n"
            "• Data (AAAA-MM-DD ou 'hoje'/'amanhã')\n"
            "• Hora inicial ('HH:MM')\n"
            "• Duração (em minutos)\n"
            "• Participantes (e-mails citados)\n"
            "• Descrição (detalhes extras)\n\n"
            "Formato JSON:\n"
            "{ 'titulo': 'texto', 'data': 'AAAA-MM-DD', 'hora': 'HH:MM', 'duracao_min': número, 'participantes': [], 'descricao': '' }\n\n"
            f"Exemplos:\n{json.dumps(exemplos, ensure_ascii=False, indent=2)}\n\n"
            f"Agora processe esta frase:\n'{prompt}'"
        )

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "Responda apenas com JSON puro e válido."},
                {"role": "user", "content": prompt_base},
            ],
            "temperature": 0.1,
        }

        print(f"🧠 Interpretando prompt → {prompt}")
        response = httpx.post("https://api.openai.com/v1/chat/completions", headers=headers, json=body, timeout=30)
        data = response.json()
        conteudo = data["choices"][0]["message"]["content"].strip()

        if conteudo.startswith("```"):
            conteudo = conteudo.replace("```json", "").replace("```", "").strip()

        parsed = json.loads(conteudo)

        # Ajusta “hoje” / “amanhã”
        if parsed.get("data") == "hoje":
            parsed["data"] = hoje.strftime("%Y-%m-%d")
        elif parsed.get("data") in ("amanha", "amanhã"):
            parsed["data"] = (hoje + timedelta(days=1)).strftime("%Y-%m-%d")
        elif parsed.get("data") in ("fim do mês", "último dia do mês"):
            ultimo_dia = calendar.monthrange(hoje.year, hoje.month)[1]
            parsed["data"] = datetime(hoje.year, hoje.month, ultimo_dia).strftime("%Y-%m-%d")

        # Se IA não entendeu, usa fallback local
        if not parsed.get("data") and data_local:
            parsed["data"] = data_local

        # Reconhece apelidos de convidados
        if "participantes" in parsed:
            convites = []
            for p in parsed["participantes"]:
                if p.lower() in ("amor", "marilia"):
                    convites.append("britto.marilia@gmail.com")
                elif "@" in p:
                    convites.append(p)
            parsed["participantes"] = convites

        print("🧩 Resultado final da IA:")
        print(json.dumps(parsed, indent=2, ensure_ascii=False))
        return parsed

    except Exception as e:
        print(f"⚠️ Falha ao interpretar via OpenAI: {e}")
        # Fallback simples
        return {
            "titulo": prompt.title(),
            "data": data_local or hoje.strftime("%Y-%m-%d"),
            "hora": "",
            "duracao_min": 60,
            "participantes": [],
            "descricao": "",
        }


# ======================================================
# 📆 CRIAÇÃO DO EVENTO NO GOOGLE CALENDAR
# ======================================================
def criar_evento(titulo, data_inicio, hora_inicio, duracao_min, participantes, descricao):
    """Cria evento no Google Calendar"""
    fuso = pytz.timezone(TZ)
    hoje = datetime.now(fuso).date()

    # Corrige “hoje” / “amanhã”
    if isinstance(data_inicio, str):
        if data_inicio.lower() == "hoje":
            data_inicio = hoje.strftime("%Y-%m-%d")
        elif data_inicio.lower() in ("amanha", "amanhã"):
            data_inicio = (hoje + timedelta(days=1)).strftime("%Y-%m-%d")

    service = get_calendar_service()

    if not hora_inicio:
        data_fim = (datetime.strptime(data_inicio, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        body = {
            "summary": titulo or "Evento",
            "description": descricao or "",
            "start": {"date": data_inicio},
            "end": {"date": data_fim},
            "attendees": [{"email": e} for e in (participantes or []) if "@" in e],
            "reminders": {"useDefault": False},
        }
        ev = service.events().insert(calendarId="primary", body=body).execute()
        print(f"✅ Evento de dia inteiro criado: {ev.get('htmlLink')}")
        return ev

    # Evento com hora
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
    ev = service.events().insert(calendarId="primary", body=body).execute()
    print(f"✅ Evento com hora criado: {ev.get('htmlLink')}")
    return ev
