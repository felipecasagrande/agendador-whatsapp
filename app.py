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
    """Valida a assinatura da Twilio"""
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
# 📅 FORMATAÇÃO LEGÍVEL DE DATA (sem locale)
# ======================================================
def formatar_data_legivel(data_str):
    """Formata data para: '20 de outubro de 2025 (segunda-feira)', ou 'hoje'/'amanhã'"""
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

    nome_mes = meses[data.month - 1]
    nome_dia = dias_semana[data.weekday()]

    return f"{data.day} de {nome_mes} de {data.year} ({nome_dia})"


# ======================================================
# 💬 ENDPOINT PRINCIPAL - WHATSAPP
# ======================================================
@app.post("/whats")
def whats():
    """Recebe mensagens, interpreta com IA e agenda no Google Calendar"""
    _validate_twilio_signature()

    body = (request.form.get("Body") or "").strip()
    from_number = (request.form.get("From") or "").replace("whatsapp:", "")
    msg_sid = request.form.get("MessageSid")

    # ⚙️ Evita duplicação
    cache_key = os.path.join("/tmp", f"msg_{msg_sid}") if msg_sid else None
    if cache_key and os.path.exists(cache_key):
        resp = MessagingResponse()
        resp.message("⚠️ Mensagem já processada.")
        return str(resp)
    if cache_key:
        open(cache_key, "w").close()

    app.logger.info("Msg de %s: %s", from_number, body)

    # ⚙️ Autorização opcional
    if ALLOW_LIST and from_number not in ALLOW_LIST:
        resp = MessagingResponse()
        resp.message("❌ Número não autorizado para usar o agendador.")
        return str(resp)

    resp = MessagingResponse()

    # 📚 Comando de ajuda
    if body.lower() in {"help", "ajuda", "menu"}:
        resp.message(
            "📅 *Agendador WhatsApp*\n\n"
            "Envie mensagens como:\n"
            "• reunião com João amanhã às 14h\n"
            "• jantar com Maria hoje às 20h\n"
            "• call com equipe dia 24 às 16h30\n"
            "• comprar pão amanhã (evento de dia inteiro)\n"
            "• comprar suco hoje #laranja\n\n"
            "O evento será criado automaticamente no Google Calendar ✅"
        )
        return str(resp)

    # ==================================================
    # 🧩 PROCESSAMENTO PRINCIPAL
    # ==================================================
    try:
        parsed = interpretar_prompt(body)
        data = parsed.get("data")
        hora = parsed.get("hora")

        if not data:
            app.logger.error("❌ IA não retornou data válida.")
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

        cor_nomes = {
            "9": "Azul (Pavão)",
            "6": "Laranja",
            "3": "Roxo",
            "10": "Verde",
            "5": "Amarelo",
            "4": "Rosa",
            "8": "Cinza",
            "11": "Vermelho"
        }
        cor_nome = cor_nomes.get(parsed.get("colorId", "9"), "Azul (Pavão)")

        resp.message(
            f"✅ *Evento criado com sucesso!*\n"
            f"• {parsed.get('titulo')}\n"
            f"• {data_legivel} {hora_txt}\n"
            f"🔗 {evento_url if evento_url else '(sem link)'}\n"
            f"🎨 *Cor:* {cor_nome}"
        )

        app.logger.info(f"🎉 Evento criado: {parsed.get('titulo')} em {data_legivel} {hora_txt}")

    except Exception as e:
        app.logger.exception("Erro ao processar mensagem: %s", e)
        resp.message("❌ Não consegui agendar. Tente: 'reunião com João amanhã às 10h30'.")

    return str(resp)


# ======================================================
# 🩺 HEALTHCHECK
# ======================================================
@app.get("/")
def root():
    return ("", 204)  # Sem texto, status 204 = No Content


# ======================================================
# 📧 NOTIFICAÇÃO DE DEPLOY (SERVIDOR LIVE)
# ======================================================
def notify_live():
    """Envia e-mail automático quando o servidor está 'live'."""
    try:
        sender = os.getenv("SMTP_USER", "felipecasagrandematos@gmail.com")
        password = os.getenv("SMTP_PASS", "")
        recipient = "felipecasagrandematos@gmail.com"

        subject = "✅ Servidor Agendador WhatsApp está online!"
        body = (
            "Olá Felipe,\n\n"
            "O servidor foi iniciado com sucesso e está ativo em:\n"
            "🔗 https://agendador-whatsapp.onrender.com\n\n"
            "Data/hora do deploy: "
            + datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            + "\n\nAtenciosamente,\nAgendador Automático 🤖"
        )

        msg = MIMEMultipart()
        msg["From"] = sender
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)

        print("📨 E-mail enviado: servidor live notificado!")

    except Exception as e:
        print(f"⚠️ Falha ao enviar notificação: {e}")


# ======================================================
# 🚀 EXECUÇÃO LOCAL (debug)
# ======================================================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    notify_live()  # Envia e-mail de notificação
    app.run(host="0.0.0.0", port=port, debug=True)
