import os
import uuid
from dotenv import load_dotenv
from app.config import supabase_client
from datetime import datetime, timedelta
import pytz
import asyncio
from cachetools import TTLCache
import logging
import time
from fastapi import Request
from typing import Optional

# ตั้งค่า logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# โหลดค่าตัวแปรแวดล้อม
load_dotenv()

# สร้าง cache
plates_cache = TTLCache(maxsize=1000, ttl=300)
search_cache = TTLCache(maxsize=100, ttl=60)
all_plates_cache = TTLCache(maxsize=1, ttl=300)
camera_cache = TTLCache(maxsize=1, ttl=600)

logger = logging.getLogger(__name__)
min_db_access_interval = 0.1
last_db_access = 0.0
MAX_RECORDS = 1000


def parse_thai_date(date_str):
    try:
        day, month, year = date_str.split('/')
        thailand_tz = pytz.timezone('Asia/Bangkok')
        dt = datetime(int(year), int(month), int(day), tzinfo=thailand_tz)
        return dt
    except Exception as e:
        logger.error(f"Error parsing date: {date_str}, {e}")
        return None


def format_timestamp_thai(timestamp):
    """
    แปลง timestamp (iso string หรือ datetime object) เป็นรูป dd/MM/YYYY HH:MM:SS
    โดยใช้ timezone Asia/Bangkok และปีเป็น พ.ศ. (Buddhist year)
    """
    if not timestamp:
        return "-"

    # ถ้าเป็น string ให้แปลงกลับเป็น datetime
    if isinstance(timestamp, str):
        try:
            # รองรับ ISO format ที่มี Z
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except Exception as e:
            logger.error(f"Error converting timestamp string: {e}")
            return timestamp

    # ตั้ง timezone เป็นกรุงเทพฯ
    thailand_tz = pytz.timezone('Asia/Bangkok')
    local_dt = timestamp.astimezone(thailand_tz)

    # คำนวณปี พุทธศักราช
    buddhist_year = local_dt.year + 543

    # format dd/MM/YYYY HH:MM:SS
    day   = f"{local_dt.day:02d}"
    month = f"{local_dt.month:02d}"
    time  = local_dt.strftime("%H:%M:%S")

    return f"{day}/{month}/{buddhist_year} {time}"


async def add_plate_candidate(
    plate_number: str,
    province: str = None,
    id_camera: str = None,
    camera_name: str = None,
    user_id: str = None,
    timestamp: str = None,
    character_confidences: list[float] = None,
    province_confidence: float = None
) -> dict:
    """
    Insert ลง plate_candidates โดยใช้ id == correlation_id
    คืนค่าแถวที่สร้าง (มีทั้ง id และ correlation_id)
    """
    corr_id = str(uuid.uuid4())
    thailand_tz = pytz.timezone('Asia/Bangkok')
    now = datetime.now(thailand_tz).isoformat()

    data = {
        "id": corr_id,
        "correlation_id": corr_id,
        "plate": plate_number,
        "created_at": timestamp or now,
    }
    if user_id:
        data["uploaded_by"] = user_id
    if province:
        data["province"] = province
    if id_camera:
        data["id_camera"] = id_camera
    if camera_name:
        data["camera_name"] = camera_name
    if character_confidences is not None:
        data["character_confidences"] = character_confidences
    if province_confidence is not None:
        data["province_confidence"] = province_confidence

    loop = asyncio.get_event_loop()
    resp = await loop.run_in_executor(
        None,
        lambda: supabase_client
                 .table("plate_candidates")
                 .insert(data)
                 .execute()
    )

    if not getattr(resp, "data", None):
        raise Exception("Insert plate_candidates failed")

    return resp.data[0]


async def add_plate_image(
    correlation_id: str,
    image_path: str,
    uploaded_by: str = None,
    notes: str = None,
    image_name: str = None
) -> dict:
    thailand_tz = pytz.timezone('Asia/Bangkok')
    now = datetime.now(thailand_tz).isoformat()

    data = {
        "correlation_id": correlation_id,
        "image_path": image_path,
        "uploaded_at": now,
        "uploaded_by": uploaded_by  # รักษาฟิลด์เดิม
    }

    if notes:
        data["notes"] = notes
    if image_name:
        data["image_name"] = image_name

    loop = asyncio.get_event_loop()
    resp = await loop.run_in_executor(
        None,
        lambda: supabase_client
                 .table("plate_images")
                 .insert(data)
                 .execute()
    )

    if not getattr(resp, "data", None):
        raise Exception("Insert plate_images failed")

    return resp.data[0]


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
    province=None,
    id_camera=None,
    camera_name=None,
    limit=MAX_RECORDS
):
    """
    ค้นหาทะเบียนตามเงื่อนไขต่างๆ
    """
    global last_db_access

    # จำกัดจำนวนข้อมูลที่ดึงมาสูงสุด
    if limit > MAX_RECORDS:
        limit = MAX_RECORDS

    # บันทึก log ข้อมูลการค้นหา
    logger.info(f"Search parameters: term={search_term}, date={start_date}-{end_date}, hours={start_hour}-{end_hour}, province={province}")

    # สร้าง cache key จากพารามิเตอร์ทั้งหมด
    cache_key = f"{search_term}_{start_date}_{end_date}_{start_month}_{end_month}_{start_year}_{end_year}_{start_hour}_{end_hour}_{province}_{id_camera}_{camera_name}_{limit}"

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

        # ถ้ามีคำค้นหา ใช้ contains
        if search_term:
            query = query.ilike("plate", f"%{search_term}%")

        if province:
            query = query.eq("province", province)

        if id_camera:
            query = query.eq("id_camera", id_camera)

        if camera_name:
            query = query.ilike("camera_name", f"%{camera_name}%")

        # การค้นหาตามช่วงวันที่
        if start_date and end_date:
            start_dt = parse_thai_date(start_date)
            end_dt = parse_thai_date(end_date)
            if start_dt and end_dt:
                end_dt = end_dt + timedelta(days=1)  # รวมวันสุดท้าย
                query = query.gte("timestamp", start_dt.isoformat())
                query = query.lt("timestamp", end_dt.isoformat())
        elif start_month and end_month and start_year and end_year:
            try:
                thailand_tz = pytz.timezone('Asia/Bangkok')
                start_dt = datetime(int(start_year), int(start_month), 1, tzinfo=thailand_tz)
                if int(end_month) == 12:
                    end_dt = datetime(int(end_year) + 1, 1, 1, tzinfo=thailand_tz)
                else:
                    end_dt = datetime(int(end_year), int(end_month) + 1, 1, tzinfo=thailand_tz)
                query = query.gte("timestamp", start_dt.isoformat())
                query = query.lt("timestamp", end_dt.isoformat())
            except ValueError as e:
                logger.error(f"Error processing month/year search: {e}")
        elif start_year and end_year:
            try:
                thailand_tz = pytz.timezone('Asia/Bangkok')
                start_dt = datetime(int(start_year), 1, 1, tzinfo=thailand_tz)
                end_dt = datetime(int(end_year) + 1, 1, 1, tzinfo=thailand_tz)
                query = query.gte("timestamp", start_dt.isoformat())
                query = query.lt("timestamp", end_dt.isoformat())
            except ValueError as e:
                logger.error(f"Error processing year search: {e}")

        # จำกัดจำนวนผลลัพธ์ + เรียงวันที่ล่าสุด
        query = query.limit(limit).order('timestamp', desc=True)

        # ดำเนินการแบบ non-blocking
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: query.execute())

        # บันทึกเวลาการเข้าถึงฐานข้อมูลล่าสุด
        last_db_access = time.time()

        if hasattr(response, 'error') and response.error:
            logger.error(f"Database Search Error: {response.error}")
            return []

        # ตรวจสอบการกรองตามช่วงเวลา
        has_hour_filter = start_hour is not None and end_hour is not None

        # แปลงรูปแบบวันที่และกรองตามช่วงเวลา (ถ้ามี)
        result = []
        for item in response.data or []:
            formatted_item = item.copy()
            timestamp = item.get("timestamp")
            if timestamp:
                try:
                    if isinstance(timestamp, str):
                        timestamp_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    else:
                        timestamp_dt = timestamp

                    thailand_tz = pytz.timezone('Asia/Bangkok')
                    local_dt = timestamp_dt.astimezone(thailand_tz)

                    if has_hour_filter:
                        hour = local_dt.hour
                        if not (int(start_hour) <= hour <= int(end_hour)):
                            continue

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
        logger.error(f"Database Search Exception: {e}")
        return []


async def get_plates():
    """ดึงทะเบียนทั้งหมดจากฐานข้อมูล (จำกัด 1000 รายการล่าสุด)"""
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
            formatted_item = item.copy()
            formatted_item["timestamp"] = format_timestamp_thai(item.get("timestamp"))
            result.append(formatted_item)

        # เก็บผลลัพธ์ใน cache
        all_plates_cache['all_plates'] = result

        logger.info(f"Retrieved all plates, count: {len(result)}")
        return result
    except Exception as e:
        logger.error(f"Database Get Plates Error: {e}")
        return []


async def get_plate(plate_number):
    """ดึงทะเบียนตามเลขทะเบียนที่ระบุ"""
    try:
        if plate_number in plates_cache:
            logger.info(f"Retrieved plate from cache: {plate_number}")
            return plates_cache[plate_number]

        results = await search_plates(search_term=plate_number, limit=10)
        result = next((item for item in results if item["plate"] == plate_number), None)

        if result:
            plates_cache[plate_number] = result

        return result
    except Exception as e:
        logger.error(f"Get Plate Exception: {e}")
        return None


async def get_cameras():
    """ดึงรายการกล้องทั้งหมด"""
    global last_db_access

    if 'cameras' in camera_cache:
        logger.info("Retrieved cameras from cache")
        return camera_cache['cameras']

    try:
        current_time = time.time()
        if current_time - last_db_access < min_db_access_interval:
            await asyncio.sleep(min_db_access_interval)

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: supabase_client.table("cameras")
                    .select("*")
                    .order('name')
                    .execute()
        )

        last_db_access = time.time()

        if hasattr(response, 'error') and response.error:
            logger.error(f"Database Get Cameras Error: {response.error}")
            return []

        camera_cache['cameras'] = response.data or []

        logger.info(f"Retrieved cameras, count: {len(response.data or [])}")
        return response.data or []
    except Exception as e:
        logger.error(f"Database Get Cameras Error: {e}")
        return []


async def get_system_settings():
    """ดึงการตั้งค่าระบบทั้งหมด"""
    global last_db_access

    try:
        current_time = time.time()
        if current_time - last_db_access < min_db_access_interval:
            await asyncio.sleep(min_db_access_interval)

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: supabase_client.table("system_settings").select("*").execute()
        )

        last_db_access = time.time()

        if hasattr(response, 'error') and response.error:
            logger.error(f"Database Get System Settings Error: {response.error}")
            return {}

        settings = {}
        for item in response.data or []:
            settings[item.get("setting_key")] = item.get("setting_value")

        logger.info(f"Retrieved system settings, count: {len(settings)}")
        return settings
    except Exception as e:
        logger.error(f"Get System Settings Exception: {e}")
        return {}


async def get_setting(key, default=None):
    """ดึงค่าการตั้งค่าตาม key ที่ระบุ"""
    try:
        settings = await get_system_settings()
        return settings.get(key, default)
    except Exception as e:
        logger.error(f"Get Setting Exception: {key}, {e}")
        return default


async def set_setting(key, value, description=None):
    """ตั้งค่าการตั้งค่าระบบ"""
    global last_db_access

    try:
        current_time = time.time()
        if current_time - last_db_access < min_db_access_interval:
            await asyncio.sleep(min_db_access_interval)

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: supabase_client.rpc(
                'set_setting',
                {
                    'p_key': key,
                    'p_value': value,
                    'p_description': description
                }
            ).execute()
        )

        last_db_access = time.time()

        if hasattr(response, 'error') and response.error:
            logger.error(f"Database Set Setting Error: {response.error}")
            return False

        logger.info(f"Set system setting: {key} = {value}")
        return True
    except Exception as e:
        logger.error(f"Set Setting Exception: {key}, {e}")
        return False


async def clear_caches():
    """ล้าง cache ทั้งหมด"""
    try:
        search_cache.clear()
        all_plates_cache.clear()
        plates_cache.clear()
        camera_cache.clear()
        logger.info("All caches cleared")
        return True
    except Exception as e:
        logger.error(f"Clear Caches Exception: {e}")
        return False


async def verify_plate_candidate(candidate_id: str, verified_by_user_id: str) -> str:
    """
    1) Fetch candidate จาก plate_candidates 
    2) Insert ลง plates โดยใช้ timestamp เดิมจาก candidate.created_at
    3) Insert ตัวอักษร+confidence ลง plate_characters
    4) Update plate_images ให้มี plate_id และ is_verified=True
    5) เติม plate_id เข้า plate_edits ที่ถูกสร้าง “ตอนแก้ก่อน verify” (reason ตรง pattern)
    6) Delete candidate ทิ้ง
    """
    # 1) ดึงข้อมูล candidate พร้อม created_at
    resp = supabase_client.table("plate_candidates") \
                          .select("*") \
                          .eq("id", candidate_id) \
                          .single() \
                          .execute()
    if not resp.data:
        raise Exception("Candidate not found")
    cand = resp.data

    # ดึง timestamp เดิมจาก candidate
    original_ts = cand["created_at"]

    # 2) Insert ลง plates → คืน new_plate_id
    ins = supabase_client.table("plates").insert({
        "plate":        cand["plate"],
        "province":     cand.get("province"),
        "id_camera":    cand.get("id_camera"),
        "camera_name":  cand.get("camera_name"),
        "user_id":      verified_by_user_id,
        "timestamp":    original_ts,      # ใช้เวลาจากตอนส่งเข้าหน้า verify
        "is_verified":  True,
        "created_at":   original_ts       # เก็บ created_at เดิมไว้ด้วย
    }).execute()
    new_plate_id = ins.data[0]["id"]

    # 3) Insert ตัวอักษร + confidence ลง plate_characters
    for idx, conf in enumerate(cand.get("character_confidences") or []):
        ch = cand["plate"][idx]
        supabase_client.table("plate_characters").insert({
            "id":         str(uuid.uuid4()),
            "plate_id":   new_plate_id,
            "type":       "character",
            "position":   idx,
            "character":  ch,
            "confidence": conf
        }).execute()

    # 4) Update plate_images ให้เชื่อมต่อกับ new_plate_id
    supabase_client.table("plate_images") \
                  .update({"plate_id": new_plate_id, "is_verified": True}) \
                  .eq("correlation_id", cand["correlation_id"]) \
                  .execute()

    # 5) เติม plate_id ให้ log ที่บันทึกไว้ก่อน verify (ไม่แก้สคีมา ใช้ reason อ้างอิง)
    link_reason = f"pre-verify edit (candidate_id={candidate_id})"
    supabase_client.table("plate_edits") \
                   .update({"plate_id": new_plate_id}) \
                   .eq("reason", link_reason) \
                   .execute()

    # 6) ลบ candidate ทิ้ง
    supabase_client.table("plate_candidates") \
                  .delete() \
                  .eq("id", candidate_id) \
                  .execute()

    return new_plate_id


async def get_plate_candidates():
    """ดึงข้อมูล plate_candidates ทั้งหมด (ล่าสุด 100 รายการ)"""
    global last_db_access

    try:
        current_time = time.time()
        if current_time - last_db_access < min_db_access_interval:
            await asyncio.sleep(min_db_access_interval)

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: supabase_client.table("plate_candidates")
                    .select("*")
                    .order("created_at", desc=True)
                    .limit(100)
                    .execute()
        )

        last_db_access = time.time()

        if response.data:
            logger.info(f"Retrieved plate candidates: {len(response.data)} records")
            return response.data
        else:
            logger.warning("No plate candidates found")
            return []
    except Exception as e:
        logger.error(f"Get Plate Candidates Exception: {e}")
        return []


async def edit_plate(plate_id: str, new_plate: str, edited_by: Optional[str] = None, reason: Optional[str] = None):
    """
    (คงฟังก์ชันเดิม) แก้ไขเลขป้ายในตาราง plates + เก็บ log ลง plate_edits
    """
    old_res = supabase_client.table("plates").select("*").eq("id", plate_id).single().execute()
    if not old_res.data:
        raise Exception("ไม่พบป้ายที่ต้องการแก้ไข")

    old_plate = old_res.data["plate"]
    if old_plate == new_plate:
        return {"message": "ไม่มีการเปลี่ยนแปลง"}

    supabase_client.table("plates").update({"plate": new_plate}).eq("id", plate_id).execute()

    supabase_client.table("plate_edits").insert({
        "plate_id": plate_id,
        "old_plate": old_plate,
        "new_plate": new_plate,
        "edited_by": edited_by,
        "reason": reason
    }).execute()

    return {"message": "แก้ไขสำเร็จ", "old": old_plate, "new": new_plate}


async def edit_plate_candidate(candidate_id: str, update_data: dict) -> dict:
    """
    แก้ไขข้อมูลใน plate_candidates
    - update_data: dict ของ field ที่ต้องการแก้ เช่น {"plate": "กข1234", "province": "กรุงเทพ"}
    """
    if not update_data:
        raise ValueError("ไม่มีข้อมูลที่ต้องการแก้ไข")

    resp = supabase_client.table("plate_candidates") \
                          .update(update_data) \
                          .eq("id", candidate_id) \
                          .execute()

    if getattr(resp, "error", None):
        raise Exception(f"Update failed: {resp.error}")

    return resp.data[0] if resp.data else {"message": "updated"}
