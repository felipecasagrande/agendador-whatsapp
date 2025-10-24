# -*- coding: utf-8 -*-
import os
import json
import logging
from dotenv import load_dotenv
from flask import Flask, request, abort
from twilio.twiml.messaging_response import MessagingResponse
from twilio.request_validator import RequestValidator
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Funções principais
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
TWILIO_WHATS_NUMBER = os.getenv("TWILIO_WHATS_NUMBER", "whatsapp:+14155238886")
ALLOW_LIST = set(filter(None, [n.strip() for n in os.getenv("ALLOW_LIST", "").split(",")]))
validator = RequestValidator(AUTH_TOKEN) if AUTH_TOKEN else None


# ======================================================
# 🧾 VALIDAÇÃO DE SEGURANÇA
# ======================================================
def _validate_twilio_signature():
    if not validator:
        app.logger.warning("Validator desabilitado (AUTH_TOKEN ausente).")
        return
    sig = request.headers.get("X-Twilio-Signature", "")
    if not validator.validate(request.url, request.form.to_dict(), sig):
        abort(403)


# ======================================================
# 📅 FORMATAÇÃO LEGÍVEL
# ======================================================
def formatar_data_legivel(data_str):
    hoje = datetime.now().date()
    data = datetime.strptime(data_str, "%Y-%m-%d").date()
    diff = (data - hoje).days
    if diff == 0:
        return "hoje"
    elif diff == 1:
        return "amanhã"

    meses = [
        "janeiro", "fevereiro", "março", "abril", "maio", "junho",
        "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"
    ]
    dias_semana = [
        "segunda-feira", "terça-feira", "quarta-feira",
        "quinta-feira", "sexta-feira", "sábado", "domingo"
    ]
    return f"{data.day} de {meses[data.month - 1]} de {data.year} ({dias_semana[data.weekday()]})"


# ======================================================
# 💬 ENDPOINT PRINCIPAL - WHATSAPP
# ======================================================
@app.post("/whats")
def whats():
    _validate_twilio_signature()
    body = (request.form.get("Body") or "").strip()
    from_number = (request.form.get("From") or "").replace("whatsapp:", "")
    msg_sid = request.form.get("MessageSid")
    cache_key = os.path.join("/tmp", f"msg_{msg_sid}") if msg_sid else None

    if cache_key and os.path.exists(cache_key):
        resp = MessagingResponse()
        resp.message("⚠️ Mensagem já processada.")
        return str(resp)
    if cache_key:
        open(cache_key, "w").close()

    app.logger.info("Msg de %s: %s", from_number, body)
    resp = MessagingResponse()

    try:
        parsed = interpretar_prompt(body)
        data = parsed.get("data")
        hora = parsed.get("hora")
        if not data:
            raise ValueError("Interpretação falhou: data ausente.")

        ev = criar_evento(
            titulo=parsed.get("titulo"),
            data_inicio=data,
            hora_inicio=hora,
            duracao_min=parsed.get("duracao_min", 60),
            participantes=parsed.get("participantes", []),
            descricao=parsed.get("descricao", ""),
            colorId=parsed.get("colorId", "9")
        )

        evento_url = ev.get("htmlLink", "")
        hora_txt = hora if hora else "(dia inteiro)"
        data_legivel = formatar_data_legivel(data)
        cor_nome = {
            "9": "Azul (Pavão)", "6": "Laranja", "3": "Roxo",
            "10": "Verde", "5": "Amarelo", "4": "Rosa",
            "8": "Cinza", "11": "Vermelho"
        }.get(parsed.get("colorId", "9"), "Azul (Pavão)")

        resp.message(
            f"✅ *Evento criado com sucesso!*\n"
            f"• {parsed.get('titulo')}\n"
            f"• {data_legivel} {hora_txt}\n"
            f"🔗 {evento_url}\n"
            f"🎨 *Cor:* {cor_nome}"
        )

    except Exception as e:
        app.logger.exception("Erro ao processar mensagem: %s", e)
        resp.message("❌ Não consegui agendar. Exemplo: 'reunião com João amanhã às 10h30'.")

    return str(resp)


# ======================================================
# 🩺 HEALTHCHECK
# ======================================================
@app.get("/")
def root():
    return ("", 204)


# ======================================================
# 🚀 EXECUÇÃO LOCAL
# ======================================================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
