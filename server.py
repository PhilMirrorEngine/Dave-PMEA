# server.py — Dave-PMEA with profile gate + per-user memory (SQLite)
# ---------------------------------------------------------------
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from datetime import datetime
import sqlite3
import re

APP_TITLE = "Dave-PMEA"
APP_DESC  = "PMEA demo API with profile gate + per-user memory"
SERVER_URL = "https://dave-pmea.onrender.com"  # <-- set to your Render URL

app = FastAPI(title=APP_TITLE, description=APP_DESC, version="1.0.0")

# ------------- DB SETUP -------------------------------------------------------
DB_PATH = "dave_memory.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # users = who is chatting (profile required once)
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id      TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            dob          TEXT NOT NULL,       -- YYYY-MM-DD
            memory_name  TEXT NOT NULL,
            created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # memory = per-user chat shards
    c.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     TEXT NOT NULL,
            role        TEXT NOT NULL,        -- "user" | "assistant"
            text        TEXT NOT NULL,
            timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

def save_memory(user_id: str, role: str, text: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO memory (user_id, role, text) VALUES (?,?,?)", (user_id, role, text))
    conn.commit()
    conn.close()

def fetch_memory(user_id: str, limit: int = 20):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT role, text, timestamp FROM memory WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    )
    rows = c.fetchall()
    conn.close()
    return [{"role": r[0], "text": r[1], "timestamp": r[2]} for r in rows]

def get_user(user_id: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, name, dob, memory_name, created_at FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {"user_id": row[0], "name": row[1], "dob": row[2], "memory_name": row[3], "created_at": row[4]}

def upsert_user(user_id: str, name: str, dob: str, memory_name: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO users (user_id, name, dob, memory_name)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            name=excluded.name,
            dob=excluded.dob,
            memory_name=excluded.memory_name
    """, (user_id, name, dob, memory_name))
    conn.commit()
    conn.close()

# ------------- MODELS ---------------------------------------------------------
class SetupIn(BaseModel):
    user_id: str = Field(..., description="Unique id for this user (e.g., 'DavePhil-Master')")
    name: str = Field(..., description="Display name")
    dob: str = Field(..., description="YYYY-MM-DD")
    memory_name: str = Field(..., description="Label for this user's memory (e.g., 'Phil Master Memory')")

class ChatIn(BaseModel):
    user: str = Field(..., description="user_id used in /setup")
    message: str = Field(..., description="User message")

# ------------- OPENAPI servers fix (so GPT Builder can import cleanly) -------
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
