import os
from dotenv import load_dotenv
from app.config import supabase_client
from datetime import datetime
import pytz
import asyncio
from cachetools import TTLCache
import logging
import time

# ตั้งค่า logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# โหลดค่าตัวแปรแวดล้อม
load_dotenv()

# สร้าง cache
# cache เก็บข้อมูลทะเบียน 5 นาที, maxsize 1000 รายการ
plates_cache = TTLCache(maxsize=1000, ttl=300)
all_plates_cache = TTLCache(maxsize=1, ttl=60)  # cache สำหรับการดึงข้อมูลทั้งหมด 1 นาที

# ตัวแปรสำหรับบันทึกเวลาใช้งาน
last_db_access = 0
min_db_access_interval = 0.1  # ขั้นต่ำ 100ms ระหว่างการเรียก

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
        all_plates_cache.clear()  # ล้าง cache ที่เก็บข้อมูลทั้งหมด
        
        logger.info(f"Added plate to Supabase: {plate_number}")
        return True
    except Exception as e:
        logger.error(f"Supabase Exception: {e}")
        raise

async def get_plates():
    """ดึงทะเบียนทั้งหมดจาก Supabase ด้วย async + caching"""
    global last_db_access
    
    try:
        # ตรวจสอบว่ามี cache หรือไม่
        if 'all_plates' in all_plates_cache:
            logger.info("Retrieved all plates from cache")
            return all_plates_cache['all_plates']
        
        # ป้องกันการเรียกฐานข้อมูลถี่เกินไป
        current_time = time.time()
        if current_time - last_db_access < min_db_access_interval:
            await asyncio.sleep(min_db_access_interval)
        
        # ดำเนินการแบบ non-blocking
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, 
            lambda: supabase_client.table("plates").select("*").execute()
        )
        
        # บันทึกเวลาการเข้าถึงฐานข้อมูลล่าสุด
        last_db_access = time.time()
        
        # เก็บผลลัพธ์ใน cache
        result = response.data if response.data else []
        all_plates_cache['all_plates'] = result
        
        logger.info(f"Retrieved all plates from DB, count: {len(result)}")
        return result
    except Exception as e:
        logger.error(f"Supabase Get Plates Error: {e}")
        return []

async def get_plate(plate_number):
    """ดึงทะเบียนและ timestamp จาก Supabase ด้วย async + caching"""
    global last_db_access
    
    try:
        # ตรวจสอบว่ามี cache หรือไม่
        if plate_number in plates_cache:
            logger.info(f"Retrieved plate from cache: {plate_number}")
            return plates_cache[plate_number]
        
        logger.info(f"Searching for plate: {plate_number}")
        
        # ป้องกันการเรียกฐานข้อมูลถี่เกินไป
        current_time = time.time()
        if current_time - last_db_access < min_db_access_interval:
            await asyncio.sleep(min_db_access_interval)
        
        # ดำเนินการแบบ non-blocking
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, 
            lambda: supabase_client.table("plates").select("*").eq("plate", plate_number).execute()
        )
        
        # บันทึกเวลาการเข้าถึงฐานข้อมูลล่าสุด
        last_db_access = time.time()
        
        if hasattr(response, 'error') and response.error:
            logger.error(f"Supabase Get Plate Error: {response.error}")
            return None
        
        result = response.data[0] if response.data and len(response.data) > 0 else None
        
        # เก็บผลลัพธ์ใน cache
        if result:
            plates_cache[plate_number] = result
            
        logger.info(f"Plate search result: {result}")
        return result
    except Exception as e:
        logger.error(f"Supabase Exception: {e}")
        return None