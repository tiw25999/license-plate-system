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
    start_month: Optional[str] = Field(None, description="เดือนเริ่มต้น (1-12)")
    end_month: Optional[str] = Field(None, description="เดือนสิ้นสุด (1-12)")
    start_year: Optional[str] = Field(None, description="ปีเริ่มต้น (เช่น 2023)")
    end_year: Optional[str] = Field(None, description="ปีสิ้นสุด (เช่น 2023)")
    limit: int = Field(5000, ge=1, le=5000, description="จำนวนผลลัพธ์สูงสุด (1-5000)")

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
    """ดึงข้อมูลทะเบียนตามเลขทะเบียน หรือดึงทั้งหมด 1000 รายการล่าสุดถ้าไม่ระบุ"""
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
    - ค้นหาทะเบียนที่มีตัวอักษรหรือตัวเลขที่ต้องการปรากฏอยู่ (ไม่จำเป็นต้องขึ้นต้น)
    - ค้นหาตามช่วงวันที่ เช่น วันที่ 01/01/1990 ถึง 31/12/2023
    - ค้นหาตามช่วงเดือน เช่น เดือน 1 ปี 1990 ถึง เดือน 12 ปี 2023
    - ค้นหาตามช่วงปี เช่น ปี 1990 ถึง 2023
    """
    try:
        # ตรวจสอบความถูกต้องของรูปแบบวันที่
        if search_params.start_date or search_params.end_date:
            date_pattern = r"^\d{2}/\d{2}/\d{4}$"
            
            if (search_params.start_date and not re.match(date_pattern, search_params.start_date)) or \
               (search_params.end_date and not re.match(date_pattern, search_params.end_date)):
                raise HTTPException(status_code=400, detail="รูปแบบวันที่ไม่ถูกต้อง ต้องเป็น DD/MM/YYYY")
                
            # ถ้ามีเพียงค่าใดค่าหนึ่ง ให้แจ้งเตือน
            if bool(search_params.start_date) != bool(search_params.end_date):
                raise HTTPException(status_code=400, detail="ต้องระบุทั้งวันที่เริ่มต้นและวันที่สิ้นสุด")
        
        # ตรวจสอบความถูกต้องของเดือนและปี
        if search_params.start_month or search_params.end_month or search_params.start_year or search_params.end_year:
            # ตรวจสอบว่ามีข้อมูลครบถ้วนหรือไม่
            has_start_month = bool(search_params.start_month)
            has_end_month = bool(search_params.end_month)
            has_start_year = bool(search_params.start_year)
            has_end_year = bool(search_params.end_year)
            
            # กรณีค้นหาตามช่วงเดือน
            if has_start_month or has_end_month:
                if not (has_start_month and has_end_month and has_start_year and has_end_year):
                    raise HTTPException(status_code=400, detail="ต้องระบุทั้งเดือนและปีเริ่มต้น รวมถึงเดือนและปีสิ้นสุด")
                
                # ตรวจสอบความถูกต้องของค่าเดือน
                try:
                    start_month = int(search_params.start_month)
                    end_month = int(search_params.end_month)
                    
                    if start_month < 1 or start_month > 12 or end_month < 1 or end_month > 12:
                        raise HTTPException(status_code=400, detail="เดือนต้องเป็นตัวเลข 1-12")
                except ValueError:
                    raise HTTPException(status_code=400, detail="เดือนต้องเป็นตัวเลข 1-12")
            
            # กรณีค้นหาตามช่วงปี
            elif has_start_year or has_end_year:
                if not (has_start_year and has_end_year):
                    raise HTTPException(status_code=400, detail="ต้องระบุทั้งปีเริ่มต้นและปีสิ้นสุด")
                
                # ตรวจสอบความถูกต้องของค่าปี
                try:
                    int(search_params.start_year)
                    int(search_params.end_year)
                except ValueError:
                    raise HTTPException(status_code=400, detail="ปีต้องเป็นตัวเลข")
        
        # เรียกใช้ฟังก์ชันค้นหา
        results = await search_plates(
            search_term=search_params.search_term,
            start_date=search_params.start_date,
            end_date=search_params.end_date,
            start_month=search_params.start_month,
            end_month=search_params.end_month,
            start_year=search_params.start_year,
            end_year=search_params.end_year,
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

@plates_router.get("/search", response_model=List[PlateModel])
async def search_plates_get(
    search_term: Optional[str] = Query(None, description="คำค้นหาสำหรับทะเบียนรถ เช่น 'A', '123'"),
    start_date: Optional[str] = Query(None, description="วันที่เริ่มต้นในรูปแบบ DD/MM/YYYY"),
    end_date: Optional[str] = Query(None, description="วันที่สิ้นสุดในรูปแบบ DD/MM/YYYY"),
    start_month: Optional[str] = Query(None, description="เดือนเริ่มต้น (1-12)"),
    end_month: Optional[str] = Query(None, description="เดือนสิ้นสุด (1-12)"),
    start_year: Optional[str] = Query(None, description="ปีเริ่มต้น (เช่น 1990)"),
    end_year: Optional[str] = Query(None, description="ปีสิ้นสุด (เช่น 2023)"),
    limit: int = Query(1000, ge=1, le=1000, description="จำนวนผลลัพธ์สูงสุด (1-1000)")
):
    """
    ค้นหาทะเบียนตามเงื่อนไขต่างๆด้วย GET method:
    - ค้นหาทะเบียนที่มีตัวอักษรหรือตัวเลขที่ต้องการปรากฏอยู่ (ไม่จำเป็นต้องขึ้นต้น)
    - ค้นหาตามช่วงวันที่ เดือน ปี
    """
    # สร้าง SearchParams จาก query parameters
    search_params = SearchParams(
        search_term=search_term,
        start_date=start_date,
        end_date=end_date,
        start_month=start_month,
        end_month=end_month,
        start_year=start_year,
        end_year=end_year,
        limit=limit
    )
    
    # เรียกใช้ฟังก์ชันค้นหาที่มีอยู่แล้ว
    return await search_plates_route(search_params)