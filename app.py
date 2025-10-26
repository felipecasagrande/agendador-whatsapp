# -*- coding: utf-8 -*-
"""
app.py
Flask + Twilio webhook para WhatsApp.

- Endpoint GET "/"  -> healthcheck
- Endpoint POST "/whats" -> recebe Body do WhatsApp, interpreta e agenda no Google Calendar
- Credenciais do Google:
    • Preferência por variáveis de ambiente GOOGLE_CREDENTIALS_JSON e GOOGLE_TOKEN_JSON
    • Se não existirem, usa "credentials.json" / "token.json" locais
"""

import os
import json
from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse

# Google Calendar
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from agendador_whatsapp import interpretar_mensagem, criar_evento_google_calendar

SCOPES = ["https://www.googleapis.com/auth/calendar"]

app = Flask(__name__)


# -------------------- GOOGLE AUTH HELPERS --------------------

def _write_google_files_from_env():
    """
    Se vierem os JSONs em env vars, persiste como arquivos para a lib do Google usar.
    """
    creds_txt = os.getenv("GOOGLE_CREDENTIALS_JSON")
    token_txt = os.getenv("GOOGLE_TOKEN_JSON")

    if creds_txt and not os.path.exists("credentials.json"):
        with open("credentials.json", "w", encoding="utf-8") as f:
            f.write(creds_txt)

    if token_txt and not os.path.exists("token.json"):
        with open("token.json", "w", encoding="utf-8") as f:
            f.write(token_txt)


def get_calendar_service():
    """
    Cria o 'service' do Calendar v3.
    Suporta dois caminhos:
      1) Token/credentials já persistidos (token.json/credentials.json)
      2) Primeiro uso local -> abre fluxo interativo (apenas ambiente dev)
    Em produção, prefira setar GOOGLE_CREDENTIALS_JSON e GOOGLE_TOKEN_JSON.
    """
    _write_google_files_from_env()

    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists("credentials.json"):
                raise RuntimeError(
                    "Credenciais ausentes. Defina GOOGLE_CREDENTIALS_JSON/GOOGLE_TOKEN_JSON "
                    "ou forneça credentials.json/token.json."
                )
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
            with open("token.json", "w", encoding="utf-8") as token:
                token.write(creds.to_json())

    service = build("calendar", "v3", credentials=creds)
    return service


# ------------------------- ROUTES ----------------------------

@app.route("/", methods=["GET"])
def root():
    return Response("OK", status=200, mimetype="text/plain")


@app.route("/whats", methods=["POST"])
def whats():
    """
    Webhook do Twilio WhatsApp.
    Espera 'Body' com o texto da mensagem.
    Retorna TwiML com a resposta do agendamento.
    """
    body = (request.values.get("Body") or "").strip()
    sender = request.values.get("From", "")

    print(f"📥 WhatsApp de {sender}: {body}")

    if not body:
        resp = MessagingResponse()
        resp.message("❌ Mensagem vazia. Envie algo como: 'reunião amanhã às 10h30' ou 'comprar cápsula hoje'.")
        return str(resp)

    # Interpreta a frase (parser local)
    parsed = interpretar_mensagem(body)
    print("🧠 Interpretado:", json.dumps(parsed, ensure_ascii=False))

    try:
        service = get_calendar_service()
    except Exception as e:
        print(f"🔴 Erro ao autenticar no Google: {e}")
        resp = MessagingResponse()
        resp.message("❌ Falha ao conectar no Google Calendar. Verifique as credenciais.")
        return str(resp)

    try:
        resultado = criar_evento_google_calendar(service, parsed)
        print("✅ Resultado:", resultado)
    except Exception as e:
        print(f"🔴 Erro ao criar evento: {e}")
        resultado = "❌ Não consegui agendar. Exemplo: 'reunião com João amanhã às 10h30'."

    resp = MessagingResponse()
    resp.message(resultado)
    return str(resp)


if __name__ == "__main__":
    # Para rodar localmente: python app.py
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=True)
