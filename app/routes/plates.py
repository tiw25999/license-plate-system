from fastapi import APIRouter, Query, HTTPException
from app.database import add_plate, get_plate, get_plates
from datetime import datetime
import pytz
from typing import Optional, List
from pydantic import BaseModel
import logging

# ตั้งค่า logging
logger = logging.getLogger(__name__)

plates_router = APIRouter()

class PlateModel(BaseModel):
    plate: str
    timestamp: str

class PlateResponse(BaseModel):
    status: str
    plate_number: str
    timestamp: str

@plates_router.post("/add_plate", response_model=PlateResponse)
async def add_plate_route(plate_number: str):
    """เพิ่มทะเบียนใหม่"""
    try:
        # สร้าง timestamp ในรูปแบบไทย
        thailand_tz = pytz.timezone('Asia/Bangkok')
        now = datetime.now(thailand_tz)
        timestamp = now.strftime("%d/%m/%Y %H:%M:%S")  # Thai format for display
        
        await add_plate(plate_number, timestamp)
        return {
            "status": "success",
            "plate_number": plate_number,
            "timestamp": timestamp
        }
    except Exception as e:
        logger.error(f"Error adding plate: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@plates_router.get("/get_plates", response_model=List[PlateModel])
async def fetch_plates(plate_number: Optional[str] = Query(None)):
    """ดึงข้อมูลทะเบียนตามเลขทะเบียน หรือดึงทั้งหมดถ้าไม่ระบุ"""
    try:
        if plate_number:
            result = await get_plate(plate_number)
            if result:
                return [PlateModel(plate=result["plate"], timestamp=result["timestamp"])]
            raise HTTPException(status_code=404, detail="Plate not found")
        else:
            plates = await get_plates()
            # Filter out the id field from each plate record
            filtered_plates = []
            for plate in plates:
                filtered_plates.append(PlateModel(
                    plate=plate["plate"],
                    timestamp=plate["timestamp"]
                ))
            return filtered_plates
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching plates: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))