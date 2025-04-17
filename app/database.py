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
all_plates_cache = TTLCache(maxsize=1, ttl=300)  # cache เก็บข้อมูลทั้งหมด 5 นาที

# ตัวแปรสำหรับบันทึกเวลาใช้งาน
last_db_access = 0
min_db_access_interval = 0.1  # ขั้นต่ำ 100ms ระหว่างการเรียก

# จำนวนรายการที่ดึงจาก DB มากสุด (ลดลงเหลือ 1000 รายการ)
MAX_RECORDS = 1000

# แปลงวันที่ไทยเป็น datetime object พร้อม timezone
def parse_thai_date(date_str):
    """แปลงวันที่รูปแบบไทย (DD/MM/YYYY) เป็น datetime object พร้อม timezone"""
    try:
        day, month, year = date_str.split('/')
        # สร้าง datetime object พร้อม timezone
        thailand_tz = pytz.timezone('Asia/Bangkok')
        dt = datetime(int(year), int(month), int(day), tzinfo=thailand_tz)
        return dt
    except Exception as e:
        logger.error(f"Error parsing date: {date_str}, {e}")
        return None

# เพิ่มฟังก์ชันใหม่สำหรับแปลง timestamp เป็นรูปแบบไทย
def format_timestamp_thai(timestamp):
    """แปลง timestamp เป็นรูปแบบไทย DD/MM/YYYY HH:MM:SS"""
    if not timestamp:
        return "-"
    
    # ถ้าเป็น string ให้แปลงเป็น datetime ก่อน
    if isinstance(timestamp, str):
        try:
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except Exception as e:
            logger.error(f"Error converting timestamp string: {e}")
            return timestamp
    
    # แปลงเป็น timezone ไทย
    thailand_tz = pytz.timezone('Asia/Bangkok')
    local_dt = timestamp.astimezone(thailand_tz)
    
    # แปลงเป็นรูปแบบสตริง DD/MM/YYYY HH:MM:SS
    return local_dt.strftime("%d/%m/%Y %H:%M:%S")

async def add_plate(plate_number, timestamp=None):
    """เพิ่มทะเบียนไปที่ Supabase ด้วย async"""
    global last_db_access
    
    # สร้าง timestamp ในรูปแบบที่ถูกต้อง
    thailand_tz = pytz.timezone('Asia/Bangkok')
    now = datetime.now(thailand_tz)
    
    try:
        # ป้องกันการเรียกฐานข้อมูลถี่เกินไป
        current_time = time.time()
        if current_time - last_db_access < min_db_access_interval:
            await asyncio.sleep(min_db_access_interval)
        
        # เก็บเป็น timestamp (จะแปลงเป็นรูปแบบไทยตอนแสดงผล)
        data = {
            "plate": plate_number,
            "timestamp": now.isoformat()  # เก็บเป็นรูปแบบ ISO
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
        search_cache.clear()
        all_plates_cache.clear()
        
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
    start_hour=None,   # เพิ่มพารามิเตอร์ช่วงเวลาเริ่มต้น
    end_hour=None,     # เพิ่มพารามิเตอร์ช่วงเวลาสิ้นสุด
    limit=MAX_RECORDS
):
    """
    ค้นหาทะเบียนตามเงื่อนไขต่างๆ
    
    Parameters:
    - search_term (str): ข้อความที่ต้องการค้นหา
    - start_date (str): วันที่เริ่มต้นในรูปแบบ DD/MM/YYYY
    - end_date (str): วันที่สิ้นสุดในรูปแบบ DD/MM/YYYY
    - start_month (str): เดือนเริ่มต้น (1-12)
    - end_month (str): เดือนสิ้นสุด (1-12)
    - start_year (str): ปีเริ่มต้น (เช่น 1990)
    - end_year (str): ปีสิ้นสุด (เช่น 2023)
    - start_hour (str): ชั่วโมงเริ่มต้น (0-23)
    - end_hour (str): ชั่วโมงสิ้นสุด (0-23)
    - limit (int): จำนวนผลลัพธ์สูงสุด
    
    Returns:
    - list: รายการทะเบียนที่ตรงตามเงื่อนไข
    """
    global last_db_access
    
    # จำกัดจำนวนข้อมูลที่ดึงมาสูงสุด
    if limit > MAX_RECORDS:
        limit = MAX_RECORDS
    
    # บันทึก log ข้อมูลการค้นหา
    logger.info(f"Search parameters: term={search_term}, date={start_date}-{end_date}, hours={start_hour}-{end_hour}")
    
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
        
        # ถ้ามีคำค้นหา ใช้ contains แทน begins with
        if search_term:
            query = query.ilike("plate", f"%{search_term}%")
        
        # การค้นหาตามช่วงวันที่ (มีทั้งวันที่เริ่มต้นและวันที่สิ้นสุด)
        if start_date and end_date:
            # แปลงวันที่ให้เป็น datetime objects
            start_dt = parse_thai_date(start_date)
            end_dt = parse_thai_date(end_date)
            
            if start_dt and end_dt:
                # เพิ่ม 1 วันให้ end_date เพื่อให้รวมวันสุดท้าย
                end_dt = end_dt + timedelta(days=1)
                
                # ใช้ timestamp โดยตรงในการค้นหา
                query = query.gte("timestamp", start_dt.isoformat())
                query = query.lt("timestamp", end_dt.isoformat())
        
        # การค้นหาตามช่วงเดือนและปี
        elif start_month and end_month and start_year and end_year:
            try:
                # สร้างวันที่เริ่มต้น (วันแรกของเดือนเริ่มต้น)
                thailand_tz = pytz.timezone('Asia/Bangkok')
                start_dt = datetime(int(start_year), int(start_month), 1, tzinfo=thailand_tz)
                
                # สร้างวันที่สิ้นสุด (วันแรกของเดือนถัดไปหลังจากเดือนสิ้นสุด)
                if int(end_month) == 12:
                    end_dt = datetime(int(end_year) + 1, 1, 1, tzinfo=thailand_tz)
                else:
                    end_dt = datetime(int(end_year), int(end_month) + 1, 1, tzinfo=thailand_tz)
                
                # ใช้ timestamp โดยตรงในการค้นหา
                query = query.gte("timestamp", start_dt.isoformat())
                query = query.lt("timestamp", end_dt.isoformat())
            except ValueError as e:
                logger.error(f"Error processing month/year search: {e}")
        
        # การค้นหาตามช่วงปี
        elif start_year and end_year:
            try:
                # สร้างวันที่เริ่มต้น (1 มกราคมของปีเริ่มต้น)
                thailand_tz = pytz.timezone('Asia/Bangkok')
                start_dt = datetime(int(start_year), 1, 1, tzinfo=thailand_tz)
                
                # สร้างวันที่สิ้นสุด (1 มกราคมของปีถัดไปหลังจากปีสิ้นสุด)
                end_dt = datetime(int(end_year) + 1, 1, 1, tzinfo=thailand_tz)
                
                # ใช้ timestamp โดยตรงในการค้นหา
                query = query.gte("timestamp", start_dt.isoformat())
                query = query.lt("timestamp", end_dt.isoformat())
            except ValueError as e:
                logger.error(f"Error processing year search: {e}")
        
        # จำกัดจำนวนผลลัพธ์
        query = query.limit(limit)
        
        # เรียงลำดับตามวันที่ล่าสุด (ใช้ timestamp โดยตรง)
        query = query.order('timestamp', desc=True)
        
        # ดำเนินการแบบ non-blocking
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: query.execute())
        
        # บันทึกเวลาการเข้าถึงฐานข้อมูลล่าสุด
        last_db_access = time.time()
        
        if hasattr(response, 'error') and response.error:
            logger.error(f"Supabase Search Error: {response.error}")
            return []
        
        # ตรวจสอบการกรองตามช่วงเวลา
        has_hour_filter = start_hour is not None and end_hour is not None
        if has_hour_filter:
            logger.info(f"Filtering by hour range: {start_hour} - {end_hour}")
        
        # แปลงรูปแบบวันที่และกรองตามช่วงเวลา (ถ้ามี)
        result = []
        for item in response.data or []:
            # ทำสำเนาข้อมูล
            formatted_item = item.copy()
            
            # แปลง timestamp เป็น datetime object
            timestamp = item.get("timestamp")
            if timestamp:
                try:
                    # แปลง timestamp จาก string เป็น datetime
                    if isinstance(timestamp, str):
                        timestamp_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    else:
                        timestamp_dt = timestamp
                    
                    # แปลงเป็น timezone ไทย เพื่อให้แน่ใจว่าใช้เวลาท้องถิ่นในการเปรียบเทียบ
                    thailand_tz = pytz.timezone('Asia/Bangkok')
                    local_dt = timestamp_dt.astimezone(thailand_tz)
                    
                    # กรองตามช่วงเวลา (ถ้ามี)
                    if has_hour_filter:
                        hour = local_dt.hour
                        if not (int(start_hour) <= hour <= int(end_hour)):
                            # ข้ามรายการนี้ถ้าไม่อยู่ในช่วงเวลาที่กำหนด
                            logger.debug(f"Filtering out: hour={hour}, not in range {start_hour}-{end_hour}")
                            continue
                        else:
                            logger.debug(f"Including: hour={hour}, is in range {start_hour}-{end_hour}")
                    
                    # แปลงเป็นรูปแบบไทย
                    formatted_item["timestamp"] = format_timestamp_thai(local_dt)
                except Exception as e:
                    logger.error(f"Error processing timestamp: {e}")
                    formatted_item["timestamp"] = format_timestamp_thai(timestamp)
            
            result.append(formatted_item)
        
        # เก็บผลลัพธ์ใน cache
        search_cache[cache_key] = result
        
        logger.info(f"Search results: {len(result)} plates found")
        return result
    except Exception as e:
        logger.error(f"Supabase Search Exception: {e}")
        return []

async def get_plates():
    """ดึงทะเบียนทั้งหมดจาก Supabase (จำกัด 1000 รายการล่าสุด)"""
    global last_db_access
    
    # ตรวจสอบว่ามี cache หรือไม่
    if 'all_plates' in all_plates_cache:
        logger.info("Retrieved all plates from cache")
        return all_plates_cache['all_plates']
    
    try:
        # ป้องกันการเรียกฐานข้อมูลถี่เกินไป
        current_time = time.time()
        if current_time - last_db_access < min_db_access_interval:
            await asyncio.sleep(min_db_access_interval)
        
        # ดำเนินการแบบ non-blocking
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, 
            lambda: supabase_client.table("plates")
                    .select("*")
                    .order('timestamp', desc=True)  # เรียงตามวันที่ล่าสุด
                    .limit(MAX_RECORDS)
                    .execute()
        )
        
        # บันทึกเวลาการเข้าถึงฐานข้อมูลล่าสุด
        last_db_access = time.time()
        
        # แปลงรูปแบบวันที่สำหรับการแสดงผล
        result = []
        for item in response.data or []:
            # ทำสำเนาข้อมูล
            formatted_item = item.copy()
            # แปลง timestamp เป็นรูปแบบไทย
            formatted_item["timestamp"] = format_timestamp_thai(item.get("timestamp"))
            result.append(formatted_item)
        
        # เก็บผลลัพธ์ใน cache
        all_plates_cache['all_plates'] = result
        
        logger.info(f"Retrieved all plates, count: {len(result)}")
        return result
    except Exception as e:
        logger.error(f"Supabase Get Plates Error: {e}")
        return []

async def get_plate(plate_number):
    """ดึงทะเบียนตามเลขทะเบียนที่ระบุ"""
    try:
        # ตรวจสอบว่ามี cache หรือไม่
        if plate_number in plates_cache:
            logger.info(f"Retrieved plate from cache: {plate_number}")
            return plates_cache[plate_number]
        
        # ใช้ฟังก์ชัน search_plates ที่ปรับปรุงแล้ว
        results = await search_plates(search_term=plate_number, limit=10)
        
        # กรองเฉพาะผลลัพธ์ที่ตรงกับเลขทะเบียนที่ต้องการ
        result = next((item for item in results if item["plate"] == plate_number), None)
        
        # เก็บผลลัพธ์ใน cache
        if result:
            plates_cache[plate_number] = result
            
        return result
    except Exception as e:
        logger.error(f"Get Plate Exception: {e}")
        return None