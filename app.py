# -*- coding: utf-8 -*-
"""
app.py
Flask + UltraMsg + Google Calendar (Service Account)
✅ Corrigido para evitar loops e limitar mensagens ao número autorizado
"""

import os
import json
import requests
from flask import Flask, request, jsonify

from googleapiclient.discovery import build
from google.oauth2 import service_account

from agendador_whatsapp import interpretar_mensagem, criar_evento_google_calendar, build_tz

app = Flask(__name__)

# -------------------- Config --------------------
ULTRAMSG_INSTANCE_ID = os.getenv("ULTRAMSG_INSTANCE_ID")
ULTRAMSG_TOKEN = os.getenv("ULTRAMSG_TOKEN")
CALENDAR_ID = os.getenv("CALENDAR_ID")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")
TZ = build_tz(os.getenv("TZ", "America/Sao_Paulo"))

SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Somente mensagens deste número serão aceitas
NUMERO_AUTORIZADO = "5531984478737"  # sem o "+"


# -------------------- Calendar Service --------------------
_calendar_service = None
def get_calendar_service():
    global _calendar_service
    if _calendar_service:
        return _calendar_service
    info = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    _calendar_service = build("calendar", "v3", credentials=creds)
    print("✅ Google Calendar autenticado.")
    return _calendar_service


# -------------------- Healthcheck --------------------
@app.route("/", methods=["GET"])
def root():
    return "✅ Agendador WhatsApp ativo (UltraMsg filtrado)", 200


# -------------------- Webhook UltraMsg --------------------
@app.route("/webhook", methods=["POST"])
def webhook_ultramsg():
    """
    Recebe mensagens do UltraMsg e cria eventos APENAS se vierem do seu número pessoal.
    Exemplo de payload:
    {
      "data": {
        "from": "5531984478737",
        "fromMe": false,
        "body": "comprar café amanhã às 11h"
      }
    }
    """
    try:
        payload = request.get_json(force=True, silent=True) or {}
        data = payload.get("data") or {}

        wa_from = data.get("from", "").strip()
        wa_text = (data.get("body") or "").strip()
        is_from_me = data.get("fromMe", False)

        # 🚫 Ignorar mensagens que não são do número autorizado
        if wa_from != NUMERO_AUTORIZADO:
            print(f"🚫 Ignorado: mensagem de {wa_from}")
            return jsonify({"status": "ignored"}), 200

        # 🚫 Ignorar mensagens enviadas pelo próprio bot ou sem texto
        if is_from_me or not wa_text:
            print(f"🔁 Ignorado (fromMe ou sem texto): {wa_text}")
            return jsonify({"status": "ignored"}), 200

        print(f"📩 Mensagem autorizada de {wa_from}: {wa_text}")

        # 1️⃣ Interpretar texto
        parsed = interpretar_mensagem(wa_text, tz=TZ)
        print(f"🧠 Interpretado: {parsed}")

        # 2️⃣ Criar evento no Calendar
        service = get_calendar_service()
        resultado = criar_evento_google_calendar(service, parsed, calendar_id=CALENDAR_ID, tz=TZ)
        print(f"✅ Resultado: {resultado}")

        # 3️⃣ Responder via UltraMsg
        send_ultramsg_message(wa_from, resultado)

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print(f"🔴 Erro no webhook: {e}")
        return jsonify({"status": "error", "detail": str(e)}), 200


# -------------------- Envio de mensagem UltraMsg --------------------
def send_ultramsg_message(to_number: str, message: str):
    """
    Envia mensagem via UltraMsg API.
    """
    try:
        url = f"https://api.ultramsg.com/{ULTRAMSG_INSTANCE_ID}/messages/chat"
        data = {
            "token": ULTRAMSG_TOKEN,
            "to": f"+{to_number}" if not str(to_number).startswith("+") else to_number,
            "body": message
        }
        r = requests.post(url, data=data, timeout=10)
        print(f"📤 Enviado para {to_number} → {r.status_code}: {r.text}")
    except Exception as e:
        print(f"🔴 Falha ao enviar resposta: {e}")


# -------------------- Execução local --------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
