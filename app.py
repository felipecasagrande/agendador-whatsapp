import os
import json
import logging
from flask import Flask, request, abort
from twilio.twiml.messaging_response import MessagingResponse
from twilio.request_validator import RequestValidator
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

from agendar_por_prompt import interpretar_prompt, criar_evento

# ======================================================
# 🔧 CONFIGURAÇÃO INICIAL
# ======================================================
load_dotenv()
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# ======================================================
# 🔐 TWILIO CONFIG
# ======================================================
ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATS_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")
ALLOW_LIST = set(filter(None, [n.strip() for n in os.getenv("ALLOW_LIST", "").split(",")]))
validator = RequestValidator(AUTH_TOKEN) if AUTH_TOKEN else None


def _validate_twilio_signature():
    """Valida a assinatura da Twilio"""
    if not validator:
        return
    sig = request.headers.get("X-Twilio-Signature", "")
    if not validator.validate(request.url, request.form.to_dict(), sig):
        abort(403)


@app.post("/whats")
def whats():
    """Recebe mensagem e agenda no Calendar"""
    _validate_twilio_signature()

    body = (request.form.get("Body") or "").strip()
    from_number = (request.form.get("From") or "").replace("whatsapp:", "")
    msg_sid = request.form.get("MessageSid")

    resp = MessagingResponse()

    if body.lower() in {"ajuda", "help", "menu"}:
        resp.message(
            "📅 *Agendador WhatsApp*\n"
            "Envie frases como:\n"
            "• reunião com João amanhã às 14h\n"
            "• jantar com Maria hoje às 20h\n"
            "• comprar pão amanhã\n\n"
            "O evento será criado no seu Google Calendar ✅"
        )
        return str(resp)

    try:
        parsed = interpretar_prompt(body)
        ev = criar_evento(
            titulo=parsed.get("titulo"),
            data_inicio=parsed.get("data"),
            hora_inicio=parsed.get("hora"),
            duracao_min=parsed.get("duracao_min", 60),
            participantes=parsed.get("participantes", []),
            descricao=parsed.get("descricao", ""),
            colorId=parsed.get("colorId", "9")
        )

        evento_url = ev.get("htmlLink", "")
        resp.message(f"✅ *Evento criado!*\n{parsed.get('titulo')}\n{parsed.get('data')} {parsed.get('hora')}\n🔗 {evento_url}")
        return str(resp)

    except Exception as e:
        app.logger.exception("Erro ao processar mensagem: %s", e)
        resp.message("❌ Não consegui agendar. Tente: 'reunião com João amanhã às 10h30'.")
        return str(resp)


@app.get("/")
def root():
    return ("", 204)


def notify_live():
    """Envia e-mail quando o servidor estiver online"""
    try:
        sender = os.getenv("SMTP_USER", "felipecasagrandematos@gmail.com")
        password = os.getenv("SMTP_PASS", "")
        recipient = "felipecasagrandematos@gmail.com"

        msg = MIMEMultipart()
        msg["From"] = sender
        msg["To"] = recipient
        msg["Subject"] = "✅ Servidor Agendador WhatsApp está online!"
        body = f"Deploy ativo em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}.\n\nURL: https://agendador-whatsapp.onrender.com"
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)

        print("📨 E-mail enviado confirmando servidor live!")
    except Exception as e:
        print(f"⚠️ Falha ao enviar notificação: {e}")


if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    notify_live()
    app.run(host="0.0.0.0", port=port, debug=True)
