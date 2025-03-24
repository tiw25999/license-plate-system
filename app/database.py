import os
from dotenv import load_dotenv
from app.config import supabase_client
from datetime import datetime
import pytz

# โหลดค่าตัวแปรแวดล้อม
load_dotenv()

def add_plate(plate_number, timestamp=None):
    """เพิ่มทะเบียนไปที่ Supabase"""
    if timestamp is None:
        # สร้าง timestamp ในรูปแบบไทย
        thailand_tz = pytz.timezone('Asia/Bangkok')
        now = datetime.now(thailand_tz)
        timestamp = now.strftime("%d/%m/%Y %H:%M:%S")  # Thai format for display
    
    try:
        # ⚡ เก็บเฉพาะที่ Supabase ใน format ไทย
        data = {
            "plate": plate_number,
            "timestamp": timestamp
        }
        response = supabase_client.table("plates").insert(data).execute()
        if hasattr(response, 'error') and response.error:
            print(f"⚡ Supabase Error: {response.error}")
            raise Exception(f"Supabase Error: {response.error}")
        print(f"✅ Added plate to Supabase: {plate_number}")
    except Exception as e:
        print(f"⚡ Supabase Exception: {e}")
        raise

def get_plates():
    """ดึงทะเบียนทั้งหมดจาก Supabase"""
    try:
        response = supabase_client.table("plates").select("*").execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"⚡ Supabase Get Plates Error: {e}")
        return []

def get_plate(plate_number):
    """ดึงทะเบียนและ timestamp จาก Supabase"""
    try:
        print(f"🔍 Searching for plate: {plate_number}")
        response = supabase_client.table("plates").select("*").eq("plate", plate_number).execute()
        
        if hasattr(response, 'error') and response.error:
            print(f"⚡ Supabase Get Plate Error: {response.error}")
            return None
        
        print(f"🔍 Search result: {response.data}")
        return response.data[0] if response.data and len(response.data) > 0 else None
    except Exception as e:
        print(f"⚡ Supabase Exception: {e}")
        return None