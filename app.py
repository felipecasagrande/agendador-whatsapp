# -*- coding: utf-8 -*-
"""
app.py
Flask + WhatsApp Cloud API (Meta) + Google Calendar (Service Account)

Rotas:
- GET /webhook   -> verificação do webhook (Meta)
- POST /webhook  -> recebe mensagens e responde
- GET /          -> healthcheck

Env vars necessárias (Render):
- META_VERIFY_TOKEN
- META_ACCESS_TOKEN
- PHONE_NUMBER_ID
- CALENDAR_ID                       (seu calendário alvo, ex: felipecasagrandematos@gmail.com)
- GOOGLE_CREDENTIALS_JSON           (conteúdo JSON da service account)
- TZ                                (opcional, default America/Sao_Paulo)
"""

import os
import json
import requests
from flask import Flask, request, jsonify, Response

from googleapiclient.discovery import build
from google.oauth2 import service_account

from agendador_whatsapp import interpretar_mensagem, criar_evento_google_calendar, build_tz

app = Flask(__name__)

# ------------- Config Meta (WhatsApp Cloud API) -------------
META_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "troque-este-token")
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
PHONE_NUMBER_ID   = os.getenv("PHONE_NUMBER_ID", "")  # ex: "123456789012345"

# ------------- Config Google Calendar -----------------------
SCOPES = ["https://www.googleapis.com/auth/calendar"]
CALENDAR_ID = os.getenv("CALENDAR_ID", "")             # e-mail do calendário alvo
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "")

# ------------- Timezone -------------------------------------
TZ = build_tz(os.getenv("TZ", "America/Sao_Paulo"))

# ------------- Calendar Service (lazy) ----------------------
_calendar_service = None
def get_calendar_service():
    global _calendar_service
    if _calendar_service:
        return _calendar_service
    if not GOOGLE_CREDENTIALS_JSON:
        raise RuntimeError("GOOGLE_CREDENTIALS_JSON não definido.")
    info = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    _calendar_service = build("calendar", "v3", credentials=creds)
    print("✅ Google Calendar autenticado com sucesso.")
    return _calendar_service


# ------------- Healthcheck ----------------------------------
@app.route("/", methods=["GET"])
def root():
    return "✅ Agendador WhatsApp ativo", 200


# ------------- Webhook Verification (GET) -------------------
@app.route("/webhook", methods=["GET"])
def verify():
    """
    Meta chama GET na validação do webhook:
      /webhook?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...
    Devemos retornar o hub.challenge quando o verify_token bate.
    """
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == META_VERIFY_TOKEN:
        print("✅ Webhook verificado pela Meta.")
        return Response(challenge, status=200, mimetype="text/plain")
    else:
        print("🔴 Falha na verificação de webhook.")
        return Response("forbidden", status=403, mimetype="text/plain")


# ------------- Webhook Receiver (POST) ----------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Recebe mensagens do WhatsApp Cloud API.
    Responde com texto de confirmação depois de criar o evento.
    """
    payload = request.get_json(force=True, silent=True) or {}
    # Meta exige 200 rápido:
    # vamos processar inline (simples) – para alto volume, mover para fila.
    try:
        entries = payload.get("entry", [])
        for entry in entries:
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])
                for msg in messages:
                    # Apenas texto
                    if msg.get("type") != "text":
                        continue

                    wa_text  = (msg.get("text") or {}).get("body", "").strip()
                    wa_from  = msg.get("from")  # ex: "5531984478737"
                    print(f"📩 WhatsApp de {wa_from}: {wa_text}")

                    # 1) Interpretar
                    parsed = interpretar_mensagem(wa_text, tz=TZ)
                    print(f"🧠 Interpretado: {parsed}")

                    # 2) Criar evento
                    if not CALENDAR_ID:
                        resultado = "❌ Falta configurar CALENDAR_ID."
                    else:
                        service = get_calendar_service()
                        resultado = criar_evento_google_calendar(service, parsed, calendar_id=CALENDAR_ID, tz=TZ)
                    print(f"✅ Resultado: {resultado}")

                    # 3) Responder no WhatsApp
                    send_whatsapp_text(wa_to=wa_from, text=resultado)

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print(f"🔴 Erro no webhook: {e}")
        return jsonify({"status": "error"}), 200  # sempre 200 p/ Meta não re-tentar infinitamente


# ------------- Envio de mensagens (Meta) --------------------
def send_whatsapp_text(wa_to: str, text: str):
    """
    Envia texto usando a API de mensagens da Meta.
    wa_to: número no formato internacional sem '+', ex: '5531984478737'
    """
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    body = {
        "messaging_product": "whatsapp",
        "to": wa_to,
        "type": "text",
        "text": {"body": text}
    }
    r = requests.post(url, headers=headers, json=body, timeout=10)
    if r.status_code >= 300:
        print(f"🔴 Falha ao enviar WhatsApp: {r.status_code} - {r.text}")
    else:
        print("📤 Resposta enviada ao WhatsApp.")


# ------------- Execução local --------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
