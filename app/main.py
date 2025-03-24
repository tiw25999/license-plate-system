# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes.plates import plates_router
import uvicorn
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="License Plate API")

# เพิ่ม CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ในโปรดักชันควรจำกัดเฉพาะโดเมนที่อนุญาต
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# เพิ่ม health check endpoint
@app.get("/health")
def health_check():
    return {"status": "ok"}

# เพิ่ม startup event สำหรับการทดสอบการเชื่อมต่อ
@app.on_event("startup")
async def startup_event():
    try:
        # ทดสอบการเชื่อมต่อกับ Supabase
        from app.config import supabase_client
        response = supabase_client.table("plates").select("count", count="exact").execute()
        print(f"Supabase connection test: Successfully connected. Count: {response.count if hasattr(response, 'count') else 'unknown'}")
    except Exception as e:
        print(f"Supabase connection test failed: {e}")
        # ไม่ raise exception เพื่อให้แอปยังคงทำงานต่อไปได้
        pass

# Mount the routers with appropriate prefixes
app.include_router(plates_router, prefix="/plates", tags=["plates"])

@app.get("/")
def read_root():
    return {"message": "License Plate API is running"}

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)