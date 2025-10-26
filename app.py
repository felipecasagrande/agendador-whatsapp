# -*- coding: utf-8 -*-
"""
app.py
Flask + Twilio WhatsApp + Google Calendar (Service Account)

✅ Funções:
- Recebe mensagens do WhatsApp (via Twilio)
- Interpreta o conteúdo em linguagem natural
- Cria eventos no Google Calendar (conta de serviço)
- Responde automaticamente pelo WhatsApp com o resultado

Autor: Mickaio / versão Render 2025
"""

import os
import json
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# Google Calendar
from googleapiclient.discovery import build
from google.oauth2 import service_account

# Import do interpretador e criador de evento
from agendador_whatsapp import interpretar_mensagem, criar_evento_google_calendar

# ==============================
# ⚙️ CONFIGURAÇÃO DO FLASK
# ==============================
app = Flask(__name__)

# ==============================
# 🔑 GOOGLE CALENDAR AUTH
# ==============================
SCOPES = ["https://www.googleapis.com/auth/calendar"]

def carregar_credenciais():
    """
    Lê as credenciais do Google do Render (env GOOGLE_CREDENTIALS_JSON)
    ou de um arquivo local credentials.json.
    """
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        if not os.path.exists("credentials.json"):
            raise FileNotFoundError("⚠️ Nenhum credentials.json encontrado e GOOGLE_CREDENTIALS_JSON não definido.")
        creds = service_account.Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    return creds

# Carrega o serviço global (ao iniciar o app)
try:
    CREDS = carregar_credenciais()
    service = build("calendar", "v3", credentials=CREDS)
    print("✅ Google Calendar autenticado com sucesso.")
except Exception as e:
    service = None
    print(f"🔴 Falha ao autenticar Google Calendar: {e}")

# ==============================
# 🌐 ROTA PRINCIPAL (healthcheck)
# ==============================
@app.route("/", methods=["GET"])
def home():
    return "✅ Agendador WhatsApp ativo", 200

# ==============================
# 💬 ROTA WHATSAPP (Twilio Webhook)
# ==============================
@app.route("/whats", methods=["POST"])
def whats():
    """
    Recebe mensagem do WhatsApp via Twilio e cria evento no Google Calendar.
    """
    msg = request.form.get("Body", "").strip()
    sender = request.form.get("From", "")
    print(f"📩 Mensagem de {sender}: {msg}")

    resp = MessagingResponse()

    try:
        if not service:
            raise Exception("Google Calendar não autenticado.")

        # 1️⃣ Interpreta mensagem
        parsed = interpretar_mensagem(msg)
        print(f"🧠 Interpretado: {parsed}")

        # 2️⃣ Cria evento no Google Calendar
        resultado = criar_evento_google_calendar(service, parsed)
        print(f"✅ Resultado: {resultado}")

        # 3️⃣ Responde via WhatsApp
        resp.message(resultado)
        return str(resp)

    except Exception as e:
        erro_txt = f"❌ Erro ao criar evento: {e}"
        print(f"🔴 {erro_txt}")
        resp.message(erro_txt)
        return str(resp)


# ==============================
# 🚀 EXECUÇÃO LOCAL (debug)
# ==============================
if __name__ == "__main__":
    porta = int(os.getenv("PORT", 10000))
    print(f"🚀 Executando localmente em http://127.0.0.1:{porta}")
    app.run(host="0.0.0.0", port=porta)
