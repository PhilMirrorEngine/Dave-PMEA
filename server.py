# server.py — Dave-PMEA with profile gate + per-user memory (SQLite)

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from datetime import datetime
import sqlite3
import os

# ------------------------ App metadata ------------------------
APP_TITLE = "Dave-PMEA"
APP_DESC  = "PMEA demo API with profile gate + per-user memory"
# Set to your Render URL (no trailing slash)
SERVER_URL = os.getenv("SERVER_URL", "https://dave-pmea.onrender.com")

app = FastAPI(title=APP_TITLE, description=APP_DESC, version="1.0.0")

# ------------------------ DB setup ----------------------------
DB_PATH = "dave_memory.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Users table (profile gate)
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     TEXT PRIMARY KEY,
            name        TEXT,
            dob         TEXT,
            memory_name TEXT,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Memory shards
    c.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    TEXT,
            message    TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ------------------------ DB helpers --------------------------
def upsert_user(user_id: str, name: str, dob: str, memory_name: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO users (user_id, name, dob, memory_name)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            name=excluded.name,
            dob=excluded.dob,
            memory_name=excluded.memory_name
        """,
        (user_id, name, dob, memory_name),
    )
    conn.commit()
    conn.close()

def get_user(user_id: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, name, dob, memory_name, created_at FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "user_id": row[0],
        "name": row[1],
        "dob": row[2],
        "memory_name": row[3],
        "created_at": row[4],
    }

def save_memory(user_id: str, message: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO memory (user_id, message, created_at) VALUES (?, ?, ?)",
              (user_id, message, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

def fetch_memory(user_id: str | None = None, limit: int = 20):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if user_id:
        c.execute(
            "SELECT user_id, message, created_at FROM memory WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
    else:
        c.execute(
            "SELECT user_id, message, created_at FROM memory ORDER BY id DESC LIMIT ?",
            (limit,),
        )
    rows = c.fetchall()
    conn.close()
    return [{"user_id": r[0], "message": r[1], "created_at": r[2]} for r in rows]

# ------------------------ Models ------------------------------
class SetupIn(BaseModel):
    user_id: str = Field(..., description="Unique id for this user (e.g., 'DavePhil-Master').")
    name: str    = Field(..., description="Display name.")
    dob: str     = Field(..., description="Date of birth in YYYY-MM-DD.")
    memory_name: str = Field(..., description="Label for this user's memory (e.g., 'Phil Master Memory').")

class ChatIn(BaseModel):
    user: str     = Field(..., description="User id used at setup.")
    message: str  = Field(..., description="User message to store / respond to.")

class MemoryPost(BaseModel):
    user_id: str
    message: str

# ------------------------ Routes ------------------------------
@app.get("/", response_class=HTMLResponse)
def root():
    return """
    <h3>✅ Dave-PMEA is running.</h3>
    <ul>
      <li>GET <code>/ping</code></li>
      <li>POST <code>/setup</code> (user profile)</li>
      <li>POST <code>/chat</code> (logs + echoes reply)</li>
      <li>GET <code>/memory?user_id=...&limit=20</code></li>
      <li>POST <code>/memory</code> (save a shard)</li>
    </ul>
    """

@app.get("/ping")
def ping():
    return {"ok": True}

@app.post("/setup")
def setup_user(data: SetupIn):
    upsert_user(data.user_id, data.name, data.dob, data.memory_name)
    return {"success": True, "profile": data.dict()}

@app.post("/chat")
def chat_with_dave(data: ChatIn):
    # gate: must have profile first
    profile = get_user(data.user)
    if not profile:
        return {
            "success": False,
            "error": "Profile not found. Call POST /setup first.",
            "hint": {
                "endpoint": "/setup",
                "example": {
                    "user_id": "DavePhil-Master",
                    "name": "Phil",
                    "dob": "1981-04-01",
                    "memory_name": "Phil Master Memory"
                }
            }
        }

    # very simple "reply" + store as shard
    reply = f"Improved reply: {data.message}"
    # Save the user's message as a shard (you can also save the reply if you want)
    save_memory(data.user, data.message)
    return {"success": True, "reply": reply}

@app.get("/memory")
def get_memory(
    user_id: str | None = Query(default=None, description="Filter by user id"),
    limit: int = Query(default=20, ge=1, le=200, description="Max rows to return")
):
    rows = fetch_memory(user_id=user_id, limit=limit)
    return {"success": True, "memories": rows}

@app.post("/memory")
def add_memory(post: MemoryPost):
    # Ensure user exists
    if not get_user(post.user_id):
        raise HTTPException(status_code=404, detail="User profile not found. Call /setup first.")
    save_memory(post.user_id, post.message)
    return {"success": True, "saved": {"user_id": post.user_id, "message": post.message}}

# ------------------------ OpenAPI servers fix -----------------
from fastapi.openapi.utils import get_openapi

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=APP_TITLE,
        version="1.0.0",
        routes=app.routes,
        description=APP_DESC,
    )
    schema["servers"] = [{"url": SERVER_URL}]
    app.openapi_schema = schema
    return app.openapi_schema

app.openapi = custom_openapi
