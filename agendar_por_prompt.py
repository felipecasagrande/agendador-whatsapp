# -*- coding: utf-8 -*-
"""
agendar_por_prompt.py
Camada de domínio: interpretar mensagem em PT-BR e criar eventos no Google Calendar.
"""

import os
import json
import re
import pytz
import httpx
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from google.oauth2 import service_account

# ======================================================
# 🔧 CONFIGURAÇÕES GERAIS
# ======================================================
SCOPES = ["https://www.googleapis.com/auth/calendar"]
TZ = "America/Sao_Paulo"

# Desativa cache problemático do Google API
import googleapiclient.discovery_cache.base
class MemoryCache(googleapiclient.discovery_cache.base.Cache):
    def __init__(self):
        self.cache = {}

    def get(self, url):
        return self.cache.get(url)

    def set(self, url, content):
        self.cache[url] = content

# ======================================================
# 🧠 INTERPRETAÇÃO DE TEXTO (IA OpenAI)
# ======================================================
def interpretar_prompt(prompt: str):
    """
    Usa GPT-4o-mini para interpretar frases e retornar:
    titulo, data, hora, duracao_min, participantes, descricao, colorId
    """
    tz = pytz.timezone(TZ)
    hoje = datetime.now(tz).date()

    try:
        # 🔍 DETECÇÃO DE COMANDOS SIMPLES (como "Corte cabelo", "tomar psi")
        prompt_limpo = prompt.strip().lower()
        
        # Lista de palavras que indicam comandos simples de agendamento
        palavras_chave = ['corte', 'cabelo', 'reunião', 'consulta', 'compra', 'comprar', 
                         'fazer', 'ir', 'visita', 'encontro', 'evento', 'tarefa', 'tomar',
                         'psi', 'psicólogo', 'psicologa', 'médico', 'médica', 'dentista']
        
        # Se for um comando muito simples (1-3 palavras) contendo palavras-chave
        palavras = prompt_limpo.split()
        if 1 <= len(palavras) <= 3 and any(palavra in prompt_limpo for palavra in palavras_chave):
            print(f"🎯 Detectado comando simples: '{prompt}' - Agendando para hoje")
            return {
                "titulo": prompt.strip(),
                "data": hoje.strftime("%Y-%m-%d"),
                "hora": "",
                "duracao_min": 60,
                "participantes": [],
                "descricao": "Agendamento automático para hoje",
                "colorId": "9"
            }

        token = os.getenv("OPENAI_TOKEN", "").strip()
        if not token:
            raise ValueError("OPENAI_TOKEN ausente no ambiente.")
        print(f"✅ Token OpenAI ativo (prefixo): {token[:15]}")

        exemplos = [
            {"input": "reunião com João amanhã às 10h30",
             "output": {"titulo": "Reunião com João", "data": "amanhã", "hora": "10:30", "duracao_min": 60}},
            {"input": "jantar com Maria hoje às 20h",
             "output": {"titulo": "Jantar com Maria", "data": "hoje", "hora": "20:00", "duracao_min": 120}},
            {"input": "comprar suco dia 23/10/2025",
             "output": {"titulo": "Comprar suco", "data": "2025-10-23", "hora": "", "duracao_min": 30}},
            {"input": "corte de cabelo",
             "output": {"titulo": "Corte de cabelo", "data": "hoje", "hora": "", "duracao_min": 60}},
            {"input": "consulta médica",
             "output": {"titulo": "Consulta médica", "data": "hoje", "hora": "", "duracao_min": 60}},
            {"input": "tomar psi",
             "output": {"titulo": "Sessão de psicologia", "data": "hoje", "hora": "", "duracao_min": 60}},
        ]

        prompt_base = (
            "Você é um assistente que interpreta frases de agendamento em português e responde SOMENTE em JSON válido.\n"
            "IMPORTANTE: Use APENAS datas válidas no formato AAAA-MM-DD. O mês deve ser entre 01-12.\n"
            "Para frases simples sem data específica, use 'hoje'.\n\n"
            "Campos obrigatórios:\n"
            "- titulo: texto do evento\n"
            "- data: AAAA-MM-DD ou 'hoje'/'amanhã'\n" 
            "- hora: HH:MM ou string vazia para dia inteiro\n"
            "- duracao_min: número em minutos (padrão: 60)\n"
            "- participantes: lista vazia ou emails\n"
            "- descricao: string vazia ou texto\n"
            "- colorId: '9' (padrão)\n\n"
            f"Exemplos:\n{json.dumps(exemplos, ensure_ascii=False, indent=2)}\n\n"
            f"Processe agora: '{prompt}'\n"
            "RESPONDA APENAS COM JSON VÁLIDO:"
        )

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "Você é um assistente de agendamento. Responda APENAS com JSON válido. Use datas realistas (meses 01-12). Para 'tomar psi' retorne título 'Sessão de psicologia' e data 'hoje'."},
                {"role": "user", "content": prompt_base},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"}
        }

        print(f"🧠 Enviando para IA → {prompt}")
        response = httpx.post("https://api.openai.com/v1/chat/completions", headers=headers, json=body, timeout=30)
        data = response.json()

        conteudo = data["choices"][0]["message"]["content"].strip()
        if conteudo.startswith("```"):
            conteudo = conteudo.replace("```json", "").replace("```", "").strip()

        parsed = json.loads(conteudo)

        # 🔍 VALIDAÇÃO E CORREÇÃO DA DATA
        data_original = parsed.get("data", "")
        
        # Corrige "hoje" / "amanhã"
        if data_original == "hoje":
            parsed["data"] = hoje.strftime("%Y-%m-%d")
        elif data_original in ("amanha", "amanhã"):
            parsed["data"] = (hoje + timedelta(days=1)).strftime("%Y-%m-%d")
        
        # Valida se a data é válida
        data_final = parsed.get("data", "")
        if data_final and data_final != "hoje" and data_final != "amanhã":
            try:
                # Tenta converter para validar
                datetime.strptime(data_final, "%Y-%m-%d")
                # Verifica se o mês é válido (1-12)
                ano, mes, dia = map(int, data_final.split('-'))
                if not (1 <= mes <= 12):
                    print(f"⚠️ Mês inválido {mes}, corrigindo para hoje")
                    parsed["data"] = hoje.strftime("%Y-%m-%d")
            except ValueError as e:
                print(f"⚠️ Data inválida '{data_final}', corrigindo para hoje: {e}")
                parsed["data"] = hoje.strftime("%Y-%m-%d")

        # Garante campos obrigatórios
        parsed["titulo"] = parsed.get("titulo", prompt.strip())
        parsed["hora"] = parsed.get("hora", "")
        parsed["duracao_min"] = parsed.get("duracao_min", 60)
        parsed["participantes"] = parsed.get("participantes", [])
        parsed["descricao"] = parsed.get("descricao", "")
        parsed["colorId"] = parsed.get("colorId", "9")

        print("🧩 Saída final da IA (VALIDADA):")
        print(json.dumps(parsed, indent=2, ensure_ascii=False))
        return parsed

    except Exception as e:
        print(f"❌ Erro ao interpretar prompt: {e}")
        # Fallback: se der erro na IA, cria evento para hoje
        print(f"🔄 Fallback: criando evento para hoje com título '{prompt}'")
        return {
            "titulo": prompt.strip(),
            "data": hoje.strftime("%Y-%m-%d"),
            "hora": "",
            "duracao_min": 60,
            "participantes": [],
            "descricao": "Agendamento automático",
            "colorId": "9"
        }


# ======================================================
# 🔐 GOOGLE CALENDAR SERVICE ACCOUNT
# ======================================================
def get_calendar_service():
    """Autentica via Service Account com tratamento robusto de JSON"""
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        raise ValueError("❌ GOOGLE_CREDENTIALS_JSON ausente no ambiente.")

    # Limpeza básica
    cleaned = creds_json.strip()
    cleaned = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', cleaned)
    
    if not cleaned.startswith("{"):
        raise ValueError("❌ O conteúdo de GOOGLE_CREDENTIALS_JSON não é um JSON válido.")

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"❌ Erro ao decodificar JSON: {e}")
        raise ValueError(f"Erro ao decodificar GOOGLE_CREDENTIALS_JSON: {e}")

    creds = service_account.Credentials.from_service_account_info(data, scopes=SCOPES)
    print(f"✅ Credenciais carregadas: {data.get('client_email')}")
    
    # Usa cache em memória para evitar problemas de arquivo
    return build("calendar", "v3", credentials=creds, cache=MemoryCache())


# ======================================================
# 📅 CRIAÇÃO DE EVENTO COM TRATAMENTO DE ERRO
# ======================================================
def criar_evento(titulo, data_inicio, hora_inicio, duracao_min, participantes, descricao, colorId="9"):
    """Cria evento no Google Calendar com tratamento robusto de erro"""
    try:
        service = get_calendar_service()
        fuso = pytz.timezone(TZ)
        hoje = datetime.now(fuso).date()

        # VALIDAÇÃO FINAL DA DATA
        if isinstance(data_inicio, str):
            if data_inicio.lower() == "hoje":
                data_inicio = hoje.strftime("%Y-%m-%d")
            elif data_inicio.lower() in ("amanha", "amanhã"):
                data_inicio = (hoje + timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                # Valida formato da data
                try:
                    datetime.strptime(data_inicio, "%Y-%m-%d")
                except ValueError:
                    print(f"⚠️ Data final inválida '{data_inicio}', usando hoje")
                    data_inicio = hoje.strftime("%Y-%m-%d")

        # Evento de dia inteiro
        if not hora_inicio or str(hora_inicio).strip() == "":
            data_fim = (datetime.strptime(data_inicio, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            body = {
                "summary": titulo or "Evento",
                "description": descricao or "",
                "start": {"date": data_inicio},
                "end": {"date": data_fim},
                "attendees": [{"email": e} for e in (participantes or []) if "@" in e],
                "colorId": colorId,
                "reminders": {"useDefault": False},
            }
            ev = service.events().insert(calendarId="primary", body=body).execute()
            link = ev.get('htmlLink', 'Link não disponível')
            print(f"✅ Evento de dia inteiro criado: {link}")
            return ev, link

        # Evento com hora definida
        inicio = fuso.localize(datetime.strptime(f"{data_inicio} {hora_inicio}", "%Y-%m-%d %H:%M"))
        fim = inicio + timedelta(minutes=int(duracao_min or 60))
        body = {
            "summary": titulo or "Evento",
            "description": descricao or "",
            "start": {"dateTime": inicio.isoformat(), "timeZone": TZ},
            "end": {"dateTime": fim.isoformat(), "timeZone": TZ},
            "attendees": [{"email": e} for e in (participantes or []) if "@" in e],
            "colorId": colorId,
            "reminders": {"useDefault": True},
        }
        ev = service.events().insert(calendarId="primary", body=body).execute()
        link = ev.get('htmlLink', 'Link não disponível')
        print(f"✅ Evento com hora criado: {link}")
        return ev, link

    except Exception as e:
        print(f"❌ Erro ao criar evento no Google Calendar: {e}")
        raise
