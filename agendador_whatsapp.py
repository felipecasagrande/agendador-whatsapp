# -*- coding: utf-8 -*-
"""
agendador_whatsapp.py
Parser PT-BR + criação de evento no Google Calendar (Service Account).
Sem Google Meet (service accounts não criam Meet em contas pessoais).
"""

import re
import pytz
from calendar import monthrange
from datetime import datetime, timedelta, date, time as dtime

# ------------------ helpers TZ ------------------
def build_tz(tz_name: str):
    try:
        return pytz.timezone(tz_name)
    except Exception:
        return pytz.timezone("America/Sao_Paulo")


# ------------------ parsing ---------------------
MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "março": 3,
    "abril": 4, "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12
}

DIAS = {
    "segunda": 0, "segunda-feira": 0,
    "terca": 1, "terça": 1, "terca-feira": 1, "terça-feira": 1,
    "quarta": 2, "quarta-feira": 2,
    "quinta": 3, "quinta-feira": 3,
    "sexta": 4, "sexta-feira": 4,
    "sabado": 5, "sábado": 5,
    "domingo": 6
}

DUR_PADRAO_MIN = 60


def _norm(txt: str) -> str:
    text = txt.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _normaliza_chave(txt: str) -> str:
    rep = str.maketrans({
        "á": "a", "ã": "a", "â": "a", "à": "a",
        "é": "e", "ê": "e",
        "í": "i",
        "ó": "o", "ô": "o",
        "ú": "u",
        "ç": "c"
    })
    return txt.translate(rep)


def extrai_hora(msg: str, tz):
    raw = _norm(msg)

    m = re.search(r"\b(\d{1,2})h(?:(\d{2}))\b", raw)
    if m:
        hh = int(m.group(1)); mm = int(m.group(2))
        if 0 <= hh < 24 and 0 <= mm < 60:
            return dtime(hh, mm, tzinfo=tz)

    m = re.search(r"\b(\d{1,2})h\b", raw)
    if m:
        hh = int(m.group(1))
        if 0 <= hh < 24:
            return dtime(hh, 0, tzinfo=tz)

    m = re.search(r"\b(\d{1,2})(?::(\d{2}))\b", raw)
    if m:
        hh = int(m.group(1)); mm = int(m.group(2))
        if 0 <= hh < 24 and 0 <= mm < 60:
            return dtime(hh, mm, tzinfo=tz)

    # número isolado (ex.: "9")
    m = re.search(r"\b(\d{1,2})\b", raw)
    if m:
        hh = int(m.group(1))
        if 0 <= hh < 24:
            return dtime(hh, 0, tzinfo=tz)

    return None


def extrai_data(msg: str, agora: datetime):
    raw = _norm(msg)

    if re.search(r"\bdepois de amanh?ã?\b", raw):
        return (agora + timedelta(days=2)).date(), "depois_amanha"

    if re.search(r"\bamanh?ã?\b", raw):
        return (agora + timedelta(days=1)).date(), "amanha"

    if re.search(r"\bhoje\b", raw):
        return agora.date(), "hoje"

    if re.search(r"\bsemana que vem\b", raw):
        return (agora + timedelta(days=7)).date(), "semana_que_vem"

    if re.search(r"\bfim do m[eê]s\b", raw):
        y, m = agora.year, agora.month
        last_day = monthrange(y, m)[1]
        return date(y, m, last_day), "fim_do_mes"

    m = re.search(r"\b(?:na|na\s+)?pr[oó]xima\s+(segunda|ter[cç]a|terça|quarta|quinta|sexta|s[áa]bado|sabado|domingo)\b", raw)
    if m:
        alvo_txt = _normaliza_chave(m.group(1))
        alvo = DIAS.get(alvo_txt, None)
        if alvo is not None:
            hoje_dw = agora.weekday()
            delta = (alvo - hoje_dw) % 7
            if delta == 0:
                delta = 7
            return (agora + timedelta(days=delta)).date(), "proxima_dia_semana"

    m = re.search(r"\b(\d{1,2})\s+de\s+([a-záãéêíóôúç]+)(?:\s+de\s+(\d{4}))?\b", raw)
    if m:
        dd = int(m.group(1))
        mes_txt = _normaliza_chave(m.group(2))
        mm = MESES.get(mes_txt)
        if mm:
            yyyy = int(m.group(3)) if m.group(3) else agora.year
            try:
                return date(yyyy, mm, dd), "data_explicita"
            except ValueError:
                pass

    return None, None


def interpretar_mensagem(msg: str, tz=None):
    tz = tz or build_tz("America/Sao_Paulo")
    agora = datetime.now(tz)
    titulo = msg.strip()
    data_dt, origem = extrai_data(msg, agora)
    hora_dt = extrai_hora(msg, tz)

    return {
        "titulo": titulo,
        "data": data_dt.isoformat() if data_dt else "",
        "hora": hora_dt.strftime("%H:%M") if hora_dt else "",
        "duracao_min": DUR_PADRAO_MIN if hora_dt else 0,
        "participantes": [],
        "descricao": "",
        "meta": {"origem_data": origem}
    }


# ----------------- Google Calendar --------------------------
def criar_evento_google_calendar(service, parsed: dict, calendar_id: str, tz):
    titulo = parsed["titulo"]

    if not parsed["data"]:
        return ("❌ Não consegui entender a data. Exemplos: "
                "'amanhã às 10h30', 'fim do mês', 'na próxima quinta'.")

    # All-day
    if not parsed["hora"]:
        dia = datetime.fromisoformat(parsed["data"]).date()
        body = {
            "summary": titulo,
            "start": {"date": dia.isoformat()},
            "end": {"date": (dia + timedelta(days=1)).isoformat()},
        }
        service.events().insert(calendarId=calendar_id, body=body).execute()
        return f"✅ Evento de dia inteiro criado em {dia.strftime('%d/%m/%Y')}: {titulo}"

    # Timed (sem Meet)
    dia = datetime.fromisoformat(parsed["data"]).date()
    hh, mm = map(int, parsed["hora"].split(":"))
    inicio = tz.localize(datetime.combine(dia, dtime(hh, mm)))
    fim = inicio + timedelta(minutes=parsed.get("duracao_min") or DUR_PADRAO_MIN)

    body = {
        "summary": titulo,
        "start": {"dateTime": inicio.isoformat()},
        "end": {"dateTime": fim.isoformat()},
    }

    service.events().insert(calendarId=calendar_id, body=body).execute()
    return f"✅ Evento criado para {inicio.strftime('%d/%m/%Y %H:%M')}: {titulo}"
