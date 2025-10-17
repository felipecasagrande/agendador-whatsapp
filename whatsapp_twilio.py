import os
import json
import logging
from dotenv import load_dotenv
from flask import Flask, request, abort
from twilio.twiml.messaging_response import MessagingResponse
from twilio.request_validator import RequestValidator

# Importa as funções principais do agendador
from agendar_por_prompt import interpretar_prompt, resolver_datetime_pt, criar_evento

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
# 🧾 FUNÇÃO DE VALIDAÇÃO DE SEGURANÇA
# ======================================================
def _validate_twilio_signature():
    """Valida a assinatura de segurança da Twilio"""
    if not validator:
        app.logger.warning("Validator desabilitado (AUTH_TOKEN ausente).")
        return
    sig = request.headers.get("X-Twilio-Signature", "")
    url = request.url
    params = request.form.to_dict()
    if not validator.validate(url, params, sig):
        app.logger.warning("Assinatura Twilio inválida.")
        abort(403)


# ======================================================
# 💬 ENDPOINT PRINCIPAL - WHATSAPP
# ======================================================
@app.post("/whats")
def whats():
    """
    Recebe mensagens do WhatsApp, interpreta a frase com IA e agenda no Google Calendar.
    """
    _validate_twilio_signature()

    body = (request.form.get("Body") or "").strip()
    from_number = (request.form.get("From") or "").replace("whatsapp:", "")
    msg_sid = request.form.get("MessageSid")

    # ⚙️ Controle de duplicação
    cache_key = os.path.join("/tmp", f"msg_{msg_sid}") if msg_sid else None
    if cache_key and os.path.exists(cache_key):
        resp = MessagingResponse()
        resp.message("⚠️ Mensagem já processada.")
        return str(resp)
    if cache_key:
        open(cache_key, "w").close()

    app.logger.info("Msg de %s: %s", from_number, body)

    # ⚙️ Verifica lista de números permitidos (opcional)
    if ALLOW_LIST and from_number not in ALLOW_LIST:
        resp = MessagingResponse()
        resp.message("❌ Número não autorizado para usar o agendador.")
        return str(resp)

    resp = MessagingResponse()

    # 📚 Comandos simples
    if body.lower() in {"help", "ajuda", "menu"}:
        resp.message(
            "📅 *Agendador WhatsApp*\n\n"
            "Envie mensagens como:\n"
            "• reunião com João amanhã às 14h\n"
            "• jantar com Maria hoje às 20h\n"
            "• call com equipe dia 24 às 16h30\n\n"
            "O evento será criado no seu Google Calendar automaticamente ✅"
        )
        return str(resp)

    # ==================================================
    # 🧩 PROCESSAMENTO PRINCIPAL
    # ==================================================
    try:
        # 1️⃣ Tenta interpretar via IA
        parsed = interpretar_prompt(body)
        data = parsed.get("data")
        hora = parsed.get("hora")

        # 2️⃣ Se a IA não entendeu data/hora, usa fallback manual
        if not data or not hora:
            app.logger.warning("⚠️ IA não retornou data/hora — ativando fallback manual.")
            data, hora = resolver_datetime_pt(body)
        else:
            app.logger.info(f"✅ Usando data/hora da IA: {data} {hora}")

        # 3️⃣ Cria o evento no Google Calendar
        ev = criar_evento(
            titulo=parsed.get("titulo"),
            data_inicio=data,
            hora_inicio=hora,
            duracao_min=parsed.get("duracao_min", 60),
            participantes=parsed.get("participantes", []),
            descricao=parsed.get("descricao", "")
        )

        evento_url = ev.get("htmlLink", "")
        resp.message(
            f"✅ *Evento criado com sucesso!*\n"
            f"• {parsed.get('titulo')}\n"
            f"• {data} {hora}\n"
            f"🔗 {evento_url if evento_url else '(sem link)'}"
        )
        app.logger.info(f"🎉 Evento criado: {parsed.get('titulo')} em {data} {hora}")

    except Exception as e:
        app.logger.exception("Erro ao processar mensagem: %s", e)
        resp.message("❌ Ocorreu um erro ao criar o evento. Tente: 'reunião com João amanhã às 10h30'.")

    return str(resp)


# ======================================================
# 🩺 HEALTHCHECK
# ======================================================
@app.get("/")
def root():
    return "OK", 200


# ======================================================
# 🚀 EXECUÇÃO LOCAL (modo debug)
# ======================================================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
