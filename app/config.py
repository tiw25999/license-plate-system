import os
from dotenv import load_dotenv
from supabase import create_client, Client  # นำเข้า Supabase SDK

# โหลดค่าตัวแปรแวดล้อมจากไฟล์ .env
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# ตรวจสอบว่า SUPABASE_URL และ SUPABASE_KEY ถูกโหลดมาหรือไม่
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing Supabase URL or API Key in environment variables")

# สร้าง Supabase client
supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
