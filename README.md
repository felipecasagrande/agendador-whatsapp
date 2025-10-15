# Agendador via WhatsApp (Twilio) → Google Calendar (Render)

Cria eventos no Google Calendar a partir de mensagens de WhatsApp (Twilio Sandbox/Business).

## ⚙️ Deploy no Render

1. Crie um repo no GitHub com estes arquivos.
2. No Render.com: **New → Web Service** (Runtime Python).
3. **Build Command**: `pip install -r requirements.txt`
4. **Start Command**: `gunicorn whatsapp_twilio:app`
5. Em **Environment**, crie as variáveis listadas em `.env.example` (cole os JSONs completos de `GOOGLE_CREDENTIALS_JSON` e `GOOGLE_TOKEN_JSON`).
6. No Twilio (WhatsApp Sandbox), em **When a message comes in**, aponte para:  
   `https://SEUAPP.onrender.com/whats`

> Dica: gere `token.json` localmente uma vez (na sua VM) e cole o conteúdo em `GOOGLE_TOKEN_JSON` para evitar o fluxo de navegador no Render.

## Teste

Envie para o número do Sandbox: `reunião com João amanhã às 10h30`.
Você receberá a confirmação e o evento aparecerá no Google Calendar.
