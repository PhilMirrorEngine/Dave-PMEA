from fastapi import FastAPI
from pydantic import BaseModel

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
    reply = f"Improved reply: {user_text} (Tip: give me your exact task + output target)"
    
    memory.append({"role": "user", "text": user_text})
    memory.append({"role": "assistant", "text": reply})

    return {
        "✅ Done": reply,
        "⏳ Next": "Your next input?",
        "🌌 Archive": memory[-2:],
    }
