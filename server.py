from fastapi import FastAPI
from pydantic import BaseModel
import sqlite3
from fastapi.openapi.utils import get_openapi

app = FastAPI()

# --- DB setup (create if not exists) ---
def init_db():
    conn = sqlite3.connect("dave_memory.db")
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT,
        text TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()

init_db()

def save_memory(role, text):
    conn = sqlite3.connect("dave_memory.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO memory (role, text) VALUES (?, ?)", (role, text))
    conn.commit()
    conn.close()

def get_memory(limit: int = 20):
    conn = sqlite3.connect("dave_memory.db")
    cursor = conn.cursor()
    cursor.execute("SELECT role, text, timestamp FROM memory ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [{"role": r, "text": t, "timestamp": ts} for r, t, ts in rows]

# --- Data model ---
class UserInput(BaseModel):
    text: str

# --- Routes ---
@app.get("/")
def root():
    return {"message": "Dave-PMEA is running 🚀"}

@app.get("/ping")
def ping():
    return {"status": "ok"}

@app.post("/dave")
def dave_endpoint(user: UserInput):
    user_text = user.text
    reply = f"Improved reply: {user_text}"

    # Save to DB
    save_memory("user", user_text)
    save_memory("assistant", reply)

    return {"reply": reply}

@app.get("/memory")
def read_memory(limit: int = 20):
    return get_memory(limit)

# --- OpenAPI "servers" fix so GPT Builder can import cleanly ---
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title="Dave-PMEA",
        version="0.1.0",
        routes=app.routes,
        description="OpenAPI for Dave-PMEA"
    )
    schema["servers"] = [{"url": "https://dave-pmea.onrender.com"}]
    app.openapi_schema = schema
    return app.openapi_schema

app.openapi = custom_openapi
