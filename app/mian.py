from fastapi import FastAPI

app = FastAPI(title="Fintech Payments Lab")

@app.get("/health")
def health():
    return {"status": "ok"}
