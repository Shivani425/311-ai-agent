# app.py — North Carolina 311 Agent with real-time address geocoding (US Census)
import re, random, csv, io, requests
from datetime import datetime
import streamlit as st

# ---------- Page chrome ----------
st.set_page_config(page_title="NC 311 Agent", page_icon="🧰", layout="wide")
st.markdown("""
<style>
.main .block-container{max-width:900px;}
.bubble{border-radius:16px; padding:12px 14px; margin:8px 0; max-width:85%; line-height:1.35;}
.left{background:#0c3a5b; color:#fff; border-top-left-radius:6px;}
.right{background:#f1f5f9; color:#111; margin-left:auto; border-top-right-radius:6px;}
.stChatInputContainer{position:sticky; bottom:0; background:linear-gradient(180deg,rgba(255,255,255,0),#fff 30%);}
.small{opacity:.85; font-size:.92rem}
</style>
""", unsafe_allow_html=True)

def bleft(t:str):  st.markdown(f'<div class="bubble left">{t}</div>', unsafe_allow_html=True)
def bright(t:str): st.markdown(f'<div class="bubble right">{t}</div>', unsafe_allow_html=True)

# ---------- Utils ----------
def make_ticket(prefix="NC"):
    return f"{prefix}-{datetime.now().strftime('%y%m%d')}-{random.randint(1000,9999)}"

def normalize(txt:str)->str:
    return re.sub(r"\s+", " ", txt.strip().lower())

def contains_any(text, keys):
    t = normalize(text)
    return any(k in t for k in keys)

# ---------- NC jurisdiction config ----------
NC_JURIS_CONFIG = {
    "Morrisville": {
        "pothole": {
            "description": "Report a pothole or road issue on Town-owned roads",
            "fields": ["street_address", "description", "photo_url_optional"],
            "link": "https://www.morrisvillenc.gov/services/report-a-problem-with/town-owned-roadways",
            "sla_days": 5,
        },
        "trash_schedule": {
            "description": "Find trash & recycling pickup day (Open Data reference)",
            "fields": ["street_address", "zip_optional"],
            "link": "https://opendata.townofmorrisville.org/explore/dataset/town-resources/api/",
        },
        "noise_complaint": {
            "description": "Report excessive noise (route via Town portal)",
            "fields": ["location", "description"],
            "link": "https://www.morrisvillenc.gov/services/report-a-problem-with/town-owned-roadways",
        },
        "streetlight": {
            "description": "Report a streetlight outage",
            "fields": ["nearest_address", "pole_number_optional", "description"],
            "link": "https://www.morrisvillenc.gov/services/report-a-problem-with/town-owned-roadways",
            "sla_days": 7,
        },
        "stray_animal": {
            "description": "Report a stray or lost animal",
            "fields": ["location", "animal_type", "description"],
            "link": "https://www.morrisvillenc.gov/services/report-a-problem-with/town-owned-roadways",
        },
        "general_info": {
            "description": "General Town information & datasets",
            "fields": [],
            "link": "https://opendata.townofmorrisville.org",
        },
    },

    # Examples (replace with official links as you confirm them)
    "Raleigh": {
        "pothole": {"description":"Report a pothole or street maintenance issue",
                    "fields":["street_address","description","photo_url_optional"],
                    "link":"https://raleighnc.gov/"},
        "trash_schedule":{"description":"Find trash & recycling day",
                          "fields":["street_address","zip_optional"],
                          "link":"https://raleighnc.gov/"},
        "noise_complaint":{"description":"Report noise disturbance",
                           "fields":["location","description"],
                           "link":"https://raleighnc.gov/"},
        "streetlight":{"description":"Report a streetlight outage",
                       "fields":["nearest_address","description"],
                       "link":"https://raleighnc.gov/"},
        "general_info":{"description":"General city information","fields":[],"link":"https://raleighnc.gov/"},
    },

    "Durham": {
        "pothole": {"description":"Report pothole or roadway issue",
                    "fields":["street_address","description","photo_url_optional"],
                    "link":"https://durhamnc.gov/"},
        "trash_schedule":{"description":"Find trash & recycling day",
                          "fields":["street_address","zip_optional"],
                          "link":"https://durhamnc.gov/"},
        "noise_complaint":{"description":"Report noise disturbance","fields":["location","description"],"link":"https://durhamnc.gov/"},
        "streetlight":{"description":"Report a streetlight outage","fields":["nearest_address","description"],"link":"https://durhamnc.gov/"},
        "general_info":{"description":"General city information","fields":[],"link":"https://durhamnc.gov/"},
    },

    "_DEFAULT": {
        "pothole": {"description":"Report a pothole or road issue",
                    "fields":["street_address","description","photo_url_optional"],
                    "link":"https://www.ncdot.gov/contact/Pages/default.aspx"},
        "trash_schedule":{"description":"Find trash & recycling pickup day (check your city’s sanitation page)",
                          "fields":["street_address","zip_optional"],
                          "link":"https://www.nc.gov/"},
        "noise_complaint":{"description":"Report noise disturbance","fields":["location","description"],"link":"https://www.nc.gov/"},
        "streetlight":{"description":"Report a streetlight outage","fields":["nearest_address","description"],"link":"https://www.ncdot.gov/"},
        "stray_animal":{"description":"Report a stray or lost animal","fields":["location","animal_type","description"],"link":"https://www.nc.gov/"},
        "general_info":{"description":"General information","fields":[],"link":"https://www.nc.gov/"},
    }
}
NC_CITIES = sorted([c for c in NC_JURIS_CONFIG.keys() if c != "_DEFAULT"])

def make_city_profile(city="Morrisville", state="North Carolina"):
    base = NC_JURIS_CONFIG.get(city, NC_JURIS_CONFIG["_DEFAULT"])
    services = {k: dict(v) for k, v in base.items()}  # shallow copy
    return {"meta": {"city": city, "state": state}, "services": services}

# ---------- Geocoding (US Census, no key) ----------
CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"

def geocode_address(raw: str, city_hint: str | None, state_hint: str = "North Carolina"):
    """
    Returns dict with matched address, city, state, zip, lon(x), lat(y) or None if not found.
    """
    oneline = raw if not city_hint else f"{raw}, {city_hint}, {state_hint}"
    try:
        r = requests.get(
            CENSUS_URL,
            params={"address": oneline, "benchmark": "Public_AR_Current", "format": "json"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        matches = data.get("result", {}).get("addressMatches", [])
        if not matches:
            # Try again without hint if we used it
            if city_hint:
                r2 = requests.get(
                    CENSUS_URL,
                    params={"address": raw, "benchmark": "Public_AR_Current", "format": "json"},
                    timeout=10,
                )
                r2.raise_for_status()
                data = r2.json()
                matches = data.get("result", {}).get("addressMatches", [])
                if not matches:
                    return None
            else:
                return None

        m = matches[0]
        comps = m.get("addressComponents", {})
        coords = m.get("coordinates", {})
        return {
            "matched": m.get("matchedAddress"),
            "city": comps.get("city"),
            "state": comps.get("state"),
            "zip": comps.get("zip"),
            "lon": coords.get("x"),
            "lat": coords.get("y"),
        }
    except Exception:
        return None

# ---------- Simple rules NLU ----------
INTENT_PATTERNS = [
    ("pothole", ["pothole", "road hole", "asphalt", "road damage", "street crack"]),
    ("trash_schedule", ["trash", "garbage", "recycle", "pickup", "collection", "bin"]),
    ("noise_complaint", ["noise", "loud", "party", "music", "construction noise"]),
    ("streetlight", ["streetlight", "light out", "lamp", "street light"]),
    ("stray_animal", ["stray", "dog", "cat", "animal control", "lost pet"]),
    ("general_info", ["info", "information", "hours", "phone", "contact", "permit", "parks"]),
]
REQUIRED_FIELDS = {
    "pothole": ["street_address", "description"],
    "trash_schedule": ["street_address"],
    "noise_complaint": ["location", "description"],
    "streetlight": ["nearest_address"],
    "stray_animal": ["location", "animal_type"],
}
FIELD_QUESTIONS = {
    "street_address": "What is the street address?",
    "nearest_intersection": "What is the nearest intersection?",
    "description": "Please describe the issue briefly.",
    "photo_url_optional": "If you have a photo URL, share it (or say 'skip').",
    "zip_optional": "What is the ZIP code? (or say 'skip')",
    "incident_time": "When did this happen? (date & time)",
    "location": "Where did this occur? (address, landmark or intersection)",
    "pole_number_optional": "If you see a pole number, share it (or say 'skip').",
    "nearest_address": "What is the nearest address to the light?",
    "animal_type": "What kind of animal is it?",
}

def detect_intent(text:str):
    t = normalize(text)
    if "yes please adapt this to my city's open data and services categories" in t:
        return "adapt_city"
    for intent, keys in INTENT_PATTERNS:
        if contains_any(t, keys): return intent
    if t in ["help","menu","hi","hello","start"]: return "menu"
    return "unknown"

# ---------- Session ----------
if "city_cfg" not in st.session_state:      st.session_state.city_cfg = make_city_profile()
if "messages" not in st.session_state:      st.session_state.messages = []
if "active_intent" not in st.session_state: st.session_state.active_intent = None
if "pending_fields" not in st.session_state:st.session_state.pending_fields = []
if "filled_fields" not in st.session_state: st.session_state.filled_fields = {}
if "ticket_log" not in st.session_state:    st.session_state.ticket_log = []

# ---------- Helpers ----------
def show_menu():
    svcs = st.session_state.city_cfg["services"]
    bullets = "\n".join([f"- **{k}** — {v['description']}" for k,v in svcs.items()])
    tips = (
        "\n\n*Tip:* If the road is a **state highway** (I-40, US-64, NC-55, etc.), "
        "potholes/streetlights are often handled by **NCDOT**. We can still log your request and "
        "include the right link."
    )
    return "I can help with:\n" + bullets + tips + "\n\nTry: 'Report a pothole', 'Trash pickup day', 'Streetlight out', 'Stray dog', or 'General info'."

def next_slot_question():
    if not st.session_state.active_intent: return None
    req = REQUIRED_FIELDS.get(st.session_state.active_intent, [])
    svc_fields = st.session_state.city_cfg["services"][st.session_state.active_intent]["fields"]
    ordered = [f for f in req if f not in st.session_state.filled_fields] + \
              [f for f in svc_fields if f not in req and f not in st.session_state.filled_fields]
    st.session_state.pending_fields = ordered
    return FIELD_QUESTIONS.get(ordered[0], f"Provide {ordered[0]}:") if ordered else None

def maybe_ncdot_note(address:str)->str|None:
    a = normalize(address)
    if any(tag in a for tag in [" i-", " us-", " nc-"]) or any(hwy in a for hwy in ["i-40","i 40","nc 55","nc-55","us 1","us-1"]):
        return ("FYI: This looks like it may be on a **state-maintained road**. "
                "For state roads, the maintainer is often **NCDOT**. We’ll still file your note and "
                "include the NCDOT contact link in the ticket.")
    return None

def finalize_case():
    intent = st.session_state.active_intent
    meta = st.session_state.city_cfg["meta"]
    svc  = st.session_state.city_cfg["services"][intent]
    ticket_id = make_ticket(prefix=(meta["city"][:2] or "NC").upper())
    payload = dict(st.session_state.filled_fields)

    if intent in {"pothole","streetlight"}:
        addr = payload.get("street_address") or payload.get("nearest_address") or ""
        note = maybe_ncdot_note(addr)
        if note: payload["note"] = note

    st.session_state.ticket_log.append({
        "ticket_id": ticket_id, "service": intent, "city": meta["city"], "state": meta["state"],
        "payload": payload, "created_at": datetime.now().isoformat(timespec="seconds"),
    })
    msg = (f"✅ **Submitted** your *{intent.replace('_',' ')}* request.\n\n"
           f"- Ticket ID: **{ticket_id}**\n- City: **{meta['city']}, {meta['state']}**\n"
           f"- Intake fields: `{payload}`\n- Reference: {svc.get('link','(no link)')}\n")
    if "sla_days" in svc:
        msg += f"- Estimated resolution target: **~{svc['sla_days']} business days**\n"
    return msg + "\nAnything else I can do? Type `menu`."

# ---------- Dispatcher (no re-intent mid-form + address geocoding) ----------
def push_user_and_process(text: str):
    st.session_state.messages.append({"role": "user", "content": text})
    tnorm = normalize(text)

    # global commands
    if tnorm in {"reset","restart","start over"}:
        st.session_state.active_intent = None
        st.session_state.pending_fields = []
        st.session_state.filled_fields = {}
        st.session_state.messages.append({"role":"assistant","content":"✅ Reset. Type `menu` to start again."})
        return

    # mid-form
    if st.session_state.active_intent and st.session_state.pending_fields:
        if tnorm == "menu":
            st.session_state.messages.append({"role":"assistant","content": show_menu()})
            return
        if tnorm == "cancel":
            st.session_state.active_intent = None
            st.session_state.pending_fields = []
            st.session_state.filled_fields = {}
            st.session_state.messages.append({"role":"assistant","content":"Canceled. Type `menu` for options."})
            return

        field = st.session_state.pending_fields[0]
        val = text.strip()
        if tnorm == "skip" and field.endswith("_optional"):
            st.session_state.filled_fields[field] = None
        else:
            st.session_state.filled_fields[field] = val

        # 🔎 Real-time geocoding when an address field is provided
        if field in {"street_address", "nearest_address"} and val:
            meta = st.session_state.city_cfg["meta"]
            geo = geocode_address(val, meta.get("city"), meta.get("state", "North Carolina"))
            if geo:
                # Save standardized address + coordinates
                st.session_state.filled_fields["address_verified"] = {
                    "matched": geo["matched"], "city": geo["city"], "state": geo["state"],
                    "zip": geo["zip"], "lat": geo["lat"], "lon": geo["lon"]
                }
                # Tell the user what we matched
                lat = f"{geo['lat']:.5f}" if isinstance(geo.get("lat"), (int,float)) else geo.get("lat")
                lon = f"{geo['lon']:.5f}" if isinstance(geo.get("lon"), (int,float)) else geo.get("lon")
                st.session_state.messages.append({"role":"assistant",
                    "content": f"📍 I standardized the address to **{geo['matched']}** "
                               f"(lat {lat}, lon {lon})."})

                # Auto-switch city if we recognize a different NC city
                detected_city = (geo.get("city") or "").title()
                detected_state = geo.get("state")
                if detected_state in {"NC","North Carolina"} and detected_city and \
                   detected_city != meta["city"] and detected_city in NC_JURIS_CONFIG:
                    st.session_state.city_cfg = make_city_profile(detected_city, "North Carolina")
                    st.session_state.messages.append({"role":"assistant",
                        "content": f"🔁 Detected **{detected_city}, NC** from the address — "
                                   f"switched to that city’s services."})
            else:
                st.session_state.messages.append({"role":"assistant",
                    "content":"⚠️ I couldn’t verify that address. I’ll continue, but you can re-enter it if needed."})

        nxt = next_slot_question()
        if nxt:
            st.session_state.messages.append({"role":"assistant","content": nxt})
        else:
            msg = finalize_case()
            st.session_state.active_intent = None
            st.session_state.pending_fields = []
            st.session_state.filled_fields = {}
            st.session_state.messages.append({"role":"assistant","content": msg})
        return

    # fresh intent
    intent = detect_intent(text)
    if intent == "menu":
        st.session_state.messages.append({"role":"assistant","content": show_menu()})
        return
    if intent == "adapt_city":
        # “name is <City> in the state <State>”
        city, state = "Your City", "North Carolina"
        t = tnorm
        if "name is" in t and "in the state" in t:
            try:
                city = t.split("name is",1)[1].split("in the state",1)[0].strip(" .,:;").title()
                state = t.split("in the state",1)[1].strip(" .,:;").title()
            except Exception: pass
        st.session_state.city_cfg = make_city_profile(city, state)
        st.session_state.messages.append({"role":"assistant",
                                          "content": f"👍 Adapted to **{city}, {state}**. Type `menu`."})
        return

    if intent in st.session_state.city_cfg["services"]:
        st.session_state.active_intent = intent
        st.session_state.filled_fields = {}
        nxt = next_slot_question()
        if nxt:
            st.session_state.messages.append({"role":"assistant",
                "content": f"Okay, let's file a **{intent.replace('_',' ')}** request.\n\n{nxt}"})
        else:
            svc = st.session_state.city_cfg["services"][intent]
            st.session_state.messages.append({"role":"assistant",
                "content": f"**{intent.replace('_',' ').title()}** — {svc['description']}\n\nMore info: {svc.get('link','(no link)')}"})
        return

    st.session_state.messages.append({"role":"assistant",
        "content": "I’m not sure I understood. Type `menu`, or try 'Report a pothole', 'Trash pickup day', or 'Streetlight out'."})

# ---------- Sidebar ----------
with st.sidebar:
    st.markdown("## NC 311 Agent")
    meta = st.session_state.city_cfg["meta"]
    st.caption("Choose city (North Carolina). Each city can have custom workflows & links.")
    city_list = NC_CITIES or ["Morrisville"]
    try:
        idx = city_list.index(meta["city"]) if meta["city"] in city_list else 0
    except Exception:
        idx = 0
    selected_city = st.selectbox("City", city_list, index=idx)
    if st.button("Apply city"):
        st.session_state.city_cfg = make_city_profile(selected_city, "North Carolina")
        st.success(f"Adapted to {selected_city}, North Carolina")

    if st.session_state.ticket_log:
        st.divider(); st.markdown("**Recent Tickets**")
        for t in st.session_state.ticket_log[-6:][::-1]:
            st.write(f"• {t['ticket_id']} — {t['service']} — {t['city']}")

    st.divider()
    if st.button("🔄 Reset conversation"):
        st.session_state.messages = []
        st.session_state.active_intent = None
        st.session_state.pending_fields = []
        st.session_state.filled_fields = {}
        st.experimental_rerun()

# ---------- Main (input-first, then render) ----------
st.title("🧰 North Carolina 311 Agent")
bleft("To protect your personal data, please don’t share sensitive info (like full card details or SSN).")
bleft("Hello! I’m your NC 311 assistant. Type `menu` to see services or ask directly.")

if not any(m["role"]=="assistant" for m in st.session_state.messages):
    st.session_state.messages.append({"role":"assistant",
        "content":"Hi! Type `menu` for potholes, trash pickup, streetlight, stray animal, and more."})

user_input = st.chat_input("Type here…")
if user_input:
    bright(user_input)
    push_user_and_process(user_input)

for m in st.session_state.messages:
    (bright if m["role"]=="user" else bleft)(m["content"])

# ---------- Export CSV ----------
st.divider()
if st.session_state.ticket_log:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=["ticket_id","service","city","state","payload","created_at"])
    writer.writeheader()
    for r in st.session_state.ticket_log:
        writer.writerow(r)
    st.download_button("⬇️ Download tickets.csv", out.getvalue(), "tickets.csv", "text/csv")

