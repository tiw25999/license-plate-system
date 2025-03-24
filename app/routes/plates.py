from fastapi import APIRouter, Query, HTTPException
from app.database import add_plate, get_plate, get_plates
from datetime import datetime
import pytz
from typing import Optional

plates_router = APIRouter()

@plates_router.post("/add_plate")
def add_plate_route(plate_number: str):
    """เพิ่มทะเบียนใหม่"""
    try:
        # สร้าง timestamp ในรูปแบบไทย
        thailand_tz = pytz.timezone('Asia/Bangkok')
        now = datetime.now(thailand_tz)
        timestamp = now.strftime("%d/%m/%Y %H:%M:%S")  # Thai format for display
        
        add_plate(plate_number, timestamp)
        return {
            "status": "success",
            "plate_number": plate_number,
            "timestamp": timestamp
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@plates_router.get("/get_plates")
def fetch_plate(plate_number: Optional[str] = Query(None)):
    """ดึงข้อมูลทะเบียนตามเลขทะเบียน หรือดึงทั้งหมดถ้าไม่ระบุ"""
    try:
        if plate_number:
            result = get_plate(plate_number)
            if result:
                return {"plate_number": result["plate"], "timestamp": result["timestamp"]}
            raise HTTPException(status_code=404, detail="Plate not found")
        else:
            plates = get_plates()
            # Filter out the id field from each plate record
            filtered_plates = []
            for plate in plates:
                filtered_plates.append({
                    "plate": plate["plate"],
                    "timestamp": plate["timestamp"]
                })
            return filtered_plates
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))