# app/main.py
from fastapi import FastAPI
from app.routes.plates import plates_router
# If you have auth routes:
# from app.routes.auth import auth_router
import uvicorn
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="License Plate API")

# Mount the routers with appropriate prefixes
app.include_router(plates_router, prefix="/plates", tags=["plates"])
# If you have auth routes:
# app.include_router(auth_router, prefix="/auth", tags=["auth"])

@app.get("/")
def read_root():
    return {"message": "License Plate API is running"}

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)