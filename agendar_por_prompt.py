from openai import OpenAI
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import dateparser, pytz, json, re, os

SCOPES = ['https://www.googleapis.com/auth/calendar']
TZ = "America/Sao_Paulo"

# Inicializa cliente OpenAI (usa variável de ambiente OPENAI_TOKEN)
OPENAI_TOKEN = os.getenv("OPENAI_TOKEN", "")
client = OpenAI(api_key=OPENAI_TOKEN) if OPENAI_TOKEN else None


# ============================================================
# 🔹 Interpretação do prompt via IA
# ============================================================
def interpretar_prompt(prompt: str) -> dict:
    if not client:
        return {"titulo": "Reunião", "duracao_min": 60, "participantes": [], "descricao": ""}

    system = """
    Responda SOMENTE JSON no formato:
    {"titulo":"Reunião com ...","duracao_min":60,"participantes":["email@dominio"],"descricao":""}
    - Se não houver duração, use 60.
    - Se não houver e-mails, deixe participantes = [].
    - NÃO inclua campos de data/hora.
    """
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        temperature=0.2
    )
    content = resp.choices[0].message.content
    try:
        data = json.loads(content)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            raise ValueError("IA não retornou JSON válido.")
        data = json.loads(m.group(0))
    data.setdefault("titulo", "Reunião")
    data.setdefault("duracao_min", 60)
    data.setdefault("participantes", [])
    data.setdefault("descricao", "")
    return data


# ============================================================
# 🔹 Resolução de data/hora em português
# ============================================================
WEEKDAYS_PT = {
    "segunda": 0, "segunda-feira": 0,
    "terca": 1, "terça": 1, "terça-feira": 1, "terca-feira": 1,
    "quarta": 2, "quarta-feira": 2,
    "quinta": 3, "quinta-feira": 3,
    "sexta": 4, "sexta-feira": 4,
    "sabado": 5, "sábado": 5,
    "domingo": 6
}

def _norm(s: str) -> str:
    return s.lower().replace("às", "as").replace("hrs", "h").replace("hs", "h").strip()

def resolver_datetime_pt(texto: str, default_time="14:00", tz_str=TZ):
    tz = pytz.timezone(tz_str)
    now = datetime.now(tz)
    base_naive = now.replace(tzinfo=None)
    t = _norm(texto)
    dt = dateparser.parse(
        t, languages=["pt"],
        settings={"RETURN_AS_TIMEZONE_AWARE": False, "PREFER_DATES_FROM": "future", "RELATIVE_BASE": base_naive}
    )
    if not dt:
        if "amanha" in t:
            h = re.search(r"\b(\d{1,2})(?::|h)?(\d{2})?\b", t)
            hour = int(h.group(1)) if h else int(default_time.split(":")[0])
            minute = int(h.group(2) or 0) if h else int(default_time.split(":")[1])
            dt = (now + relativedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0).replace(tzinfo=None)
        else:
            dow = next((WEEKDAYS_PT[k] for k in WEEKDAYS_PT if k in t), None)
            if dow is not None:
                days_ahead = (dow - now.weekday()) % 7 or 7
                h = re.search(r"\b(\d{1,2})(?::|h)?(\d{2})?\b", t)
                hour = int(h.group(1)) if h else int(default_time.split(":")[0])
                minute = int(h.group(2) or 0) if h else int(default_time.split(":")[1])
                dt = (now + relativedelta(days=days_ahead)).replace(hour=hour, minute=minute, second=0, microsecond=0).replace(tzinfo=None)
    if not dt:
        hour, minute = map(int, default_time.split(":"))
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += relativedelta(days=1)
        dt = candidate.replace(tzinfo=None)
    parsed = tz.localize(dt)
    if parsed <= now:
        parsed = parsed + relativedelta(days=1)
    date_iso = parsed.strftime("%Y-%m-%d")
    time_iso = parsed.strftime("%H:%M")
    return date_iso, time_iso


# ============================================================
# 🔹 Criação do evento no Google Calendar (corrigido p/ Render)
# ============================================================
def criar_evento(titulo, data_inicio, hora_inicio, duracao_min, participantes, descricao, colorId="1"):
    """
    Cria um evento no Google Calendar com suporte a cores e correção automática
    do formato da chave privada do Render (substitui '\\n' por '\n').
    """
    inicio_dt = datetime.strptime(f"{data_inicio} {hora_inicio}", "%Y-%m-%d %H:%M")
    fim_dt = inicio_dt + timedelta(minutes=int(duracao_min or 60))
    start_iso = inicio_dt.strftime("%Y-%m-%dT%H:%M:%S")
    end_iso = fim_dt.strftime("%Y-%m-%dT%H:%M:%S")

    # Carrega credenciais do ambiente
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        raise ValueError("❌ Variável GOOGLE_CREDENTIALS_JSON não encontrada.")

    # 🔧 Corrige quebra de linha perdida no Render
    creds_json = creds_json.replace('\\n', '\n')

    creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=SCOPES)
    service = build("calendar", "v3", credentials=creds)

    # Corpo do evento
    body = {
        "summary": titulo or "Reunião",
        "description": descricao or "",
        "start": {"dateTime": start_iso, "timeZone": TZ},
        "end": {"dateTime": end_iso, "timeZone": TZ},
        "attendees": [{"email": e} for e in (participantes or []) if "@" in e],
        "colorId": colorId or "1"
    }

    ev = service.events().insert(calendarId="primary", body=body).execute()
    print(f"✅ Evento criado: {ev.get('htmlLink')}")
    return ev
