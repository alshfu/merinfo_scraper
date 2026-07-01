"""
Merinfo CRM — professionell dashboard över företagsdata i MongoDB.

Kör med:  streamlit run dashboard.py

Databaser:
  merinfo_db.companies  — scrapad företagsdata (org.nr, ekonomi, styrelse ...)
  crm_db.users          — säljare/managers
  crm_db.leads          — bearbetning: status, historik, uppföljning
"""

import datetime
import re

import bcrypt
import certifi
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from bson import ObjectId
from pymongo import MongoClient

# ─────────────────────────────────────────────────────────────────────────────
#  Konfiguration
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Merinfo CRM",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded",
)

LEAD_STATUSES = [
    "NEW", "CONTACTED", "NO_ANSWER", "THINKING",
    "INTERESTED", "NEGOTIATION", "WON", "LOST", "NOT_INTERESTED",
]
STATUS_COLORS = {
    "NEW": "#64748b", "CONTACTED": "#0ea5e9", "NO_ANSWER": "#f59e0b",
    "THINKING": "#8b5cf6", "INTERESTED": "#14b8a6", "NEGOTIATION": "#6366f1",
    "WON": "#16a34a", "LOST": "#dc2626", "NOT_INTERESTED": "#94a3b8",
}
ACTION_TYPES = ["CALL", "EMAIL", "MEETING", "NOTE", "STATUS_CHANGE"]
PAGE_SIZE = 20

# Villkor: har telefon kopplad till företaget ELLER en kopplad person
PHONE_OR = {
    "$or": [
        {"phone": {"$nin": ["", None]}},
        {"all_phones.0": {"$exists": True}},
        {"board_members.personal_data.phones.0": {"$exists": True}},
    ]
}

SORT_OPTIONS = {
    "Namn (A–Ö)": ("name", 1),
    "Namn (Ö–A)": ("name", -1),
    "Nyast registrerad": ("registered_date", -1),
    "Äldst registrerad": ("registered_date", 1),
}

# CSS för mobilanpassning: stapla kolumner och kompaktare layout på små skärmar
MOBILE_CSS = """
<style>
/* Större, touch-vänliga knappar (WCAG ~44px tap-yta) */
.stButton button { min-height: 2.6rem; border-radius: 10px; font-weight: 600; }
[data-testid="stMetricValue"] { font-size: 1.3rem; }
a[href^='tel:'] { display: inline-block; padding: 3px 0; }

@media (max-width: 640px) {
  /* Stapla kolumner på mobil */
  [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; gap: 0.3rem !important; }
  [data-testid="stColumn"] { min-width: 100% !important; flex: 1 1 100% !important; }
  [data-testid="stMetricValue"] { font-size: 1.1rem !important; }
  h1 { font-size: 1.4rem !important; }
  .block-container { padding: 1rem 0.8rem !important; }
  .stButton button { width: 100% !important; }
  a[href^='tel:'] { font-size: 1.3rem !important; }
}
</style>
"""


# ─────────────────────────────────────────────────────────────────────────────
#  Databas
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_resource
def get_client():
    uri = st.secrets["MONGO_URI"]
    client = MongoClient(uri, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=8000)
    client.admin.command("ping")
    return client


def companies_col():
    return get_client()["merinfo_db"]["companies"]


def leads_col():
    return get_client()["crm_db"]["leads"]


def users_col():
    return get_client()["crm_db"]["users"]


# ─────────────────────────────────────────────────────────────────────────────
#  Inloggning
# ─────────────────────────────────────────────────────────────────────────────
def verify_login(username, password):
    """Returnerar användardokumentet vid korrekt lösenord, annars None."""
    user = users_col().find_one({"username": username})
    if not user or not user.get("password_hash"):
        return None
    try:
        ok = bcrypt.checkpw(password.encode("utf-8"),
                            user["password_hash"].encode("utf-8"))
    except (ValueError, TypeError):
        return None
    return user if ok else None


def require_login():
    """Visar inloggningsformulär och stoppar appen tills man är inloggad.

    Kan stängas av genom att sätta REQUIRE_LOGIN = false i .streamlit/secrets.toml.
    """
    if not st.secrets.get("REQUIRE_LOGIN", True):
        st.session_state.setdefault("auth_user", {
            "username": "gäst", "full_name": "Gäst", "role": "öppen"})
        return
    if st.session_state.get("auth_user"):
        return

    st.title("🔐 Merinfo CRM — Logga in")
    with st.form("login_form"):
        username = st.text_input("Användarnamn")
        password = st.text_input("Lösenord", type="password")
        submitted = st.form_submit_button("Logga in", type="primary")
    if submitted:
        user = verify_login(username.strip(), password)
        if user:
            st.session_state.auth_user = {
                "username": user["username"],
                "full_name": user.get("full_name", user["username"]),
                "role": user.get("role", "user"),
            }
            st.rerun()
        else:
            st.error("Fel användarnamn eller lösenord.")
    st.stop()


# ─────────────────────────────────────────────────────────────────────────────
#  Hjälpfunktioner
# ─────────────────────────────────────────────────────────────────────────────
def parse_sv_number(value):
    """'1 889' -> 1889.0, '104,28 %' -> 104.28, '37 325 tkr' -> 37325.0."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value)
    s = s.replace("tkr", "").replace("kr", "").replace("%", "")
    s = s.replace(" ", "").replace(" ", "").strip()
    s = s.replace(",", ".")
    if s in ("", "-", "n/a", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fmt_tkr(value):
    n = parse_sv_number(value)
    if n is None:
        return "–"
    return f"{n:,.0f} tkr".replace(",", " ")


def fmt_phones(phones):
    """phones kan vara strängar eller {'number','user'}-objekt."""
    out = []
    for p in phones or []:
        if isinstance(p, dict):
            num = p.get("number", "")
            who = p.get("user")
            out.append(f"{num} ({who})" if who else num)
        else:
            out.append(str(p))
    return ", ".join(x for x in out if x) or "–"


def norm_number(number):
    """Rensar ett telefonnummer till tel:-format (endast siffror och +)."""
    return re.sub(r"[^\d+]", "", str(number or ""))


def tel_html(number, size="1.15rem"):
    """Klickbar tap-to-call-länk (fungerar på mobil)."""
    href = norm_number(number)
    return (f"<a href='tel:{href}' style='font-size:{size};font-weight:600;"
            f"text-decoration:none;color:#2563eb'>📞 {number}</a>")


def collect_phones(doc):
    """Alla nummer kopplade till företaget + personer. Deduplicerat.

    Returnerar list av {number, name, source, meta}.
    """
    seen = set()
    out = []

    def add(number, name, source, meta=""):
        key = norm_number(number)
        if not key or key in seen:
            return
        seen.add(key)
        out.append({"number": number, "name": name or "", "source": source, "meta": meta})

    for p in doc.get("all_phones") or []:
        if isinstance(p, dict):
            bits = [x for x in (p.get("type"), p.get("operator"))
                    if x and x not in ("Kontakta oss!", "")]
            add(p.get("number"), p.get("user") or doc.get("name"),
                "Företag", " · ".join(bits))
        else:
            add(p, doc.get("name"), "Företag")
    add(doc.get("phone"), doc.get("name"), "Företag")

    for m in doc.get("board_members") or []:
        mname = m.get("name")
        for p in (m.get("personal_data") or {}).get("phones") or []:
            if isinstance(p, dict):
                add(p.get("number"), p.get("user") or mname, "Styrelse")
            else:
                add(p, mname, "Styrelse")
    return out


def clean_industry(v):
    """'Butiker, Shopping > Butiker, Shopping' -> 'Butiker, Shopping'."""
    if not v:
        return v
    return v.split(">")[0].strip()


def has_any_phone(doc):
    """True om telefon finns på företaget eller någon kopplad person."""
    if doc.get("phone"):
        return True
    if doc.get("all_phones"):
        return True
    for m in doc.get("board_members") or []:
        if (m.get("personal_data") or {}).get("phones"):
            return True
    return False


def status_badge(status):
    color = STATUS_COLORS.get(status, "#64748b")
    return (
        f'<span style="background:{color};color:#fff;padding:2px 10px;'
        f'border-radius:12px;font-size:0.78rem;font-weight:600;">{status}</span>'
    )


@st.cache_data(ttl=300)
def get_filter_options():
    col = companies_col()
    # bransch: visa städat namn, men behåll råvärdet för query
    industry_map = {}
    for raw in col.distinct("industry"):
        if raw:
            industry_map[clean_industry(raw)] = raw
    return {
        "county": sorted(x for x in col.distinct("county") if x),
        "company_form": sorted(x for x in col.distinct("company_form") if x),
        "status": sorted(x for x in col.distinct("status") if x),
        "industry_map": dict(sorted(industry_map.items())),
    }


@st.cache_data(ttl=60)
def get_stats():
    return {
        "companies": companies_col().count_documents({}),
        "leads": leads_col().count_documents({}),
        "users": users_col().count_documents({}),
    }


@st.cache_data(ttl=120)
def get_users_map():
    """{_id_str: label}."""
    out = {}
    for u in users_col().find({}, {"full_name": 1, "username": 1}):
        label = u.get("full_name") or u.get("username") or str(u["_id"])
        out[str(u["_id"])] = label
    return out


def build_query(search, county, form, status, industry, phone_filter):
    conds = []
    if search:
        s = re.escape(search.strip())
        conds.append({"$or": [
            {"name": {"$regex": s, "$options": "i"}},
            {"org_number": {"$regex": s, "$options": "i"}},
        ]})
    if county:
        conds.append({"county": {"$in": county}})
    if form:
        conds.append({"company_form": {"$in": form}})
    if status:
        conds.append({"status": {"$in": status}})
    if industry:
        conds.append({"industry": {"$in": industry}})
    if phone_filter == "with":
        conds.append(PHONE_OR)
    elif phone_filter == "without":
        conds.append({"$nor": [PHONE_OR]})
    if not conds:
        return {}
    if len(conds) == 1:
        return conds[0]
    return {"$and": conds}


@st.cache_data(ttl=30)
def search_companies(query, page, sort_field, sort_dir):
    col = companies_col()
    total = col.count_documents(query)
    proj = {
        "org_number": 1, "name": 1, "county": 1, "municipality": 1,
        "company_form": 1, "status": 1, "industry": 1, "financials": 1,
        "phone": 1, "all_phones": 1, "board_members.personal_data.phones": 1,
    }
    cursor = (
        col.find(query, proj)
        .sort(sort_field, sort_dir)
        .skip(page * PAGE_SIZE)
        .limit(PAGE_SIZE)
    )
    return list(cursor), total


def latest_financials(financials):
    """Senaste periodens ekonomi -> (period, dict)."""
    if not financials:
        return None, {}
    period = sorted(financials.keys())[-1]
    return period, financials[period]


def get_lead(org_number):
    return leads_col().find_one({"org_number": org_number})


def leads_status_map(org_numbers):
    """{org_number: status} för en lista av org.nr."""
    out = {}
    for l in leads_col().find(
        {"org_number": {"$in": org_numbers}}, {"org_number": 1, "status": 1}
    ):
        out[l["org_number"]] = l.get("status")
    return out


# ─────────────────────────────────────────────────────────────────────────────
#  Vy: detaljsida
# ─────────────────────────────────────────────────────────────────────────────
def render_overview(doc):
    st.markdown(f"### {doc.get('name', '(namnlöst)')}")
    cols = st.columns([1, 1, 1, 1])
    cols[0].metric("Org.nummer", doc.get("org_number", "–"))
    cols[1].metric("Bolagsform", doc.get("company_form", "–"))
    cols[2].metric("Län", doc.get("county", "–"))
    cols[3].metric("Kommun", doc.get("municipality", "–"))

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Status:** " + (doc.get("status") or "–"))
        st.markdown("**Bransch:** " + (doc.get("industry") or "–"))
        st.markdown("**Registrerad:** " + (doc.get("registered_date") or "–"))
        st.markdown("**F-skatt:** " + (doc.get("f_skatt") or "–")
                    + "   ·   **Moms:** " + (doc.get("vat_registered") or "–"))
    with c2:
        st.markdown("**Adress:** " + (doc.get("address") or "–"))
        st.markdown("**Telefon:** " + (doc.get("phone") or "–"))
        st.markdown("**Bankgiro:** " + (doc.get("bankgiro") or "–"))
        if doc.get("url"):
            st.markdown(f"[🔗 Merinfo-profil]({doc['url']})")

    if doc.get("description"):
        st.info("📝 " + doc["description"])
    if doc.get("signatory_rules"):
        st.caption("Firmateckning: " + doc["signatory_rules"])
    sni = doc.get("sni_codes") or []
    if sni:
        st.markdown("**SNI-koder:** " + " · ".join(sni))


def render_financials(doc):
    financials = doc.get("financials") or {}
    if not financials:
        st.info("Ingen ekonomisk data.")
        return

    periods = sorted(financials.keys())
    rows = []
    for p in periods:
        row = {"Period": p}
        for k, v in financials[p].items():
            row[k] = parse_sv_number(v)
        rows.append(row)
    df = pd.DataFrame(rows).set_index("Period")

    # Diagram: omsättning + resultat
    oms_key = next((c for c in df.columns if "msättning" in c), None)
    res_key = next((c for c in df.columns if "esultat" in c), None)
    if oms_key or res_key:
        fig = go.Figure()
        if oms_key:
            fig.add_bar(x=df.index, y=df[oms_key], name="Omsättning (tkr)",
                        marker_color="#2563eb")
        if res_key:
            fig.add_trace(go.Scatter(
                x=df.index, y=df[res_key], name="Resultat e. finansnetto (tkr)",
                mode="lines+markers", marker_color="#16a34a", yaxis="y2",
            ))
        fig.update_layout(
            height=340, margin=dict(l=0, r=0, t=20, b=0),
            legend=dict(orientation="h", y=1.15),
            yaxis=dict(title="Omsättning"),
            yaxis2=dict(title="Resultat", overlaying="y", side="right"),
        )
        st.plotly_chart(fig, width="stretch")

    st.markdown("**Nyckeltal per period**")
    st.dataframe(df.T, width="stretch")

    kf = doc.get("key_figures") or {}
    if kf:
        st.markdown("**Key figures**")
        kf_rows = []
        for p in sorted(kf.keys()):
            r = {"Period": p}
            r.update(kf[p])
            kf_rows.append(r)
        st.dataframe(pd.DataFrame(kf_rows).set_index("Period").T,
                     width="stretch")


def render_board(doc):
    members = doc.get("board_members") or []
    if not members:
        st.info("Inga styrelsemedlemmar registrerade.")
        return
    st.caption(f"{len(members)} personer")
    for m in members:
        pd_ = m.get("personal_data") or {}
        header = f"👤 {m.get('name', '—')}"
        if m.get("roles"):
            header += f"  ·  {m['roles']}"
        if m.get("age"):
            header += f"  ·  {m['age']} år"
        with st.expander(header):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Roll:** " + (m.get("roles") or "–"))
                st.markdown("**Tillsatt:** " + (m.get("appointed_date") or "–"))
                st.markdown("**Ort:** " + (pd_.get("city") or m.get("city") or "–"))
                st.markdown("**Adress:** " + (pd_.get("address") or "–"))
                st.markdown("**Civilstånd:** " + (pd_.get("civil_status") or "–"))
            with c2:
                phones = pd_.get("phones") or []
                if phones:
                    st.markdown("**Telefon:**")
                    for p in phones:
                        num = p.get("number") if isinstance(p, dict) else p
                        st.markdown(tel_html(num), unsafe_allow_html=True)
                else:
                    st.markdown("**Telefon:** –")
                vehicles = pd_.get("vehicles") or []
                if vehicles:
                    st.markdown("**Fordon:**")
                    for v in vehicles:
                        st.markdown(f"- 🚗 {v}")
                else:
                    st.markdown("**Fordon:** –")
            url = pd_.get("url") or m.get("profile_url")
            if url:
                st.markdown(f"[🔗 Personprofil]({url})")


def render_phones(doc):
    """Alla telefonnummer kopplade till företaget — tap-to-call på mobil."""
    phones = collect_phones(doc)
    if not phones:
        st.info("Inga telefonnummer hittades för detta företag.")
        return
    st.caption(f"{len(phones)} nummer — tryck på ett nummer för att ringa 📱")
    for p in phones:
        with st.container(border=True):
            st.markdown(tel_html(p["number"], size="1.4rem"), unsafe_allow_html=True)
            sub = " · ".join(x for x in [p["name"], p["source"], p["meta"]] if x)
            if sub:
                st.caption(sub)


def render_lead(doc):
    org = doc["org_number"]
    lead = get_lead(org)
    users_map = get_users_map()
    user_ids = list(users_map.keys())

    if lead:
        st.markdown("**Nuvarande status:** " + status_badge(lead.get("status", "NEW")),
                    unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        assigned = str(lead.get("assigned_to")) if lead.get("assigned_to") else None
        c1.markdown("**Tilldelad:** " + (users_map.get(assigned, "–")))
        nf = lead.get("next_follow_up")
        c2.markdown("**Nästa uppföljning:** "
                    + (nf.strftime("%Y-%m-%d") if isinstance(nf, datetime.datetime) else "–"))

        st.markdown("#### 📜 Historik")
        for h in reversed(lead.get("history", [])):
            d = h.get("date")
            when = d.strftime("%Y-%m-%d %H:%M") if isinstance(d, datetime.datetime) else "?"
            line = f"**{when}** · `{h.get('action', '')}` — {h.get('details', '')}"
            st.markdown(line)
            if h.get("note"):
                st.caption("💬 " + h["note"])
            if h.get("new_status"):
                st.caption("→ status: " + h["new_status"])
    else:
        st.info("Detta företag är ännu inte i CRM:et. Skapa en lead nedan.")

    st.markdown("#### ➕ Registrera aktivitet")
    with st.form(f"lead_form_{org}", clear_on_submit=True):
        cc1, cc2 = st.columns(2)
        action = cc1.selectbox("Typ", ACTION_TYPES)
        cur_status = lead.get("status") if lead else "NEW"
        new_status = cc2.selectbox(
            "Ny status", LEAD_STATUSES,
            index=LEAD_STATUSES.index(cur_status) if cur_status in LEAD_STATUSES else 0,
        )
        cc3, cc4 = st.columns(2)
        assign_default = 0
        if lead and str(lead.get("assigned_to")) in user_ids:
            assign_default = user_ids.index(str(lead.get("assigned_to")))
        assign_to = cc3.selectbox(
            "Tilldela", user_ids, index=assign_default if user_ids else 0,
            format_func=lambda x: users_map.get(x, x),
        ) if user_ids else None
        follow_up = cc4.date_input(
            "Nästa uppföljning",
            value=(lead.get("next_follow_up").date()
                   if lead and isinstance(lead.get("next_follow_up"), datetime.datetime)
                   else datetime.date.today() + datetime.timedelta(days=7)),
        )
        details = st.text_input("Detaljer", placeholder="Kort beskrivning av vad som hände")
        note = st.text_area("Anteckning", placeholder="Fri anteckning ...")
        submitted = st.form_submit_button("💾 Spara", type="primary")

    if submitted:
        now = datetime.datetime.utcnow()
        entry = {"date": now, "action": action,
                 "details": details or f"{action}", "note": note,
                 "new_status": new_status}
        set_fields = {
            "status": new_status,
            "next_follow_up": datetime.datetime.combine(follow_up, datetime.time()),
        }
        if assign_to:
            set_fields["assigned_to"] = ObjectId(assign_to)
        leads_col().update_one(
            {"org_number": org},
            {
                "$set": set_fields,
                "$push": {"history": entry},
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        st.success("Sparat!")
        st.cache_data.clear()
        st.rerun()


def render_detail(org_number):
    if st.button("← Tillbaka till listan"):
        st.session_state.selected_org = None
        st.rerun()

    doc = companies_col().find_one({"org_number": org_number})
    if not doc:
        st.error("Företaget hittades inte.")
        return

    lead = get_lead(org_number)
    if lead:
        st.markdown("Lead-status: " + status_badge(lead.get("status", "NEW")),
                    unsafe_allow_html=True)

    tabs = st.tabs(["🏢 Översikt", "📞 Telefonnummer", "📊 Ekonomi",
                    "👥 Styrelse & personer", "🎯 Lead / CRM"])
    with tabs[0]:
        render_overview(doc)
    with tabs[1]:
        render_phones(doc)
    with tabs[2]:
        render_financials(doc)
    with tabs[3]:
        render_board(doc)
    with tabs[4]:
        render_lead(doc)


# ─────────────────────────────────────────────────────────────────────────────
#  Vy: lista
# ─────────────────────────────────────────────────────────────────────────────
def sidebar_filters():
    """Bygger sidopanelens filter och returnerar (query, sort_field, sort_dir)."""
    opts = get_filter_options()
    industry_map = opts["industry_map"]

    st.sidebar.header("🔎 Sök & filter")
    search = st.sidebar.text_input("Sök namn / org.nr")

    st.sidebar.markdown("**🏭 Bransch**")
    industry_labels = st.sidebar.multiselect(
        "Bransch", list(industry_map.keys()), label_visibility="collapsed")
    industry = [industry_map[lbl] for lbl in industry_labels]

    st.sidebar.markdown("**📞 Telefon**")
    phone_choice = st.sidebar.radio(
        "Telefon", ["Alla", "Endast med telefon", "Endast utan telefon"],
        label_visibility="collapsed",
    )
    phone_filter = {"Alla": None, "Endast med telefon": "with",
                    "Endast utan telefon": "without"}[phone_choice]

    with st.sidebar.expander("Fler filter"):
        county = st.multiselect("Län", opts["county"])
        form = st.multiselect("Bolagsform", opts["company_form"])
        status = st.multiselect("Bolagsstatus", opts["status"])

    sort_label = st.sidebar.selectbox("↕️ Sortera efter", list(SORT_OPTIONS.keys()))
    sort_field, sort_dir = SORT_OPTIONS[sort_label]

    filt_key = (search, tuple(county), tuple(form), tuple(status),
                tuple(industry), phone_filter, sort_label)
    if filt_key != st.session_state.get("last_filter"):
        st.session_state.page = 0
        st.session_state.last_filter = filt_key

    query = build_query(search, county, form, status, industry, phone_filter)
    return query, sort_field, sort_dir


def render_pagination(total):
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    pc1, pc2, pc3 = st.columns([1, 2, 1])
    with pc1:
        if st.session_state.page > 0 and st.button("◀ Föregående"):
            st.session_state.page -= 1
            st.rerun()
    with pc2:
        st.markdown(
            f"<div style='text-align:center'>Sida {st.session_state.page + 1} / {pages}</div>",
            unsafe_allow_html=True,
        )
    with pc3:
        if st.session_state.page < pages - 1 and st.button("Nästa ▶"):
            st.session_state.page += 1
            st.rerun()


def render_list(query, sort_field, sort_dir):
    results, total = search_companies(query, st.session_state.page, sort_field, sort_dir)
    st.subheader(f"Företag — {total:,}".replace(",", " ") + " träffar")

    if not results:
        st.warning("Inga träffar.")
        return

    lead_map = leads_status_map([r["org_number"] for r in results])

    for r in results:
        with st.container(border=True):
            phone_icon = "📞" if has_any_phone(r) else ""
            lstat = lead_map.get(r["org_number"])
            badge = status_badge(lstat) if lstat else ""
            _, fin = latest_financials(r.get("financials"))
            oms = fin.get("Omsättning") if fin else None
            res = fin.get("Resultat efter finansnetto") if fin else None

            c1, c2 = st.columns([4, 1])
            with c1:
                st.markdown(
                    f"**{r.get('name', '—')}** {phone_icon}&nbsp;&nbsp;{badge}",
                    unsafe_allow_html=True,
                )
                st.caption(
                    f"{r.get('org_number', '')} · "
                    f"{r.get('county') or '–'} · {r.get('company_form') or '–'}"
                )
                st.caption(
                    f"{clean_industry(r.get('industry')) or '–'}  ·  "
                    f"Oms: {fmt_tkr(oms)} · Res: {fmt_tkr(res)}"
                )
            with c2:
                if st.button("Öppna →", key="open_" + r["org_number"],
                             width="stretch"):
                    st.session_state.selected_org = r["org_number"]
                    st.rerun()

    render_pagination(total)


def render_ringlista(query, sort_field, sort_dir):
    """Ringlista: alla telefonnummer för de filtrerade företagen — tap-to-call."""
    results, total = search_companies(query, st.session_state.page, sort_field, sort_dir)
    st.subheader(f"📞 Ringlista — {total:,}".replace(",", " ") + " företag")
    st.caption("Tips: aktivera filtret **Endast med telefon** i sidopanelen. "
               "Tryck på ett nummer för att ringa.")

    if not results:
        st.warning("Inga träffar.")
        return

    lead_map = leads_status_map([r["org_number"] for r in results])

    for r in results:
        phones = collect_phones(r)
        with st.container(border=True):
            c1, c2 = st.columns([4, 1])
            with c1:
                lstat = lead_map.get(r["org_number"])
                badge = status_badge(lstat) if lstat else ""
                st.markdown(f"**{r.get('name', '—')}** {badge}",
                            unsafe_allow_html=True)
                st.caption(f"{r.get('org_number', '')} · "
                           f"{clean_industry(r.get('industry')) or '–'}")
            with c2:
                if st.button("Öppna →", key="rl_" + r["org_number"],
                             width="stretch"):
                    st.session_state.selected_org = r["org_number"]
                    st.rerun()
            if phones:
                for p in phones:
                    sub = " · ".join(x for x in [p["name"], p["source"]] if x)
                    st.markdown(
                        tel_html(p["number"])
                        + f" <span style='color:#64748b;font-size:0.85rem'>{sub}</span>",
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("Inga nummer registrerade")

    render_pagination(total)


# ─────────────────────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    st.session_state.setdefault("selected_org", None)
    st.session_state.setdefault("page", 0)

    st.markdown(MOBILE_CSS, unsafe_allow_html=True)

    require_login()

    with st.sidebar:
        u = st.session_state.auth_user
        st.markdown(f"👤 **{u['full_name']}**  ·  _{u['role']}_")
        if st.button("Logga ut"):
            st.session_state.auth_user = None
            st.rerun()
        st.divider()

    st.title("🏢 Merinfo CRM")

    try:
        stats = get_stats()
        m1, m2, m3 = st.columns(3)
        m1.metric("Företag", f"{stats['companies']:,}".replace(",", " "))
        m2.metric("Leads i arbete", stats["leads"])
        m3.metric("Användare", stats["users"])
    except Exception as e:
        st.error(f"Kunde inte ansluta till MongoDB: {e}")
        st.stop()

    st.divider()

    if st.session_state.selected_org:
        render_detail(st.session_state.selected_org)
        return

    # Filter i sidopanelen — delas av båda vyerna
    query, sort_field, sort_dir = sidebar_filters()

    mode = st.radio(
        "Vy", ["🏢 Företag", "📞 Ringlista"],
        horizontal=True, label_visibility="collapsed",
    )
    if mode == "📞 Ringlista":
        render_ringlista(query, sort_field, sort_dir)
    else:
        render_list(query, sort_field, sort_dir)


if __name__ == "__main__":
    main()
