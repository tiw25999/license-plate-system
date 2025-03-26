from fastapi import APIRouter, Query, HTTPException, Path
from app.database import add_plate, get_plate, get_plates, search_plates
from datetime import datetime
import pytz
from typing import Optional, List
from pydantic import BaseModel, Field
import logging
import re

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

class SearchParams(BaseModel):
    search_term: Optional[str] = Field(None, description="คำค้นหาสำหรับทะเบียนรถ เช่น 'ABC'")
    start_date: Optional[str] = Field(None, description="วันที่เริ่มต้นในรูปแบบ DD/MM/YYYY")
    end_date: Optional[str] = Field(None, description="วันที่สิ้นสุดในรูปแบบ DD/MM/YYYY")
    limit: int = Field(500, ge=1, le=1000, description="จำนวนผลลัพธ์สูงสุด (1-1000)")

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
    """ดึงข้อมูลทะเบียนตามเลขทะเบียน หรือดึงทั้งหมดถ้าไม่ระบุ (จำกัด 500 รายการ)"""
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

@plates_router.post("/search", response_model=List[PlateModel])
async def search_plates_route(search_params: SearchParams):
    """
    ค้นหาทะเบียนตามเงื่อนไขต่างๆ:
    - ค้นหาทะเบียนที่คล้ายกัน (เช่น ค้นหา "ABC" จะได้ ABC0001, ABC1234, ฯลฯ)
    - ค้นหาตามช่วงวันที่ (เช่น 01/12/2001 ถึง 31/12/2005)
    - ผลลัพธ์จำกัดตามที่ระบุ (ค่าเริ่มต้น 500 รายการ)
    """
    try:
        # ตรวจสอบความถูกต้องของวันที่
        if search_params.start_date or search_params.end_date:
            date_pattern = r"^\d{2}/\d{2}/\d{4}$"
            
            if search_params.start_date and not re.match(date_pattern, search_params.start_date):
                raise HTTPException(status_code=400, detail="Start date must be in DD/MM/YYYY format")
                
            if search_params.end_date and not re.match(date_pattern, search_params.end_date):
                raise HTTPException(status_code=400, detail="End date must be in DD/MM/YYYY format")
            
            # ถ้ามีเฉพาะวันที่เริ่มต้นหรือวันที่สิ้นสุด ให้กำหนดอีกวันที่เป็นวันที่เดียวกัน
            if search_params.start_date and not search_params.end_date:
                search_params.end_date = search_params.start_date
            elif search_params.end_date and not search_params.start_date:
                search_params.start_date = search_params.end_date
        
        # เรียกใช้ฟังก์ชันค้นหา
        results = await search_plates(
            search_term=search_params.search_term,
            start_date=search_params.start_date,
            end_date=search_params.end_date,
            limit=search_params.limit
        )
        
        # แปลงผลลัพธ์เป็น PlateModel
        filtered_plates = []
        for plate in results:
            filtered_plates.append(PlateModel(
                plate=plate["plate"],
                timestamp=plate["timestamp"]
            ))
        
        return filtered_plates
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error searching plates: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error searching plates: {str(e)}")

# เพิ่ม endpoint สำหรับค้นหาด้วย URL พารามิเตอร์
@plates_router.get("/search", response_model=List[PlateModel])
async def search_plates_get(
    search_term: Optional[str] = Query(None, description="คำค้นหาสำหรับทะเบียนรถ เช่น 'ABC'"),
    start_date: Optional[str] = Query(None, description="วันที่เริ่มต้นในรูปแบบ DD/MM/YYYY"),
    end_date: Optional[str] = Query(None, description="วันที่สิ้นสุดในรูปแบบ DD/MM/YYYY"),
    limit: int = Query(500, ge=1, le=1000, description="จำนวนผลลัพธ์สูงสุด (1-1000)")
):
    """
    ค้นหาทะเบียนตามเงื่อนไขต่างๆด้วย GET method:
    - ค้นหาทะเบียนที่คล้ายกัน (เช่น ค้นหา "ABC" จะได้ ABC0001, ABC1234, ฯลฯ)
    - ค้นหาตามช่วงวันที่ (เช่น 01/12/2001 ถึง 31/12/2005)
    - ผลลัพธ์จำกัดตามที่ระบุ (ค่าเริ่มต้น 500 รายการ)
    """
    # สร้าง SearchParams จาก query parameters
    search_params = SearchParams(
        search_term=search_term,
        start_date=start_date,
        end_date=end_date,
        limit=limit
    )
    
    # เรียกใช้ฟังก์ชันค้นหาที่มีอยู่แล้ว
    return await search_plates_route(search_params)