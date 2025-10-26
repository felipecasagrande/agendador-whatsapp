# -*- coding: utf-8 -*-
"""
agendador_whatsapp.py
Versão Render 2025 — compatível com conta de serviço
sem criação de link Meet (service accounts não suportam Meet)
"""

import re
import pytz
from calendar import monthrange
from datetime import datetime, timedelta, date, time as dtime

# -------------------- CONFIG --------------------
TZ = pytz.timezone("America/Sao_Paulo")
DUR_PADRAO_MIN = 60
CONVIDADO_AMOR = "britto.marilia@gmail.com"
CALENDAR_ID = "felipecasagrandematos@gmail.com"  # altere se quiser outro calendário
# ------------------------------------------------

MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "março": 3,
    "abril": 4, "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12
}

DIAS = {
    "segunda": 0, "segunda-feira": 0,
    "terca": 1, "terça": 1,
    "quarta": 2,
    "quinta": 3,
    "sexta": 4,
    "sabado": 5, "sábado": 5,
    "domingo": 6
}

def _agora():
    return datetime.now(TZ)

def _norm(txt: str) -> str:
    return re.sub(r"\s+", " ", txt.lower().strip())

def extrai_hora(msg: str):
    msg = _norm(msg)
    padroes = [
        r"(\d{1,2})h(\d{2})",
        r"(\d{1,2})h",
        r"(\d{1,2}):(\d{2})"
    ]
    for p in padroes:
        m = re.search(p, msg)
        if m:
            hh = int(m.group(1))
            mm = int(m.group(2)) if len(m.groups()) > 1 else 0
            if 0 <= hh < 24 and 0 <= mm < 60:
                return dtime(hh, mm, tzinfo=TZ)
    return None

def _normaliza_chave(txt: str) -> str:
    rep = str.maketrans("áãâàéêíóôúç", "aaaaeeioouc")
    return txt.translate(rep)

def extrai_data(msg: str, agora: datetime):
    raw = _norm(msg)

    if "depois de amanha" in raw or "depois de amanhã" in raw:
        return (agora + timedelta(days=2)).date(), "depois_amanha"
    if "amanha" in raw or "amanhã" in raw:
        return (agora + timedelta(days=1)).date(), "amanha"
    if "hoje" in raw:
        return agora.date(), "hoje"
    if "semana que vem" in raw:
        return (agora + timedelta(days=7)).date(), "semana_que_vem"

    m = re.search(r"(\d{1,2}) de ([a-záãéêíóôúç]+)(?: de (\d{4}))?", raw)
    if m:
        dd = int(m.group(1))
        mes_txt = _normaliza_chave(m.group(2))
        mm = MESES.get(mes_txt)
        yyyy = int(m.group(3)) if m.group(3) else agora.year
        if mm:
            return date(yyyy, mm, dd), "data_explicita"

    return None, None

def precisa_convidar_amor(msg: str) -> bool:
    return "convide amor" in _norm(msg)

def interpretar_mensagem(msg: str):
    agora = _agora()
    titulo = msg.strip()
    data_dt, origem = extrai_data(msg, agora)
    hora_dt = extrai_hora(msg)
    participantes = [CONVIDADO_AMOR] if precisa_convidar_amor(msg) else []
    return {
        "titulo": titulo,
        "data": data_dt.isoformat() if data_dt else "",
        "hora": hora_dt.strftime("%H:%M") if hora_dt else "",
        "duracao_min": DUR_PADRAO_MIN if hora_dt else 0,
        "participantes": participantes,
        "descricao": "",
        "meta": {"origem_data": origem}
    }

# ----------------- GOOGLE CALENDAR -----------------
def criar_evento_google_calendar(service, parsed: dict):
    titulo = parsed["titulo"]
    data = parsed["data"]
    hora = parsed["hora"]
    participantes = parsed.get("participantes", [])

    if not data:
        return "❌ Não consegui entender a data. Tente: 'amanhã às 15h' ou '10 de novembro às 9h'."

    if not hora:
        dia = datetime.fromisoformat(data).date()
        evento = {
            "summary": titulo,
            "start": {"date": dia.isoformat()},
            "end": {"date": (dia + timedelta(days=1)).isoformat()},
        }
        if participantes:
            evento["attendees"] = [{"email": e} for e in participantes]
        service.events().insert(calendarId=CALENDAR_ID, body=evento).execute()
        return f"✅ Evento de dia inteiro criado em {dia.strftime('%d/%m/%Y')}: {titulo}"

    dia = datetime.fromisoformat(data).date()
    hh, mm = map(int, hora.split(":"))
    inicio = TZ.localize(datetime.combine(dia, dtime(hh, mm)))
    fim = inicio + timedelta(minutes=parsed["duracao_min"])

    evento = {
        "summary": titulo,
        "start": {"dateTime": inicio.isoformat()},
        "end": {"dateTime": fim.isoformat()},
    }
    if participantes:
        evento["attendees"] = [{"email": e} for e in participantes]

    service.events().insert(calendarId=CALENDAR_ID, body=evento).execute()
    return f"✅ Evento criado para {inicio.strftime('%d/%m/%Y %H:%M')}: {titulo}"
