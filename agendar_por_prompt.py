# -*- coding: utf-8 -*-
"""
agendar_por_prompt.py
Camada de domínio: interpretar mensagem em PT-BR e criar eventos no Google Calendar.
"""

import os
import json
import re
import pytz
import httpx
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from google.oauth2 import service_account

# ======================================================
# 🔧 CONFIGURAÇÕES GERAIS
# ======================================================
SCOPES = ["https://www.googleapis.com/auth/calendar"]
TZ = "America/Sao_Paulo"


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
        ]

        prompt_base = (
            "Você é um assistente que interpreta frases de agendamento em português e responde SOMENTE em JSON válido.\n"
            "Identifique: título, data (AAAA-MM-DD ou 'hoje'/'amanhã'), hora ('HH:MM'), duração (em minutos), participantes, descrição e colorId.\n\n"
            "Formato JSON:\n"
            "{\n"
            '  "titulo": "texto",\n'
            '  "data": "AAAA-MM-DD ou hoje/amanhã",\n'
            '  "hora": "HH:MM ou vazio",\n'
            '  "duracao_min": número,\n'
            '  "participantes": [],\n'
            '  "descricao": "",\n'
            '  "colorId": "9"\n'
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

        print("🧩 Saída final da IA:")
        print(json.dumps(parsed, indent=2, ensure_ascii=False))
        return parsed

    except Exception as e:
        print(f"❌ Erro ao interpretar prompt: {e}")
        raise


# ======================================================
# 🔐 GOOGLE CALENDAR SERVICE ACCOUNT (com correção Render)
# ======================================================
def get_calendar_service():
    """Autentica via Service Account (sem token.json), corrigindo escapes do Render"""
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        raise ValueError("❌ GOOGLE_CREDENTIALS_JSON ausente no ambiente.")

    # ✅ Corrige quebras e escapes incorretos vindos do painel do Render
    cleaned = re.sub(r'(?<!\\)\\(?![\\n"])', r"\\\\", creds_json)
    cleaned = cleaned.replace("\\n", "\n")

    creds = service_account.Credentials.from_service_account_info(
        json.loads(cleaned),
        scopes=SCOPES
    )
    return build("calendar", "v3", credentials=creds)


# ======================================================
# 📅 CRIAÇÃO DE EVENTO
# ======================================================
def criar_evento(titulo, data_inicio, hora_inicio, duracao_min, participantes, descricao, colorId="9"):
    """Cria evento no Google Calendar"""
    service = get_calendar_service()
    fuso = pytz.timezone(TZ)
    hoje = datetime.now(fuso).date()

    # Converte “hoje” e “amanhã”
    if isinstance(data_inicio, str):
        if data_inicio.lower() == "hoje":
            data_inicio = hoje.strftime("%Y-%m-%d")
        elif data_inicio.lower() in ("amanha", "amanhã"):
            data_inicio = (hoje + timedelta(days=1)).strftime("%Y-%m-%d")

    # Evento de dia inteiro
    if not hora_inicio or str(hora_inicio).strip() == "":
        data_fim = (datetime.strptime(data_inicio, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        body = {
            "summary": titulo or "Evento",
            "description": descricao or "",
            "start": {"date": data_inicio},
            "end": {"date": data_fim},
            "attendees": [{"email": e} for e in (participantes or []) if "@" in e],
            "colorId": colorId,
            "reminders": {"useDefault": False},
        }
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
        "colorId": colorId,
        "reminders": {"useDefault": True},
    }
    ev = service.events().insert(calendarId="primary", body=body).execute()
    print(f"✅ Evento com hora criado: {ev.get('htmlLink')}")
    return ev
