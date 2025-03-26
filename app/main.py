from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.routes.plates import plates_router
import uvicorn
from dotenv import load_dotenv
import logging
import time
from starlette.concurrency import run_in_threadpool

# ตั้งค่า logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI(title="License Plate API")

# เพิ่ม CORS middleware ที่ปลอดภัยมากขึ้น
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://license-plate-web-production.up.railway.app", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],  # ระบุเฉพาะ methods ที่จำเป็น
    allow_headers=["*"],
    max_age=86400,  # cache CORS preflight requests for 24 hours
)

# เพิ่ม middleware สำหรับบันทึกเวลาที่ใช้ในการทำงาน
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    
    # ดำเนินการแบบ non-blocking
    response = await call_next(request)
    
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    
    # บันทึก request ที่สำคัญ
    logger.info(
        f"Path: {request.url.path} | "
        f"Method: {request.method} | "
        f"Time: {process_time:.4f}s"
    )
    
    return response

# เพิ่ม health check endpoint
@app.get("/health")
def health_check():
    return {"status": "ok"}

# เพิ่ม startup event สำหรับการทดสอบการเชื่อมต่อ
@app.on_event("startup")
async def startup_event():
    try:
        # ทดสอบการเชื่อมต่อกับ Supabase
        from app.database import get_plates
        plates = await get_plates()
        logger.info(f"Supabase connection test: Successfully connected. Count: {len(plates)}")
    except Exception as e:
        logger.error(f"Supabase connection test failed: {e}")
        # ไม่ raise exception เพื่อให้แอปยังคงทำงานต่อไปได้
        pass

# Mount the routers
app.include_router(plates_router, prefix="/plates", tags=["plates"])

@app.get("/")
def read_root():
    return {"message": "License Plate API is running"}

if __name__ == "__main__":
    # สำหรับการพัฒนาในเครื่อง
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)