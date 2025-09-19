# server.py — Dave-PMEA with per-user profiles + persistent memory (SQLite)

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from datetime import datetime
import sqlite3
from typing import Optional, List, Dict

# ------------ App meta ------------
APP_TITLE = "Dave-PMEA"
APP_DESC  = "PMEA demo API with per-user profile + persistent memory"
SERVER_URL = "https://dave-pmea.onrender.com"   # <— your Render URL

app = FastAPI(title=APP_TITLE, description=APP_DESC, version="1.0.0")

# ------------ DB setup ------------
DB_PATH = "dave_memory.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Users (profile required once per user)
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     TEXT PRIMARY KEY,
            name        TEXT,
            dob         TEXT,
            memory_name TEXT,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Memory shards (per user)
    c.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    TEXT,
            role       TEXT,        -- 'user' or 'assistant'
            text       TEXT,
            tags       TEXT,        -- optional (comma/JSON)
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit(); conn.close()

init_db()

# ------------ Helpers ------------
def upsert_user(user_id: str, name: str, dob: str, memory_name: str):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""
        INSERT INTO users (user_id, name, dob, memory_name)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
          name=excluded.name,
          dob=excluded.dob,
          memory_name=excluded.memory_name
    """, (user_id, name, dob, memory_name))
    conn.commit(); conn.close()

def user_exists(user_id: str) -> bool:
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone(); conn.close()
    return bool(row)

def save_memory(user_id: str, role: str, text: str, tags: Optional[str] = None):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""
        INSERT INTO memory (user_id, role, text, tags)
        VALUES (?, ?, ?, ?)
    """, (user_id, role, text, tags))
    conn.commit(); conn.close()

def fetch_memory(user_id: Optional[str], limit: int) -> List[Dict]:
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    if user_id:
        c.execute("""
            SELECT id, user_id, role, text, tags, created_at
            FROM memory
            WHERE user_id=?
            ORDER BY datetime(created_at) DESC
            LIMIT ?
        """, (user_id, limit))
    else:
        c.execute("""
            SELECT id, user_id, role, text, tags, created_at
            FROM memory
            ORDER BY datetime(created_at) DESC
            LIMIT ?
        """, (limit,))
    rows = c.fetchall(); conn.close()
    return [
        {"id": r[0], "user_id": r[1], "role": r[2], "text": r[3], "tags": r[4], "created_at": r[5]}
        for r in rows
    ]

# ------------ Models ------------
class SetupIn(BaseModel):
    user_id: str = Field(..., description="Unique id for this user (e.g., 'DavePhil-Master')")
    name: str   = Field(..., description="Display name")
    dob:  str   = Field(..., description="Date of birth in YYYY-MM-DD")
    memory_name: str = Field(..., description="Label for this user's memory (e.g., 'Phil Master Memory')")

class ChatIn(BaseModel):
    user: str   = Field(..., description="User id used at setup")
    message: str = Field(..., description="User message")

# ------------ Endpoints ------------
@app.get("/", response_class=HTMLResponse)
def root():
    return f"""
    <html><body style="font-family:system-ui">
      <p>✅ <b>{APP_TITLE}</b> is running.</p>
      <ul>
        <li>POST <code>/setup</code></li>
        <li>POST <code>/chat</code></li>
        <li>GET  <code>/memory</code></li>
        <li>GET  <code>/health</code></li>
      </ul>
    </body></html>
    """

@app.get("/health")
def health():
    return {"ok": True, "time": datetime.utcnow().isoformat()}

@app.post("/setup")
def setup_user(payload: SetupIn):
    upsert_user(payload.user_id, payload.name, payload.dob, payload.memory_name)
    return {"ok": True, "user_id": payload.user_id}

@app.post("/chat")
def chat_with_dave(payload: ChatIn):
    # ensure profile exists
    if not user_exists(payload.user):
        return {"ok": False, "error": "Profile not found. Call /setup first for this user."}
    # save user message
    save_memory(payload.user, "user", payload.message)
    # (Demo reply – your PMEA loop/LLM call would go here)
    reply = f"Improved reply: {payload.message}"
    # save assistant reply
    save_memory(payload.user, "assistant", reply)
    return {"reply": reply}

@app.get("/memory")
def get_memory(
    user_id: Optional[str] = Query(default=None, description="Filter by user id (optional)"),
    limit: int = Query(default=20, ge=1, le=200, description="Max rows (default 20)")
):
    rows = fetch_memory(user_id, limit)
    return {"ok": True, "count": len(rows), "rows": rows}

# ------------ OpenAPI 'servers' fix (for GPT Builder imports) ------------
from fastapi.openapi.utils import get_openapi
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=APP_TITLE,
        version="1.0.0",
        routes=app.routes,
        description=APP_DESC
    )
    schema["servers"] = [{"url": SERVER_URL}]
    app.openapi_schema = schema
    return app.openapi_schema
app.openapi = custom_openapi
