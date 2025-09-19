from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.openapi.utils import get_openapi

app = FastAPI()

# Simple PMEA loop state
memory = []

class UserInput(BaseModel):
    text: str

@app.get("/")
def root():
    return {"message": "Dave-PMEA is running 🚀"}

@app.post("/dave")
def dave_endpoint(user: UserInput):
    user_text = user.text
    reply = f"🪞 Improved reply: {user_text}"
    memory.append({"role": "user", "text": user_text})
    memory.append({"role": "assistant", "text": reply})
    return {
        "reply": reply,
        "Next": "Your next input?",
        "Archive": memory[-2:]
    }

@app.get("/ping")
def ping():
    return {"status": "ok"}

# --- OpenAPI "servers" fix so GPT Builder can import cleanly -------------
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
