import os
from dotenv import load_dotenv
from app.config import supabase_client
from datetime import datetime, timedelta
import pytz
import asyncio
from cachetools import TTLCache
import logging
import time
import re

# ตั้งค่า logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# โหลดค่าตัวแปรแวดล้อม
load_dotenv()

# สร้าง cache
plates_cache = TTLCache(maxsize=1000, ttl=300)  # cache เก็บข้อมูลทะเบียน 5 นาที
search_cache = TTLCache(maxsize=100, ttl=60)  # cache สำหรับการค้นหา 1 นาที

# ตัวแปรสำหรับบันทึกเวลาใช้งาน
last_db_access = 0
min_db_access_interval = 0.1  # ขั้นต่ำ 100ms ระหว่างการเรียก

# ฟังก์ชันสำหรับแปลงรูปแบบวันที่ไทยเป็น timestamp
def parse_thai_date(date_str):
    """แปลงวันที่รูปแบบไทย (DD/MM/YYYY) เป็น datetime object"""
    try:
        day, month, year = date_str.split('/')
        return datetime(int(year), int(month), int(day))
    except Exception as e:
        logger.error(f"Error parsing date: {date_str}, {e}")
        return None

# ฟังก์ชันสำหรับแปลงเดือนและปีเป็น datetime object
def parse_month_year(month_str, year_str):
    """แปลงเดือนและปีเป็น datetime object"""
    try:
        month = int(month_str)
        year = int(year_str)
        if month < 1 or month > 12:
            logger.error(f"Invalid month: {month}")
            return None
        return datetime(year, month, 1)
    except Exception as e:
        logger.error(f"Error parsing month/year: {month_str}/{year_str}, {e}")
        return None

# ฟังก์ชันสำหรับแปลงเวลาให้เป็น string
def format_time(hour):
    """แปลงชั่วโมงเป็น string รูปแบบ HH:00:00"""
    try:
        hour = int(hour)
        if hour < 0 or hour > 23:
            logger.error(f"Invalid hour: {hour}")
            return None
        return f"{hour:02d}:00:00"
    except Exception as e:
        logger.error(f"Error formatting time: {hour}, {e}")
        return None

async def add_plate(plate_number, timestamp=None):
    """เพิ่มทะเบียนไปที่ Supabase ด้วย async"""
    global last_db_access
    
    if timestamp is None:
        # สร้าง timestamp ในรูปแบบไทย
        thailand_tz = pytz.timezone('Asia/Bangkok')
        now = datetime.now(thailand_tz)
        timestamp = now.strftime("%d/%m/%Y %H:%M:%S")  # Thai format for display
    
    try:
        # ป้องกันการเรียกฐานข้อมูลถี่เกินไป
        current_time = time.time()
        if current_time - last_db_access < min_db_access_interval:
            await asyncio.sleep(min_db_access_interval)
        
        # ⚡ เก็บเฉพาะที่ Supabase ใน format ไทย
        data = {
            "plate": plate_number,
            "timestamp": timestamp
        }
        
        # ดำเนินการแบบ non-blocking
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, 
            lambda: supabase_client.table("plates").insert(data).execute()
        )
        
        # บันทึกเวลาการเข้าถึงฐานข้อมูลล่าสุด
        last_db_access = time.time()
        
        if hasattr(response, 'error') and response.error:
            logger.error(f"Supabase Error: {response.error}")
            raise Exception(f"Supabase Error: {response.error}")
        
        # ล้าง cache เพื่อให้ข้อมูลเป็นปัจจุบัน
        if plate_number in plates_cache:
            del plates_cache[plate_number]
        search_cache.clear()  # ล้าง cache การค้นหา
        
        logger.info(f"Added plate to Supabase: {plate_number}")
        return True
    except Exception as e:
        logger.error(f"Supabase Exception: {e}")
        raise

async def search_plates(
    search_term=None,
    start_date=None,
    end_date=None,
    start_month=None,
    end_month=None,
    start_year=None,
    end_year=None,
    start_hour=None,
    end_hour=None,
    limit=500
):
    """
    ค้นหาทะเบียนตามเงื่อนไขต่างๆ ละเอียดมากขึ้น
    
    Parameters:
    - search_term (str): ข้อความที่ต้องการค้นหา เช่น "ABC"
    - start_date (str): วันที่เริ่มต้นในรูปแบบ DD/MM/YYYY
    - end_date (str): วันที่สิ้นสุดในรูปแบบ DD/MM/YYYY
    - start_month (str): เดือนเริ่มต้น (1-12)
    - end_month (str): เดือนสิ้นสุด (1-12)
    - start_year (str): ปีเริ่มต้น (เช่น 2023)
    - end_year (str): ปีสิ้นสุด (เช่น 2023)
    - start_hour (str): ชั่วโมงเริ่มต้น (0-23)
    - end_hour (str): ชั่วโมงสิ้นสุด (0-23)
    - limit (int): จำนวนผลลัพธ์สูงสุด
    
    Returns:
    - list: รายการทะเบียนที่ตรงตามเงื่อนไข
    """
    global last_db_access
    
    # สร้าง cache key จากพารามิเตอร์ทั้งหมด
    cache_key = f"{search_term}_{start_date}_{end_date}_{start_month}_{end_month}_{start_year}_{end_year}_{start_hour}_{end_hour}_{limit}"
    
    # เช็คว่ามีใน cache หรือไม่
    if cache_key in search_cache:
        logger.info(f"Retrieved search results from cache for key: {cache_key}")
        return search_cache[cache_key]
    
    try:
        # ป้องกันการเรียกฐานข้อมูลถี่เกินไป
        current_time = time.time()
        if current_time - last_db_access < min_db_access_interval:
            await asyncio.sleep(min_db_access_interval)
            
        # เริ่มสร้าง query
        query = supabase_client.table("plates").select("*")
        
        # ถ้ามีคำค้นหา ให้หาทะเบียนที่ขึ้นต้นด้วยคำนั้น
        if search_term:
            query = query.ilike("plate", f"{search_term}%")
        
        # =============== การค้นหาตามวันที่ ===============
        # กรณีที่ 1: ค้นหาตามช่วงวันที่เต็ม (DD/MM/YYYY)
        if start_date and end_date:
            # แปลงวันที่สตริงเป็น datetime objects
            start_dt = parse_thai_date(start_date)
            end_dt = parse_thai_date(end_date)
            
            if start_dt and end_dt:
                # เพิ่ม 1 วันให้ end_date เพื่อให้รวมวันสุดท้าย
                end_dt = end_dt + timedelta(days=1)
                
                # แปลงกลับเป็นสตริงในรูปแบบไทย
                start_str = start_dt.strftime("%d/%m/%Y")
                end_str = end_dt.strftime("%d/%m/%Y")
                
                # ใช้ gte (greater than or equal) และ lt (less than)
                query = query.gte("timestamp", start_str).lt("timestamp", end_str)
        
        # กรณีที่ 2: ค้นหาตามช่วงเดือนและปี
        elif start_month and end_month and start_year and end_year:
            # แปลงเดือนและปีเป็น datetime objects
            start_dt = parse_month_year(start_month, start_year)
            end_dt = parse_month_year(end_month, end_year)
            
            if start_dt and end_dt:
                # ถ้าเป็นเดือนสุดท้าย ให้เพิ่มอีก 1 เดือน
                if int(end_month) == 12:
                    end_dt = datetime(int(end_year) + 1, 1, 1)
                else:
                    end_dt = datetime(int(end_year), int(end_month) + 1, 1)
                
                # แปลงกลับเป็นสตริงในรูปแบบไทย
                start_str = start_dt.strftime("01/%m/%Y")
                end_str = end_dt.strftime("01/%m/%Y")
                
                # ใช้ gte (greater than or equal) และ lt (less than)
                query = query.gte("timestamp", start_str).lt("timestamp", end_str)
        
        # กรณีที่ 3: ค้นหาตามช่วงปี
        elif start_year and end_year:
            # สร้างช่วงวันที่จากปี
            start_dt = datetime(int(start_year), 1, 1)
            # เพิ่ม 1 ปี เพื่อให้รวมวันสุดท้ายของปี
            end_dt = datetime(int(end_year) + 1, 1, 1)
            
            # แปลงกลับเป็นสตริงในรูปแบบไทย
            start_str = start_dt.strftime("01/01/%Y")
            end_str = end_dt.strftime("01/01/%Y")
            
            # ใช้ gte (greater than or equal) และ lt (less than)
            query = query.gte("timestamp", start_str).lt("timestamp", end_str)
        
        # =============== การค้นหาตามเวลา ===============
        # กรณีที่ 4: ค้นหาตามช่วงเวลา (ชั่วโมง)
        if start_hour is not None and end_hour is not None:
            # แปลงชั่วโมงเป็นสตริง
            start_time = format_time(start_hour)
            end_time = format_time(end_hour)
            
            if start_time and end_time:
                # ใช้ LIKE operator เพื่อค้นหาเวลาที่ตรงกับรูปแบบ "DD/MM/YYYY HH:MM:SS"
                if int(end_hour) >= int(start_hour):
                    # เวลาปกติ เช่น 10:00-15:00
                    
                    # สร้าง SQL filter สำหรับ Supabase
                    # หมายเหตุ: นี่เป็นวิธีที่ทำได้ใน Supabase ซึ่งใช้ PostgreSQL
                    # เราต้องใช้ filter แบบ custom SQL เพื่อเปรียบเทียบเวลา
                    hour_filter = f"SUBSTRING(timestamp, 12, 2) >= '{int(start_hour):02d}' AND SUBSTRING(timestamp, 12, 2) <= '{int(end_hour):02d}'"
                    query = query.or_(hour_filter)
                else:
                    # เวลาข้ามวัน เช่น 22:00-03:00
                    # แบ่งเป็น 2 ช่วง: start_hour ถึง 23:59 และ 00:00 ถึง end_hour
                    hour_filter_1 = f"SUBSTRING(timestamp, 12, 2) >= '{int(start_hour):02d}'"
                    hour_filter_2 = f"SUBSTRING(timestamp, 12, 2) <= '{int(end_hour):02d}'"
                    query = query.or_(f"{hour_filter_1} OR {hour_filter_2}")
        
        # จำกัดจำนวนผลลัพธ์
        query = query.limit(limit)
        
        # ดำเนินการแบบ non-blocking
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: query.execute())
        
        # บันทึกเวลาการเข้าถึงฐานข้อมูลล่าสุด
        last_db_access = time.time()
        
        if hasattr(response, 'error') and response.error:
            logger.error(f"Supabase Search Error: {response.error}")
            return []
        
        # เก็บผลลัพธ์ใน cache
        result = response.data if response.data else []
        search_cache[cache_key] = result
        
        logger.info(f"Search results: {len(result)} plates found")
        return result
    except Exception as e:
        logger.error(f"Supabase Search Exception: {e}")
        return []

# ฟังก์ชันเดิมยังคงมีไว้เพื่อความเข้ากันได้กับโค้ดเก่า
async def get_plates():
    """ดึงทะเบียนทั้งหมดจาก Supabase (จำกัด 500 รายการ)"""
    return await search_plates(limit=500)

async def get_plate(plate_number):
    """ดึงทะเบียนตามเลขทะเบียนที่ระบุ"""
    try:
        # ตรวจสอบว่ามี cache หรือไม่
        if plate_number in plates_cache:
            logger.info(f"Retrieved plate from cache: {plate_number}")
            return plates_cache[plate_number]
        
        # ใช้ฟังก์ชัน search_plates ที่ปรับปรุงแล้ว
        results = await search_plates(search_term=plate_number, limit=1)
        
        # กรองเฉพาะผลลัพธ์ที่ตรงกับเลขทะเบียนที่ต้องการ
        result = next((item for item in results if item["plate"] == plate_number), None)
        
        # เก็บผลลัพธ์ใน cache
        if result:
            plates_cache[plate_number] = result
            
        return result
    except Exception as e:
        logger.error(f"Get Plate Exception: {e}")
        return None

# 2. ปรับปรุงไฟล์ plates.py

# app/routes/plates.py
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

class AdvancedSearchParams(BaseModel):
    search_term: Optional[str] = Field(None, description="คำค้นหาสำหรับทะเบียนรถ เช่น 'ABC'")
    start_date: Optional[str] = Field(None, description="วันที่เริ่มต้นในรูปแบบ DD/MM/YYYY")
    end_date: Optional[str] = Field(None, description="วันที่สิ้นสุดในรูปแบบ DD/MM/YYYY")
    start_month: Optional[str] = Field(None, description="เดือนเริ่มต้น (1-12)")
    end_month: Optional[str] = Field(None, description="เดือนสิ้นสุด (1-12)")
    start_year: Optional[str] = Field(None, description="ปีเริ่มต้น (เช่น 2023)")
    end_year: Optional[str] = Field(None, description="ปีสิ้นสุด (เช่น 2023)")
    start_hour: Optional[str] = Field(None, description="ชั่วโมงเริ่มต้น (0-23)")
    end_hour: Optional[str] = Field(None, description="ชั่วโมงสิ้นสุด (0-23)")
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
async def search_plates_route(search_params: AdvancedSearchParams):
    """
    ค้นหาทะเบียนแบบละเอียด:
    - ค้นหาตามเลขทะเบียน เช่น "ABC" (จะได้ ABC0001, ABC1234, ฯลฯ)
    - ค้นหาตามช่วงวันที่ เช่น 01/12/2023 ถึง 31/12/2023
    - ค้นหาตามช่วงเดือน เช่น เดือน 1 ถึง เดือน 6 ปี 2023
    - ค้นหาตามช่วงปี เช่น ปี 2020 ถึง 2023
    - ค้นหาตามช่วงเวลา เช่น 8:00 น. ถึง 17:00 น.
    """
    try:
        # ตรวจสอบความถูกต้องของข้อมูล
        validate_search_params(search_params)
        
        # เรียกใช้ฟังก์ชันค้นหา
        results = await search_plates(
            search_term=search_params.search_term,
            start_date=search_params.start_date,
            end_date=search_params.end_date,
            start_month=search_params.start_month,
            end_month=search_params.end_month,
            start_year=search_params.start_year,
            end_year=search_params.end_year,
            start_hour=search_params.start_hour,
            end_hour=search_params.end_hour,
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
    search_term: Optional[str] = Query(None, description="คำค้นหาสำหรับทะเบียนรถ เช่น 'ABC'"),
    start_date: Optional[str] = Query(None, description="วันที่เริ่มต้นในรูปแบบ DD/MM/YYYY"),
    end_date: Optional[str] = Query(None, description="วันที่สิ้นสุดในรูปแบบ DD/MM/YYYY"),
    start_month: Optional[str] = Query(None, description="เดือนเริ่มต้น (1-12)"),
    end_month: Optional[str] = Query(None, description="เดือนสิ้นสุด (1-12)"),
    start_year: Optional[str] = Query(None, description="ปีเริ่มต้น (เช่น 2023)"),
    end_year: Optional[str] = Query(None, description="ปีสิ้นสุด (เช่น 2023)"),
    start_hour: Optional[str] = Query(None, description="ชั่วโมงเริ่มต้น (0-23)"),
    end_hour: Optional[str] = Query(None, description="ชั่วโมงสิ้นสุด (0-23)"),
    limit: int = Query(500, ge=1, le=1000, description="จำนวนผลลัพธ์สูงสุด (1-1000)")
):
    """
    ค้นหาทะเบียนแบบละเอียดด้วย GET method:
    - ค้นหาตามเลขทะเบียน (เช่น ABC)
    - ค้นหาตามช่วงวันที่ เดือน ปี เวลา
    """
    # สร้าง SearchParams จาก query parameters
    search_params = AdvancedSearchParams(
        search_term=search_term,
        start_date=start_date,
        end_date=end_date,
        start_month=start_month,
        end_month=end_month,
        start_year=start_year,
        end_year=end_year,
        start_hour=start_hour,
        end_hour=end_hour,
        limit=limit
    )
    
    # เรียกใช้ฟังก์ชันค้นหาที่มีอยู่แล้ว
    return await search_plates_route(search_params)

def validate_search_params(params: AdvancedSearchParams):
    """ตรวจสอบความถูกต้องของพารามิเตอร์การค้นหา"""
    
    # ตรวจสอบวันที่
    if params.start_date or params.end_date:
        date_pattern = r"^\d{2}/\d{2}/\d{4}$"
        
        if params.start_date and not re.match(date_pattern, params.start_date):
            raise HTTPException(status_code=400, detail="Start date must be in DD/MM/YYYY format")
            
        if params.end_date and not re.match(date_pattern, params.end_date):
            raise HTTPException(status_code=400, detail="End date must be in DD/MM/YYYY format")
        
        # ถ้ามีเฉพาะวันที่เริ่มต้นหรือวันที่สิ้นสุด ให้กำหนดอีกวันที่เป็นวันที่เดียวกัน
        if params.start_date and not params.end_date:
            params.end_date = params.start_date
        elif params.end_date and not params.start_date:
            params.start_date = params.end_date
    
    # ตรวจสอบเดือน
    if params.start_month or params.end_month:
        if params.start_month and (not params.start_month.isdigit() or int(params.start_month) < 1 or int(params.start_month) > 12):
            raise HTTPException(status_code=400, detail="Start month must be between 1 and 12")
            
        if params.end_month and (not params.end_month.isdigit() or int(params.end_month) < 1 or int(params.end_month) > 12):
            raise HTTPException(status_code=400, detail="End month must be between 1 and 12")
        
        # ถ้ามีเฉพาะเดือนเริ่มต้นหรือเดือนสิ้นสุด ให้กำหนดอีกเดือนเป็นเดือนเดียวกัน
        if params.start_month and not params.end_month:
            params.end_month = params.start_month
        elif params.end_month and not params.start_month:
            params.start_month = params.end_month
    
    # ตรวจสอบปี
    if params.start_year or params.end_year:
        if params.start_year and not params.start_year.isdigit():
            raise HTTPException(status_code=400, detail="Start year must be a number")
            
        if params.end_year and not params.end_year.isdigit():
            raise HTTPException(status_code=400, detail="End year must be a number")
        
        # ถ้ามีเฉพาะปีเริ่มต้นหรือปีสิ้นสุด ให้กำหนดอีกปีเป็นปีเดียวกัน
        if params.start_year and not params.end_year:
            params.end_year = params.start_year
        elif params.end_year and not params.start_year:
            params.start_year = params.end_year
    
    # ตรวจสอบชั่วโมง
    if params.start_hour or params.end_hour:
        if params.start_hour and (not params.start_hour.isdigit() or int(params.start_hour) < 0 or int(params.start_hour) > 23):
            raise HTTPException(status_code=400, detail="Start hour must be between 0 and 23")
            
        if params.end_hour and (not params.end_hour.isdigit() or int(params.end_hour) < 0 or int(params.end_hour) > 23):
            raise HTTPException(status_code=400, detail="End hour must be between 0 and 23")
        
        # ถ้ามีเฉพาะชั่วโมงเริ่มต้นหรือชั่วโมงสิ้นสุด ให้กำหนดอีกชั่วโมงเป็นชั่วโมงเดียวกัน
        if params.start_hour and not params.end_hour:
            params.end_hour = params.start_hour
        elif params.end_hour and not params.start_hour:
            params.start_hour = params.end_hour
    
    # ตรวจสอบความสอดคล้องของเดือน/ปี (ต้องมีทั้งเดือนและปี)
    if (params.start_month or params.end_month) and not (params.start_year and params.end_year):
        raise HTTPException(status_code=400, detail="Both month and year are required for month-based search")
    
    return params