import os, json, logging
from dotenv import load_dotenv
from flask import Flask, request, abort
from twilio.twiml.messaging_response import MessagingResponse
from twilio.request_validator import RequestValidator

# Carrega envs
load_dotenv()
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# Importa funções principais
from agendar_por_prompt import interpretar_prompt, resolver_datetime_pt, criar_evento

# --------------------------------------------------------
# GOOGLE CREDENTIALS (carrega via variáveis de ambiente)
# --------------------------------------------------------
def _materialize_google_files():
    creds_txt = os.getenv("GOOGLE_CREDENTIALS_JSON")
    token_txt = os.getenv("GOOGLE_TOKEN_JSON")
    if creds_txt and not os.path.exists("credentials.json"):
        with open("credentials.json", "w", encoding="utf-8") as f:
            f.write(creds_txt)
    if token_txt and not os.path.exists("token.json"):
        with open("token.json", "w", encoding="utf-8") as f:
            f.write(token_txt)

_materialize_google_files()

# --------------------------------------------------------
# TWILIO SETTINGS
# --------------------------------------------------------
ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATS_NUMBER = os.getenv("TWILIO_WHATS_NUMBER", "whatsapp:+14155238886")
ALLOW_LIST = set(filter(None, [n.strip() for n in os.getenv("ALLOW_LIST", "").split(",")]))
validator = RequestValidator(AUTH_TOKEN) if AUTH_TOKEN else None

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

# --------------------------------------------------------
# ENDPOINT PRINCIPAL
# --------------------------------------------------------
@app.post("/whats")
def whats():
    """Recebe mensagens do WhatsApp e agenda eventos via Google Calendar"""
    _validate_twilio_signature()

    body = (request.form.get("Body") or "").strip()
    from_number = (request.form.get("From") or "").replace("whatsapp:", "")

    # Whitelist opcional
    if ALLOW_LIST and from_number not in ALLOW_LIST:
        resp = MessagingResponse()
        resp.message("❌ Número não autorizado.")
        return str(resp)

    # Idempotência por MessageSid (evita duplicação)
    msg_sid = request.form.get("MessageSid")
    cache_key = os.path.join("/tmp", f"msg_{msg_sid}") if msg_sid else None
    if cache_key and os.path.exists(cache_key):
        resp = MessagingResponse()
        resp.message("⚠️ Mensagem já processada.")
        return str(resp)
    if cache_key:
        open(cache_key, "w").close()

    app.logger.info("Msg de %s: %s", from_number, body)

    # Comando simples
    if body.lower() in {"help", "ajuda", "menu"}:
        resp = MessagingResponse()
        resp.message("Envie algo como: 'reunião com Joana amanhã às 14h'")
        return str(resp)

    # --------------------------------------------------------
    # BLOCO PRINCIPAL (IA + FALLBACK)
    # --------------------------------------------------------
    resp = MessagingResponse()
    try:
        # 🔹 Interpreta o texto via IA
        parsed = interpretar_prompt(body)
        data = parsed.get("data")
        hora = parsed.get("hora")

        # 🔹 Só usa fallback se a IA não retornar data/hora válidas
        if not data or not hora:
            app.logger.warning("⚠️ IA não retornou data/hora — ativando fallback manual.")
            data, hora = resolver_datetime_pt(body)
        else:
            app.logger.info(f"✅ Usando data/hora da IA: {data} {hora}")

        # 🔹 Cria o evento no Google Calendar
        ev = criar_evento(
            parsed["titulo"],
            data,
            hora,
            int(parsed.get("duracao_min", 60)),
            parsed.get("participantes", []),
            parsed.get("descricao", "")
        )

        resp.message(f"✅ Evento criado!\n• {parsed['titulo']}\n• {data} {hora}")

    except Exception as e:
        app.logger.exception("Erro: %s", e)
        resp.message("❌ Não consegui agendar. Tente: 'reunião com João amanhã às 10h30'.")

    return str(resp)

# --------------------------------------------------------
# HEALTHCHECK
# --------------------------------------------------------
@app.get("/")
def root():
    return "OK", 200
