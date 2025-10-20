import os
import json
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from google.oauth2 import service_account
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def interpretar_prompt(prompt: str):
    try:
        hoje = datetime.now().date()
        parsed = {"titulo": prompt, "data": "", "hora": "", "duracao_min": 0, "participantes": [], "descricao": ""}

        # IA tenta entender
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Extraia título, data, hora, duração (minutos), participantes e descrição de uma frase em português."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        parsed.update(json.loads(completion.choices[0].message.content))

        # "convide amor" adiciona e-mail da Marília
        if "convide amor" in prompt.lower():
            convidados = parsed.get("participantes", [])
            if "britto.marilia@gmail.com" not in convidados:
                convidados.append("britto.marilia@gmail.com")
            parsed["participantes"] = convidados

        # Detectar cor (#laranja, #roxo, etc)
        cor_map = {
            "#azul": "9",
            "#roxo": "3",
            "#verde": "10",
            "#amarelo": "5",
            "#laranja": "6",
            "#rosa": "4",
            "#cinza": "8",
            "#vermelho": "11"
        }
        parsed["colorId"] = "9"  # padrão: azul pavão
        for cor_tag, cor_id in cor_map.items():
            if cor_tag in prompt.lower():
                parsed["colorId"] = cor_id
                parsed["descricao"] = cor_tag
                break

        # Se não houver data, tenta hoje
        if not parsed.get("data"):
            parsed["data"] = hoje.strftime("%Y-%m-%d")

        # Se não houver hora, evento de dia inteiro
        if not parsed.get("hora"):
            parsed["hora"] = ""

        print("🧩 Saída final da IA:")
        print(json.dumps(parsed, indent=2, ensure_ascii=False))
        return parsed

    except Exception as e:
        print(f"❌ Erro ao interpretar prompt: {e}")
        raise


def criar_evento(titulo, data_inicio, hora_inicio, duracao_min=60, participantes=None, descricao="", colorId="9"):
    try:
        SCOPES = ["https://www.googleapis.com/auth/calendar"]
        creds = service_account.Credentials.from_service_account_file(
            "credentials.json", scopes=SCOPES
        )
        service = build("calendar", "v3", credentials=creds)

        if hora_inicio:
            inicio = f"{data_inicio}T{hora_inicio}:00"
            fim = (datetime.strptime(inicio, "%Y-%m-%dT%H:%M:%S") + timedelta(minutes=duracao_min)).strftime("%Y-%m-%dT%H:%M:%S")
            event = {
                "summary": titulo,
                "description": descricao,
                "start": {"dateTime": inicio, "timeZone": "America/Recife"},
                "end": {"dateTime": fim, "timeZone": "America/Recife"},
                "colorId": colorId,
                "attendees": [{"email": e} for e in participantes or []],
                "reminders": {"useDefault": True}
            }
        else:
            event = {
                "summary": titulo,
                "description": descricao,
                "start": {"date": data_inicio},
                "end": {"date": data_inicio},
                "colorId": colorId,
                "attendees": [{"email": e} for e in participantes or []],
                "reminders": {"useDefault": False}
            }

        ev = service.events().insert(calendarId="primary", body=event).execute()
        print(f"✅ Evento criado: {titulo} em {data_inicio} {hora_inicio or '(dia inteiro)'}")
        return ev

    except Exception as e:
        print(f"❌ Erro ao criar evento: {e}")
        raise
