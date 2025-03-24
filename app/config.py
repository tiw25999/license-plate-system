import os
import sys
from dotenv import load_dotenv

# พิมพ์ข้อมูลเพื่อดีบัก
print("Starting config.py initialization")
print("Python version:", sys.version)
print("Current working directory:", os.getcwd())

# โหลดค่าตัวแปรแวดล้อมจากไฟล์ .env
load_dotenv()

# พิมพ์รายการตัวแปรทั้งหมดในสภาพแวดล้อม
print("All environment variables:", list(os.environ.keys()))

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

print(f"SUPABASE_URL loaded: {'Yes' if SUPABASE_URL else 'No'}")
print(f"SUPABASE_KEY loaded: {'Yes' if SUPABASE_KEY else 'No'}")

try:
    # ตรวจสอบว่า SUPABASE_URL และ SUPABASE_KEY ถูกโหลดมาหรือไม่
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: Missing Supabase credentials")
        raise ValueError("Missing Supabase URL or API Key in environment variables")

    # สร้าง Supabase client
    from supabase import create_client, Client
    supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("Supabase client created successfully")
except Exception as e:
    print(f"Error creating Supabase client: {e}")
    # ในขั้นตอนการพัฒนา เราอาจต้องการใช้ค่าเริ่มต้นแทน
    # ส่วนในการใช้งานจริง ควรให้ล้มเหลว
    raise