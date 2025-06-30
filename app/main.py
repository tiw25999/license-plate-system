from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.routes.plates import plates_router
from app.routes.auth import auth_router
import uvicorn
from dotenv import load_dotenv
import logging
import time
from starlette.concurrency import run_in_threadpool

from slowapi.extension import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware

# ตั้งค่า logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI(title="License Plate API")

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# ✅ CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://license-plate-web-production.up.railway.app",
        "http://localhost:3000"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
    max_age=86400,
)

# ✅ Middleware สำหรับวัดเวลา
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    logger.info(
        f"Path: {request.url.path} | "
        f"Method: {request.method} | "
        f"Time: {process_time:.4f}s"
    )
    return response

# ✅ Health check
@app.get("/health")
def health_check():
    return {"status": "ok"}

# ✅ Startup event
@app.on_event("startup")
async def startup_event():
    try:
        from app.database import get_plates
        plates = await get_plates()
        logger.info(f"Supabase connection test: Successfully connected. Count: {len(plates)}")
    except Exception as e:
        logger.error(f"Supabase connection test failed: {e}")
        pass

# ✅ Mount routers
app.include_router(plates_router, prefix="/plates", tags=["plates"])
app.include_router(auth_router, prefix="", tags=["auth"])

# ✅ Root
@app.get("/")
def read_root():
    return {"message": "License Plate API is running"}

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
