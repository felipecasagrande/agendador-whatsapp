# -*- coding: utf-8 -*-
"""
app.py
Flask + Twilio WhatsApp + Google Calendar (Service Account)
Versão 2025 — compatível com Render
"""

import os
import json
from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse

# Google Calendar
from googleapiclient.discovery import build
from google.oauth2 import service_account

# Import local
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
    Lê as credenciais do Google de variável de ambiente (Render)
    ou do arquivo local credentials.json.
    """
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    elif os.path.exists("credentials.json"):
        creds = service_account.Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    else:
        raise FileNotFoundError("⚠️ Nenhum credentials.json encontrado nem GOOGLE_CREDENTIALS_JSON definido.")
    return creds

# Inicializa o serviço do Calendar
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
# 💬 WEBHOOK WHATSAPP (Twilio)
# ==============================
@app.route("/whats", methods=["POST"])
def whats():
    """
    Recebe mensagem do WhatsApp (via Twilio)
    → interpreta o texto
    → cria evento no Google Calendar
    → responde ao usuário
    """
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

        # 3️⃣ Enviar resposta ao WhatsApp
        resposta.message(resultado)
        xml = str(resposta)

        # ⚠️ IMPORTANTE — Twilio exige XML com MIME correto
        return Response(xml, mimetype="text/xml")

    except Exception as e:
        erro_txt = f"❌ Erro ao criar evento: {e}"
        print(f"🔴 {erro_txt}")
        resposta.message(erro_txt)
        return Response(str(resposta), mimetype="text/xml")


# ==============================
# 🚀 EXECUÇÃO LOCAL (debug)
# ==============================
if __name__ == "__main__":
    porta = int(os.getenv("PORT", 10000))
    print(f"🚀 Executando localmente em http://127.0.0.1:{porta}")
    app.run(host="0.0.0.0", port=porta)
