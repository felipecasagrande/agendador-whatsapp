# -*- coding: utf-8 -*-
"""
app.py
Flask + Twilio WhatsApp + Google Calendar (Service Account).
Totalmente automatizado para ambiente Render.
"""

import os
import json
from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse
from googleapiclient.discovery import build
from google.oauth2 import service_account

from agendador_whatsapp import interpretar_mensagem, criar_evento_google_calendar

SCOPES = ["https://www.googleapis.com/auth/calendar"]
app = Flask(__name__)


# -------------------- GOOGLE AUTH --------------------

def get_calendar_service():
    """
    Autentica via conta de serviço (service_account).
    Lê o JSON da env var GOOGLE_CREDENTIALS_JSON.
    """
    creds_txt = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not creds_txt:
        raise RuntimeError("❌ Variável GOOGLE_CREDENTIALS_JSON não definida.")

    # Garante que o arquivo exista no container
    if not os.path.exists("credentials.json"):
        with open("credentials.json", "w", encoding="utf-8") as f:
            f.write(creds_txt)

    creds = service_account.Credentials.from_service_account_file(
        "credentials.json",
        scopes=SCOPES
    )

    service = build("calendar", "v3", credentials=creds)
    return service


# -------------------- ROTAS --------------------

@app.route("/", methods=["GET"])
def root():
    return Response("✅ Serviço ativo.", status=200, mimetype="text/plain")


@app.route("/whats", methods=["POST"])
def whats():
    """
    Webhook do Twilio WhatsApp.
    """
    body = (request.values.get("Body") or "").strip()
    sender = request.values.get("From", "")
    print(f"📩 Mensagem de {sender}: {body}")

    resp = MessagingResponse()

    if not body:
        resp.message("❌ Mensagem vazia. Exemplo: 'reunião amanhã às 10h30'")
        return str(resp)

    parsed = interpretar_mensagem(body)
    print("🧠 Interpretado:", json.dumps(parsed, ensure_ascii=False))

    try:
        service = get_calendar_service()
        resultado = criar_evento_google_calendar(service, parsed)
        print("✅ Resultado:", resultado)
        resp.message(resultado)
    except Exception as e:
        print(f"🔴 Erro: {e}")
        resp.message("❌ Falha ao criar evento no Google Calendar. Verifique as credenciais ou permissões.")

    return str(resp)


if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
