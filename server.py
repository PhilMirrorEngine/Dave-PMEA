# server.py — Dave-PMEA (Ultra-Safe) with per-user memory, consent & purge
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from datetime import datetime, date
from typing import Optional, List, Literal, Dict, Any
import sqlite3
import re

APP_URL = "https://dave-pmea.onrender.com"  # <— set to your Render URL

app = FastAPI(title="Dave-PMEA", description="PMEA demo API (Ultra-Safe)", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],    # lock down to your domains later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------- DB -------------------------
DB_PATH = "dave_memory.db"

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = db(); cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
          user_id TEXT PRIMARY KEY,
          dob TEXT,                    -- YYYY-MM-DD
          age_mode TEXT,               -- child|teen|adult
          verified INTEGER DEFAULT 0,  -- 0|1
          guardian_consented INTEGER DEFAULT 0, -- 0|1 (for <13)
          created_ts TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id TEXT,
          role TEXT,                 -- user|assistant
          text TEXT,
          mode TEXT,                 -- snapshot at write
          ts TEXT
        )
    """)
    conn.commit(); conn.close()
init_db()

# ------------------------- Age/Mode helpers -------------------------
def years_from_dob(dob: str) -> int:
    try:
        born = date.fromisoformat(dob)
        today = date.today()
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    except Exception:
        return -1

def mode_from_age(age: int) -> Literal["child","teen","adult"]:
    if age < 0:   return "teen"
    if age < 13:  return "child"
    if age < 18:  return "teen"
    return "adult"

def upsert_user(user_id: str, dob: Optional[str], verified: bool, guardian_consented: Optional[bool] = None):
    age = years_from_dob(dob) if dob else -1
    mode = mode_from_age(age) if dob else "teen"
    cons = 1 if guardian_consented else 0
    conn = db(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO users (user_id, dob, age_mode, verified, guardian_consented, created_ts)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
          dob=excluded.dob,
          age_mode=excluded.age_mode,
          verified=excluded.verified,
          guardian_consented=COALESCE(NULLIF(excluded.guardian_consented,0), users.guardian_consented)
    """, (user_id, dob or "", mode, 1 if verified else 0, cons, datetime.utcnow().isoformat()+"Z"))
    conn.commit(); conn.close()
    return get_user(user_id)

def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT user_id, dob, age_mode, verified, guardian_consented, created_ts FROM users WHERE user_id=?", (user_id,))
    r = cur.fetchone(); conn.close()
    if not r: return None
    return {
        "user_id": r[0], "dob": r[1], "mode": r[2],
        "verified": bool(r[3]), "guardian_consented": bool(r[4]),
        "created_ts": r[5]
    }

def save_msg(user_id: str, role: str, text: str, mode: str):
    conn = db(); cur = conn.cursor()
    cur.execute("INSERT INTO messages (user_id, role, text, mode, ts) VALUES (?,?,?,?,?)",
                (user_id, role, text, mode, datetime.utcnow().isoformat()+"Z"))
    conn.commit(); conn.close()

def fetch_msgs(user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT role, text, ts, mode FROM messages WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))
    rows = cur.fetchall(); conn.close()
    return [{"role": r[0], "text": r[1], "timestamp": r[2], "mode": r[3]} for r in rows]

def purge_user(user_id: str) -> int:
    conn = db(); cur = conn.cursor()
    cur.execute("DELETE FROM messages WHERE user_id=?", (user_id,))
    n1 = cur.rowcount
    cur.execute("DELETE FROM users WHERE user_id=?", (user_id,))
    n2 = cur.rowcount
    conn.commit(); conn.close()
    return n1 + n2

# ------------------------- Safety rules -------------------------
SAFE_TOPICS_CHILD = {
    "space","planet","planets","science","stars","math","animals","history",
    "reading","homework","coding","programming","kindness","friendship","safety","exercise"
}
RISKY_TEEN_KEYWORDS = {
    "explicit","porn","gambling","hard drug","self-harm","suicide","extremist","bomb","weapon"
}

URL_RE = re.compile(r"(https?://\S+|www\.\S+)")
EMAIL_RE = re.compile(r"\b[\w\.-]+@[\w\.-]+\.\w{2,}\b")
PHONE_RE = re.compile(r"\b\+?\d[\d\s\-]{6,}\d\b")

def sanitize(text: str, strip_links=True, strip_pii=True, max_len=500) -> str:
    t = text[:max_len]
    if strip_links:
        t = URL_RE.sub("[link removed]", t)
    if strip_pii:
        t = EMAIL_RE.sub("[email removed]", t)
        t = PHONE_RE.sub("[phone removed]", t)
    return t

def teen_blocked(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in RISKY_TEEN_KEYWORDS)

# Replies (minimal; keep it ultra safe)
def reply_child(msg: str) -> str:
    return (
        "Kid-safe mode:\n"
        "• I'll explain simply and kindly.\n"
        "• No links or personal info.\n\n"
        f"You asked: “{sanitize(msg)}”. Let’s learn step by step! 😊"
    )

def reply_teen(msg: str) -> str:
    if teen_blocked(msg):
        return "I can’t help with that topic. Let’s keep it safe and educational."
    return (
        "Teen-safe answer:\n"
        f"• Your question: “{sanitize(msg)}”\n"
        "• I’ll keep things short, supportive, and age-appropriate."
    )

def reply_adult(msg: str) -> str:
    return f"Improved reply: {sanitize(msg, max_len=1200)}\nTip: next, tell me the exact task and target output."

# ------------------------- OpenAPI servers fix -------------------------
from fastapi.openapi.utils import get_openapi
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title="Dave-PMEA",
        version="1.1.0",
        routes=app.routes,
        description="OpenAPI for Dave-PMEA (Ultra-Safe)",
    )
    schema["servers"] = [{"url": APP_URL}]
    app.openapi_schema = schema
    return app.openapi_schema
app.openapi = custom_openapi

# ------------------------- Schemas -------------------------
class VerifyIn(BaseModel):
    user_id: str = Field(..., min_length=1)
    dob: str      # "YYYY-MM-DD"
    guardian_consented: Optional[bool] = False  # if under 13

class ConsentIn(BaseModel):
    user_id: str
    guardian_consented: bool

class ChatIn(BaseModel):
    user: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    dob: Optional[str] = None  # optional after first verify

class ChatOut(BaseModel):
    reply: str
    mode: Literal["child","teen","adult"]
    saved: bool

class PurgeIn(BaseModel):
    user_id: str

# ------------------------- Routes -------------------------
@app.get("/")
def root():
    return {
        "message": "Dave-PMEA (Ultra-Safe) is running 🚀",
        "endpoints": {
            "GET /ping": "health",
            "POST /age-verify": "{user_id, dob, guardian_consented?}",
            "POST /set-consent": "{user_id, guardian_consented}",
            "POST /chat": "{user, message, [dob]} (per-user safe behaviour + memory)",
            "GET /memory": "?user_id=...&limit=20",
            "DELETE /delete-my-data": "{user_id}"
        }
    }

@app.get("/ping")
def ping():
    return {"ok": True}

@app.post("/age-verify")
def age_verify(body: VerifyIn):
    profile = upsert_user(body.user_id, body.dob, verified=True, guardian_consented=body.guardian_consented)
    return {"ok": True, "user": profile}

@app.post("/set-consent")
def set_consent(body: ConsentIn):
    u = get_user(body.user_id)
    if not u:
        raise HTTPException(404, "user not found")
    upsert_user(body.user_id, u["dob"], verified=u["verified"], guardian_consented=body.guardian_consented)
    return {"ok": True, "user": get_user(body.user_id)}

@app.post("/chat", response_model=ChatOut)
def chat(body: ChatIn):
    # Ensure user exists / verify inline if first time
    u = get_user(body.user)
    if not u:
        u = upsert_user(body.user, body.dob or "", verified=bool(body.dob), guardian_consented=False)

    mode = u["mode"]
    msg  = body.message.strip()

    # CHILD: enforce topic whitelist + consent
    if mode == "child":
        allowed = any(tok in msg.lower() for tok in SAFE_TOPICS_CHILD)
        if not allowed:
            reply = ("I can’t talk about that. Please ask a trusted adult. "
                     "Would you like to learn about space, animals, math, coding, or reading instead?")
            # no storage for disallowed content
            return ChatOut(reply=reply, mode=mode, saved=False)

        if not u["guardian_consented"]:
            reply = ("I need a parent or guardian to give consent before we can chat normally. "
                     "They can do this at /set-consent. Here’s a safe mini-explanation while you wait:\n"
                     + reply_child(msg))
            # do not save anything for non-consented child
            return ChatOut(reply=reply, mode=mode, saved=False)

        # consented + allowed
        reply = reply_child(msg)
        save_msg(body.user, "user", sanitize(msg), mode)
        save_msg(body.user, "assistant", reply, mode)
        return ChatOut(reply=reply, mode=mode, saved=True)

    # TEEN: block risky, sanitize, but save memory
    if mode == "teen":
        r = reply_teen(msg)
        save_msg(body.user, "user", sanitize(msg), mode)
        save_msg(body.user, "assistant", r, mode)
        return ChatOut(reply=r, mode=mode, saved=True)

    # ADULT: normal behaviour
    r = reply_adult(msg)
    save_msg(body.user, "user", sanitize(msg, max_len=1200), mode)
    save_msg(body.user, "assistant", r, mode)
    return ChatOut(reply=r, mode=mode, saved=True)

@app.get("/memory")
def memory(user_id: str = Query(...), limit: int = Query(20, ge=1, le=200)):
    return {"user_id": user_id, "items": fetch_msgs(user_id, limit)}

@app.delete("/delete-my-data")
def delete_my_data(body: PurgeIn):
    deleted = purge_user(body.user_id)
    return {"ok": True, "deleted_rows": deleted}

# Minimal browser test page (optional)
@app.get("/test")
def test():
    return (
        "<h3>Dave-PMEA Ultra-Safe</h3>"
        "<p>Try: <code>/ping</code>, <code>/openapi.json</code></p>"
    )
