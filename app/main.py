# app/main.py

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.routes.plates import plates_router
from app.routes.auth import auth_router
import uvicorn
import logging
import time
import os
from dotenv import load_dotenv
from slowapi.extension import Limiter
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

# ตั้งค่า logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("license-plate-api")

# โหลด .env
load_dotenv()

app = FastAPI(title="License Plate API")

# ตั้ง rate limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# ===== CORS =====
# ใช้ ENV CORS_ORIGINS คั่นด้วยคอมมา เช่น:
# CORS_ORIGINS=https://your-frontend.onrender.com,http://localhost:3000
cors_origins_env = os.getenv("CORS_ORIGINS", "")
allow_origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]
if not allow_origins:
    # fallback ให้ dev ใช้ได้ ถ้ายังไม่ตั้ง ENV
    allow_origins = [
        "http://localhost:3000",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware วัดเวลาแต่ละ request
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    elapsed = time.time() - start
    response.headers["X-Process-Time"] = str(elapsed)
    logger.info(
        f"Path: {request.url.path} | Method: {request.method} | Time: {elapsed:.4f}s"
    )
    return response

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.on_event("startup")
async def startup_event():
    from app.database import get_plates
    try:
        plates = await get_plates()
        logger.info(f"เชื่อมต่อ Supabase สำเร็จ จำนวน plate ทั้งหมด: {len(plates)}")
    except Exception as e:
        logger.error(f"เชื่อมต่อ Supabase ล้มเหลว: {e}")

# เพิ่ม router ทั้งสองตัว
app.include_router(plates_router)  # prefix="/plates"
app.include_router(auth_router)    # prefix="/auth"

@app.get("/")
def read_root():
    return {"message": "License Plate API กำลังทำงาน"}

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)
