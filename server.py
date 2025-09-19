# server.py — Dave-PMEA API (ultra-safe, per-user memory)

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime
import sqlite3
import re

app = FastAPI(title="Dave-PMEA", description="PMEA demo API", version="1.0.1")

DB_PATH = "dave_memory.db"

# ---------- DB Setup ----------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Per-user memory store
    c.execute("""
    CREATE TABLE IF NOT EXISTS memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        role    TEXT NOT NULL,
        text    TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    # Users + moderation mode
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        age INTEGER,
        verified INTEGER DEFAULT 0,   -- 0/1
        mode TEXT                     -- child | teen | adult
    )
    """)
    conn.commit()
    conn.close()

init_db()

# ---------- Helpers ----------
def determine_mode(age: Optional[int]) -> Literal["child","teen","adult"]:
    if age is None:
        return "teen"  # default conservatively
    if age < 13:
        return "child"
    if age < 18:
        return "teen"
    return "adult"

def get_user(user_id: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, age, verified, mode FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {"user_id": row[0], "age": row[1], "verified": bool(row[2]), "mode": row[3]}

def upsert_user(user_id: str, age: Optional[int], verified: bool):
    mode = determine_mode(age)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO users(user_id, age, verified, mode)
        VALUES(?,?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET
            age=excluded.age,
            verified=excluded.verified,
            mode=excluded.mode
    """, (user_id, age, int(verified), mode))
    conn.commit()
    conn.close()
    return {"user_id": user_id, "age": age, "verified": verified, "mode": mode}

URL_RE = re.compile(r"https?://\S+")
EMAIL_RE = re.compile(r"\b[\w\.-]+@[\w\.-]+\.\w+\b")

def sanitize_for_teen(text: str) -> str:
    # strip links/emails, keep it short
    text = URL_RE.sub("[link removed]", text)
    text = EMAIL_RE.sub("[email removed]", text)
    text = text.strip()
    if len(text) > 240:
        text = text[:240] + "…"
    return text

def save_memory(user_id: str, role: Literal["user","assistant"], text: str, mode: str):
    # child: never store; teen: store sanitized short; adult: store as-is
    if mode == "child":
        return
    if mode == "teen":
        text = sanitize_for_teen(text)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO memory(user_id, role, text) VALUES (?,?,?)", (user_id, role, text))
    conn.commit()
    conn.close()

def pmea_reply(mode: str, message: str) -> str:
    # Minimal PMEA-style improvement with ultra-safe constraints by mode
    if mode == "child":
        # short, educational, no links/PII
        return ("Let's keep this simple and safe:\n"
                "• I can give you helpful, friendly info.\n"
                "• If you need anything private or complex, ask a trusted adult.\n"
                "• What would you like to learn about next?")
    if mode == "teen":
        # short, risk-reduced, no links, concise steps
        safe = sanitize_for_teen(message)
        return (f"Improved: {safe}\n"
                "Next: tell me your exact goal and deadline. I’ll give you a short plan.")
    # adult
    return (f"Improved reply: {message}\n"
            "Tip: next, tell me the exact task and target output.")

# ---------- Models ----------
class AgeVerifyIn(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=128)
    age: Optional[int] = Field(None, ge=0, le=120)

class ChatIn(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=128)
    message: str = Field(..., min_length=1)

# ---------- Endpoints ----------
@app.get("/")
def root():
    return {
        "message": "Dave-PMEA is running 🚀",
        "endpoints": {
            "GET /ping": "health ping",
            "GET /healthz": "health ping",
            "POST /age-verify": {"user_id": "abc", "age": 17},
            "POST /chat": {"user_id": "abc", "message": "Hello"},
            "GET /memory": "/memory?user_id=abc&limit=20"
        }
    }

@app.get("/ping")
def ping():
    return {"ok": True}

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.post("/age-verify")
def age_verify(payload: AgeVerifyIn):
    profile = upsert_user(payload.user_id, payload.age, verified=True)
    # child gets safest mode; teen/adult set accordingly
    return {"ok": True, "user": profile}

@app.post("/chat")
def chat(payload: ChatIn):
    # Load user or create a conservative default
    user = get_user(payload.user_id)
    if not user:
        user = upsert_user(payload.user_id, age=None, verified=False)
    mode = user["mode"]

    # Save the user message (unless child)
    save_memory(payload.user_id, "user", payload.message, mode)

    # Produce ultra-safe PMEA reply by mode
    reply = pmea_reply(mode, payload.message)

    # Save the assistant message (unless child)
    save_memory(payload.user_id, "assistant", reply, mode)

    return {"reply": reply, "mode": mode}

@app.get("/memory")
def get_memory(user_id: str, limit: int = 20):
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be 1..200")

    user = get_user(user_id)
    if not user:
        # No profile -> nothing stored
        return {"user_id": user_id, "memory": []}

    # child never shows anything
    if user["mode"] == "child":
        return {"user_id": user_id, "memory": []}

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT role, text, timestamp
        FROM memory
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
    """, (user_id, limit))
    rows = c.fetchall()
    conn.close()
    out = [{"role": r[0], "text": r[1], "timestamp": r[2]} for r in rows]
    return {"user_id": user_id, "memory": out}

# ---------- OpenAPI servers fix (so GPT Builder can import cleanly) ----------
from fastapi.openapi.utils import get_openapi
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
        description=app.description,
    )
    schema["servers"] = [{"url": "https://dave-pmea.onrender.com"}]  # <-- set to your Render URL
    app.openapi_schema = schema
    return app.openapi_schema

app.openapi = custom_openapi
