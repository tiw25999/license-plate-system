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
# cache เก็บข้อมูลทะเบียน 5 นาที, maxsize 1000 รายการ
plates_cache = TTLCache(maxsize=1000, ttl=300)
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
    limit=500
):
    """
    ค้นหาทะเบียนตามเงื่อนไขต่างๆ (ทะเบียนที่คล้ายกัน, ช่วงวันที่)
    
    Parameters:
    - search_term (str): ข้อความที่ต้องการค้นหา เช่น "ABC"
    - start_date (str): วันที่เริ่มต้นในรูปแบบ DD/MM/YYYY
    - end_date (str): วันที่สิ้นสุดในรูปแบบ DD/MM/YYYY
    - limit (int): จำนวนผลลัพธ์สูงสุด
    
    Returns:
    - list: รายการทะเบียนที่ตรงตามเงื่อนไข
    """
    global last_db_access
    
    # สร้าง cache key จากพารามิเตอร์ทั้งหมด
    cache_key = f"{search_term}_{start_date}_{end_date}_{limit}"
    
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
        
        # ถ้ามีช่วงวันที่ ให้กรองตามช่วงวันที่
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