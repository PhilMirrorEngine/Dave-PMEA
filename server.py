# server.py  — Dave-PMEA with per-user memory (SQLite)
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from datetime import datetime, date
from typing import Optional, List, Literal, Dict, Any
import sqlite3
import json

APP_URL = "https://dave-pmea.onrender.com"  # <-- set to your Render URL

app = FastAPI(title="Dave-PMEA", description="PMEA demo API", version="1.0.0")

# ---------- CORS (lets your GPT Action call this API) ----------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # lock down later to your domains if you like
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- SQLite boot + helpers ----------
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
          dob TEXT,                      -- YYYY-MM-DD
          age_mode TEXT,                 -- 'child'|'teen'|'adult'
          verified INTEGER DEFAULT 0     -- 0|1
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id TEXT,
          role TEXT,                     -- 'user'|'assistant'
          text TEXT,
          mode TEXT,                     -- snapshot of age_mode at time of write
          ts TEXT                        -- ISO timestamp
        )
    """)
    conn.commit(); conn.close()

init_db()

def years_from_dob(dob: str) -> int:
    try:
        born = date.fromisoformat(dob)
        today = date.today()
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    except Exception:
        return -1

def mode_from_age(age: int) -> Literal["child","teen","adult"]:
    if age < 0:         return "teen"     # fallback
    if age < 13:        return "child"
    if age < 18:        return "teen"
    return "adult"

def save_user(user_id: str, dob: Optional[str], verified: bool) -> Dict[str, Any]:
    conn = db(); cur = conn.cursor()
    age = years_from_dob(dob) if dob else -1
    mode = mode_from_age(age) if dob else "teen"
    cur.execute("""
        INSERT INTO users (user_id, dob, age_mode, verified)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET dob=excluded.dob, age_mode=excluded.age_mode, verified=excluded.verified
    """, (user_id, dob or "", mode, 1 if verified else 0))
    conn.commit()
    cur.execute("SELECT user_id, dob, age_mode, verified FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return {"user_id": row[0], "dob": row[1], "mode": row[2], "verified": bool(row[3])}

def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT user_id, dob, age_mode, verified FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone(); conn.close()
    if not row: return None
    return {"user_id": row[0], "dob": row[1], "mode": row[2], "verified": bool(row[3])}

def save_msg(user_id: str, role: str, text: str, mode: str):
    conn = db(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO messages (user_id, role, text, mode, ts) VALUES (?,?,?,?,?)",
        (user_id, role, text, mode, datetime.utcnow().isoformat()+"Z")
    )
    conn.commit(); conn.close()

def fetch_msgs(user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    conn = db(); cur = conn.cursor()
    cur.execute(
        "SELECT role, text, ts, mode FROM messages WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, limit)
    )
    rows = cur.fetchall(); conn.close()
    return [{"role": r[0], "text": r[1], "timestamp": r[2], "mode": r[3]} for r in rows]

# ---------- OpenAPI servers fix (so GPT Actions can Import from URL cleanly) ----------
from fastapi.openapi.utils import get_openapi
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title="Dave-PMEA",
        version="1.0.0",
        routes=app.routes,
        description="OpenAPI for Dave-PMEA"
    )
    schema["servers"] = [{"url": APP_URL}]
    app.openapi_schema = schema
    return app.openapi_schema
app.openapi = custom_openapi

# ---------- Schemas ----------
class VerifyIn(BaseModel):
    user_id: str = Field(..., min_length=1)
    dob: str      # "YYYY-MM-DD"

class ChatIn(BaseModel):
    user: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    dob: Optional[str] = None  # optional after first verification

class ChatOut(BaseModel):
    reply: str
    mode: Literal["child","teen","adult"]
    saved: bool

# ---------- Policy-safe reply builders ----------
SAFE_TOPICS_CHILD = {
    "space","planets","science","math","animals","history","reading","study","homework","coding","kindness"
}

def reply_child(msg: str) -> str:
    # stripped-down, educational, no links, no PII
    return (
        "Here’s a kid-safe explanation:\n"
        "• Keep it simple and friendly.\n"
        "• If you asked something complex, I’ll explain the basics first.\n"
        "• If this topic isn’t child-appropriate, I’ll suggest talking to a trusted adult.\n\n"
        f"You said: “{msg}”\n"
        "Let’s learn step by step! 😊"
    )

def reply_teen(msg: str) -> str:
    # short, supportive, no explicit content, no profane language, minimal links
    return (
        "Here’s a teen-friendly answer:\n"
        f"• Your question: “{msg}”\n"
        "• I’ll keep it straightforward and bias-aware.\n"
        "• For sensitive topics, I’ll stay educational and safe."
    )

def reply_adult(msg: str) -> str:
    # normal behaviour (you can swap in the PMEA loop later)
    return f"Improved reply: {msg}\nTip: next, tell me the exact task and target output."

# ---------- Routes ----------
@app.get("/")
def root():
    return {
        "message": "Dave-PMEA is running 🚀",
        "endpoints": {
            "GET /ping": "health",
            "POST /age-verify": "{user_id, dob}",
            "POST /chat": "{user, message, [dob]} (auto-saves memory)",
            "GET /memory": "?user_id=...&limit=20 (recent to older)"
        }
    }

@app.get("/ping")
def ping():
    return {"ok": True}

@app.post("/age-verify")
def age_verify(body: VerifyIn):
    # record + set mode
    profile = save_user(body.user_id, body.dob, verified=True)
    return {"ok": True, "user": profile}

@app.post("/chat", response_model=ChatOut)
def chat(body: ChatIn):
    # 1) get or create user
    u = get_user(body.user)
    if not u:
        # if first time and dob supplied, verify now; else default teen until verified
        if body.dob:
            u = save_user(body.user, body.dob, verified=True)
        else:
            u = save_user(body.user, "", verified=False)

    mode = u["mode"]

    # 2) build policy-safe reply per mode
    msg = body.message.strip()

    if mode == "child":
        # hard topic gate (example)
        lowered = msg.lower()
        allowed = any(t in lowered for t in SAFE_TOPICS_CHILD)
        if not allowed:
            reply = (
                "I can’t talk about that. For safety, please ask a trusted adult. "
                "Want to learn about space, animals, math, or coding instead?"
            )
        else:
            reply = reply_child(msg)

    elif mode == "teen":
        reply = reply_teen(msg)
    else:
        reply = reply_adult(msg)

    # 3) save both turns
    save_msg(body.user, "user", msg, mode)
    save_msg(body.user, "assistant", reply, mode)

    return ChatOut(reply=reply, mode=mode, saved=True)

@app.get("/memory")
def memory(user_id: str = Query(...), limit: int = Query(20, ge=1, le=200)):
    # per-user recall
    return {"user_id": user_id, "items": fetch_msgs(user_id, limit)}

# ---------- Minimal /test page (optional) ----------
@app.get("/test", response_class=None)
def test():
    html = f"""
    <html><head><title>Dave-PMEA Reply</title></head>
    <body style="font-family:sans-serif;max-width:720px;margin:40px auto;line-height:1.5">
      <h2>Dave-PMEA</h2>
      <p>Try endpoints:</p>
      <ul>
        <li><a href="{APP_URL}/ping">/ping</a></li>
        <li><a href="{APP_URL}/memory?user_id=demo">/memory?user_id=demo</a></li>
        <li><a href="{APP_URL}/openapi.json">/openapi.json</a></li>
      </ul>
      <p>POST to <code>/age-verify</code> and <code>/chat</code> with JSON bodies.</p>
    </body></html>
    """
    return html
