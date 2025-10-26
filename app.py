# -*- coding: utf-8 -*-
"""
app.py
Flask + Twilio WhatsApp + Google Calendar (Service Account)
Versão 2025 – Resposta garantida via Twilio
"""

import os
import json
from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse

# Google Calendar
from googleapiclient.discovery import build
from google.oauth2 import service_account

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
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    elif os.path.exists("credentials.json"):
        creds = service_account.Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    else:
        raise FileNotFoundError("⚠️ Credenciais Google não encontradas.")
    return creds


try:
    CREDS = carregar_credenciais()
    service = build("calendar", "v3", credentials=CREDS)
    print("✅ Google Calendar autenticado com sucesso.")
except Exception as e:
    service = None
    print(f"🔴 Falha ao autenticar Google Calendar: {e}")

# ==============================
# 🌐 HEALTHCHECK
# ==============================
@app.route("/", methods=["GET"])
def home():
    return "✅ Agendador WhatsApp ativo", 200

# ==============================
# 💬 WEBHOOK WHATSAPP
# ==============================
@app.route("/whats", methods=["POST"])
def whats():
    msg = request.form.get("Body", "").strip()
    sender = request.form.get("From", "")
    print(f"📩 Mensagem de {sender}: {msg}")

    resposta = MessagingResponse()

    try:
        if not service:
            raise Exception("Google Calendar não autenticado.")

        # 1️⃣ Interpretar mensagem
        parsed = interpretar_mensagem(msg)
        print(f"🧠 Interpretado: {parsed}")

        # 2️⃣ Criar evento
        resultado = criar_evento_google_calendar(service, parsed)
        print(f"✅ Resultado: {resultado}")

        # 3️⃣ Resposta WhatsApp
        resposta.message(resultado)
        xml = str(resposta)

        # ⚠️ IMPORTANTE: retornar com MIME correto (Twilio exige text/xml)
        return Response(xml, mimetype="text/xml")

    except Exception as e:
        erro_txt = f"❌ Erro ao criar evento: {e}"
        print(f"🔴 {erro_txt}")
        resposta.message(erro_txt)
        return Response(str(resposta), mimetype="text/xml")

# ==============================
# 🚀 EXECUÇÃO LOCAL
# ==============================
if __name__ == "__main__":
    porta = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=porta)
