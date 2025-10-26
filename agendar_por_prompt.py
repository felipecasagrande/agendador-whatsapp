# -*- coding: utf-8 -*-
"""
agendador_whatsapp.py
Camada de domínio: interpretar mensagem em PT-BR e criar evento no Google Calendar.

Regras implementadas:
- “hoje”, “amanhã/amanha”, “depois de amanhã/amanha”
- “fim do mês” (mês corrente)
- “semana que vem” (+7 dias)
- data explícita “24 de outubro de 2025” (ou “24 de outubro” => ano corrente)
- “na próxima <dia da semana>” (se hoje for o dia, vai para a semana seguinte)
- extrai horários “10h30”, “10:30”, “16h”, etc.
- sem hora => evento de dia inteiro
- com hora => 60 min + Meet
- “convide amor” -> adiciona automaticamente britto.marilia@gmail.com
"""

import re
import uuid
import pytz
from calendar import monthrange
from datetime import datetime, timedelta, date, time as dtime

# -------------------- CONFIG --------------------
TZ = pytz.timezone("America/Sao_Paulo")
DUR_PADRAO_MIN = 60
CONVIDADO_AMOR = "britto.marilia@gmail.com"
# ------------------------------------------------

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


def _agora():
    return datetime.now(TZ)


def _norm(txt: str) -> str:
    txt = txt.lower().strip()
    txt = re.sub(r"\s+", " ", txt)
    return txt


def extrai_hora(msg: str):
    """
    Retorna um dtime (timezone-aware) ou None.
    Suporta: 10h, 10h30, 10:30, 9, 09:00
    """
    m = re.search(r"\b(\d{1,2})h(?:(\d{2}))\b", _norm(msg))
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2))
        if 0 <= hh < 24 and 0 <= mm < 60:
            return dtime(hh, mm, tzinfo=TZ)
    m = re.search(r"\b(\d{1,2})h\b", _norm(msg))
    if m:
        hh = int(m.group(1))
        if 0 <= hh < 24:
            return dtime(hh, 0, tzinfo=TZ)
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))\b", _norm(msg))
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2))
        if 0 <= hh < 24 and 0 <= mm < 60:
            return dtime(hh, mm, tzinfo=TZ)
    # número isolado (ex.: "9")
    m = re.search(r"\b(\d{1,2})\b", _norm(msg))
    if m:
        hh = int(m.group(1))
        if 0 <= hh < 24:
            return dtime(hh, 0, tzinfo=TZ)
    return None


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


def extrai_data(msg: str, agora: datetime):
    """
    Retorna (date, origem_str) ou (None, None)
    A ordem das verificações evita conflitos (ex.: "depois de amanhã" antes de "amanhã")
    """
    raw = _norm(msg)

    # 1) Depois de amanhã
    if re.search(r"\bdepois de amanh?ã?\b", raw):
        return (agora + timedelta(days=2)).date(), "depois_amanha"

    # 2) Amanhã
    if re.search(r"\bamanh?ã?\b", raw):
        return (agora + timedelta(days=1)).date(), "amanha"

    # 3) Hoje
    if re.search(r"\bhoje\b", raw):
        return agora.date(), "hoje"

    # 4) Semana que vem (+7)
    if re.search(r"\bsemana que vem\b", raw):
        return (agora + timedelta(days=7)).date(), "semana_que_vem"

    # 5) Fim do mês corrente
    if re.search(r"\bfim do m[eê]s\b", raw):
        y, m = agora.year, agora.month
        last_day = monthrange(y, m)[1]
        return date(y, m, last_day), "fim_do_mes"

    # 6) Próxima <dia da semana>
    m = re.search(r"\b(?:na|na\s+)?pr[oó]xima\s+(segunda|ter[cç]a|terça|quarta|quinta|sexta|s[áa]bado|sabado|domingo)\b", raw)
    if m:
        alvo_txt = _normaliza_chave(m.group(1))
        # normaliza chaves
        if alvo_txt == "terca": alvo_txt = "terca"
        if alvo_txt == "sabado": alvo_txt = "sabado"
        alvo = DIAS.get(alvo_txt, None)
        if alvo is not None:
            hoje_dw = agora.weekday()
            delta = (alvo - hoje_dw) % 7
            if delta == 0:
                delta = 7
            return (agora + timedelta(days=delta)).date(), "proxima_dia_semana"

    # 7) Datas explícitas “24 de outubro de 2025” ou “24 de outubro”
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


def precisa_convidar_amor(msg: str) -> bool:
    return "convide amor" in _norm(msg)


def interpretar_mensagem(msg: str):
    """
    Produz um dicionário padronizado para o agendamento.
    """
    agora = _agora()
    titulo = msg.strip()
    data_dt, origem = extrai_data(msg, agora)
    hora_dt = extrai_hora(msg)

    participantes = []
    if precisa_convidar_amor(msg):
        participantes.append(CONVIDADO_AMOR)

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
    """
    service: googleapiclient Calendar v3
    parsed: retorno de interpretar_mensagem()

    - Sem hora => all-day
    - Com hora => DUR_PADRAO_MIN + Meet
    - “convide amor” => adiciona CONVIDADO_AMOR
    """
    titulo = parsed["titulo"]
    participantes = parsed.get("participantes", [])

    if not parsed["data"]:
        return "❌ Não consegui entender a data. Exemplos: 'amanhã às 10h30', 'fim do mês', 'na próxima quinta'."

    # All-day
    if not parsed["hora"]:
        dia = datetime.fromisoformat(parsed["data"]).date()
        body = {
            "summary": titulo,
            "start": {"date": dia.isoformat()},
            "end": {"date": (dia + timedelta(days=1)).isoformat()},
        }
        if participantes:
            body["attendees"] = [{"email": e} for e in participantes]

        service.events().insert(calendarId="primary", body=body).execute()
        return f"✅ Evento de dia inteiro criado em {dia.strftime('%d/%m/%Y')}: {titulo}"

    # Timed + Meet
    dia = datetime.fromisoformat(parsed["data"]).date()
    hh, mm = map(int, parsed["hora"].split(":"))
    inicio = TZ.localize(datetime.combine(dia, dtime(hh, mm)))
    fim = inicio + timedelta(minutes=parsed["duracao_min"] or DUR_PADRAO_MIN)

    body = {
        "summary": titulo,
        "start": {"dateTime": inicio.isoformat()},
        "end": {"dateTime": fim.isoformat()},
        "conferenceData": {
            "createRequest": {
                "requestId": str(uuid.uuid4()),
                "conferenceSolutionKey": {"type": "hangoutsMeet"}
            }
        }
    }
    if participantes:
        body["attendees"] = [{"email": e} for e in participantes]

    created = service.events().insert(
        calendarId="primary",
        body=body,
        conferenceDataVersion=1
    ).execute()

    # Se quiser devolver o link do meet:
    meet = created.get("hangoutLink")
    if meet:
        return f"✅ Evento criado para {inicio.strftime('%d/%m/%Y %H:%M')} (Meet): {titulo}\n🔗 {meet}"
    return f"✅ Evento criado para {inicio.strftime('%d/%m/%Y %H:%M')} (Meet adicionado): {titulo}"
