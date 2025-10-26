from flask import Flask, request
import os
from agendar_por_prompt import interpretar_prompt, criar_evento

app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Agendador WhatsApp ativo!"

@app.route('/whats', methods=['POST'])
def whats():
    try:
        # Obter dados do Twilio
        from_number = request.form.get('From', '')
        mensagem = request.form.get('Body', '').strip()
        
        print(f"📱 Mensagem recebida de {from_number}: {mensagem}")
        
        if not mensagem:
            return """
            <Response>
                <Message>❌ Por favor, envie uma mensagem para agendar. Ex: "Reunião com João amanhã às 14h"</Message>
            </Response>
            """
        
        # Interpretar a mensagem
        parsed = interpretar_prompt(mensagem)
        
        # Criar evento no Google Calendar
        ev, link = criar_evento(
            titulo=parsed.get("titulo"),
            data_inicio=parsed.get("data"),
            hora_inicio=parsed.get("hora"),
            duracao_min=parsed.get("duracao_min"),
            participantes=parsed.get("participantes", []),
            descricao=parsed.get("descricao", ""),
            colorId=parsed.get("colorId", "9")
        )
        
        # Formatar mensagem de confirmação
        data_formatada = parsed.get("data", "")
        hora_formatada = parsed.get("hora", "")
        
        if hora_formatada:
            quando = f"{data_formatada} às {hora_formatada}"
        else:
            quando = f"{data_formatada} (dia inteiro)"
        
        mensagem_resposta = f"""✅ Evento agendado com sucesso!

📅 *{parsed.get('titulo')}*
🗓️ {quando}
⏰ Duração: {parsed.get('duracao_min', 60)} minutos

🔗 Acesse seu evento:
{link}

_Evento adicionado ao seu Google Calendar_"""
        
        print(f"📤 Enviando confirmação para WhatsApp: {mensagem_resposta}")
        
        return f"""
        <Response>
            <Message>{mensagem_resposta}</Message>
        </Response>
        """
        
    except Exception as e:
        print(f"❌ Erro ao processar mensagem: {e}")
        
        mensagem_erro = f"""❌ Não consegui agendar seu evento.

Erro: {str(e)}

Tente formatar assim:
• "Reunião com João amanhã às 14h"
• "Dentista dia 28/10"
• "Corte de cabelo hoje"

Ou seja mais específico com data e hora."""
        
        return f"""
        <Response>
            <Message>{mensagem_erro}</Message>
        </Response>
        """

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
