import os
import json
import logging
from dotenv import load_dotenv
from flask import Flask, request, abort
from twilio.twiml.messaging_response import MessagingResponse
from twilio.request_validator import RequestValidator

# Funções principais do agendador
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

    if ALLOW_LIST and from_number not in ALLOW_LIST:
        resp = MessagingResponse()
        resp.message("❌ Número não autorizado.")
        return str(resp)

    resp = MessagingResponse()

    if body.lower() in {"help", "ajuda", "menu"}:
        resp.message(
            "📅 *Agendador WhatsApp*\n\n"
            "Envie mensagens como:\n"
            "• reunião com João amanhã às 14h #roxo\n"
            "• jantar com Maria hoje às 20h #laranja\n"
            "• comprar suco amanhã #azul (dia inteiro)\n\n"
            "💡 Se não informar cor, o evento será azul por padrão."
        )
        return str(resp)

    try:
        parsed = interpretar_prompt(body)
        data = parsed.get("data")
        hora = parsed.get("hora")
        cor = parsed.get("colorId", "1")

        if not data:
            raise ValueError("Interpretação falhou: data ausente.")

        ev = criar_evento(
            titulo=parsed.get("titulo"),
            data_inicio=data,
            hora_inicio=hora,
            duracao_min=parsed.get("duracao_min", 60),
            participantes=parsed.get("participantes", []),
            descricao=parsed.get("descricao", ""),
            color_id=cor
        )

        evento_url = ev.get("htmlLink", "")
        hora_txt = hora if hora else "(dia inteiro)"

        resp.message(
            f"✅ *Evento criado com sucesso!*\n"
            f"• {parsed.get('titulo')}\n"
            f"• {data} {hora_txt}\n"
            f"🔗 {evento_url if evento_url else '(sem link)'}"
        )
        app.logger.info(f"🎉 Evento criado: {parsed.get('titulo')} em {data} {hora_txt}")

    except Exception as e:
        app.logger.exception("Erro ao processar mensagem: %s", e)
        resp.message("❌ Não consegui agendar. Tente: 'reunião com João amanhã às 10h30 #laranja'.")

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
