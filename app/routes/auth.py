from fastapi import APIRouter, Depends, HTTPException, status, Request
from app.schemas import UserLogin, UserSignUp, UserResponse, UserRoleUpdate, UserInfo, ChangePassword
from app.config import supabase_client
from app.security import verify_password, get_password_hash, create_access_token
from app.middleware import verify_token  # แก้ไขการนำเข้า verify_token จาก middleware
from typing import Optional, List
from app.security import decode_access_token
import logging
import re
from datetime import timedelta

# ตั้งค่า logging
logger = logging.getLogger(__name__)

auth_router = APIRouter()

@auth_router.post("/signup", response_model=UserResponse)
async def signup(user: UserSignUp, request: Request):
    """สมัครสมาชิกใหม่"""
    try:
        # ตรวจสอบความถูกต้องของอีเมล
        if user.email:
            email_pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
            if not re.match(email_pattern, user.email):
                raise HTTPException(status_code=400, detail="รูปแบบอีเมลไม่ถูกต้อง")
        
        # ตรวจสอบว่ารหัสผ่านตรงกันหรือไม่
        if user.password != user.confirm_password:
            raise HTTPException(status_code=400, detail="รหัสผ่านไม่ตรงกัน")
        
        # ตรวจสอบความยาวของรหัสผ่าน
        if len(user.password) < 6:
            raise HTTPException(status_code=400, detail="รหัสผ่านต้องมีความยาวอย่างน้อย 6 ตัวอักษร")
        
        # ตรวจสอบความยาวของ username
        if len(user.username) < 3:
            raise HTTPException(status_code=400, detail="ชื่อผู้ใช้ต้องมีความยาวอย่างน้อย 3 ตัวอักษร")
        
        # สร้างผู้ใช้ใหม่โดยใช้ฟังก์ชัน register_user
        response = supabase_client.rpc(
            'register_user',
            {
                'p_username': user.username,
                'p_password': user.password,
                'p_email': user.email,
                'p_role': 'member'
            }
        ).execute()
        
        # ตรวจสอบการสร้างผู้ใช้
        if hasattr(response, 'error') and response.error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"การสมัครสมาชิกล้มเหลว: {response.error}"
            )
        
        # ดึงข้อมูลผู้ใช้
        user_id = response.data[0]  # register_user จะ return user_id
        
        # ดึงข้อมูลผู้ใช้จากตาราง users
        user_data = supabase_client.table("users").select("*").eq("id", user_id).single().execute()
        
        if not user_data.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่พบข้อมูลผู้ใช้หลังจากลงทะเบียน"
            )
        
        # สร้าง JWT token
        token_data = {
            "sub": str(user_id),
            "username": user.username,
            "role": "member"
        }
        access_token = create_access_token(token_data, timedelta(days=7))
        
        # บันทึกกิจกรรม
        supabase_client.rpc(
            'log_activity',
            {
                'p_user_id': user_id,
                'p_action': 'signup',
                'p_table_name': 'users',
                'p_record_id': user_id,
                'p_description': 'สมัครสมาชิกใหม่',
                'p_ip_address': request.client.host if request.client else None,
                'p_user_agent': request.headers.get("user-agent")
            }
        ).execute()
        
        return {
            "id": user_id,
            "username": user_data.data["username"],
            "email": user_data.data.get("email"),
            "role": "member",
            "token": access_token
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Signup error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการสมัครสมาชิก: {str(e)}"
        )

@auth_router.post("/login", response_model=UserResponse)
async def login(user: UserLogin, request: Request):
    """เข้าสู่ระบบ"""
    try:
        # เข้าสู่ระบบด้วยฟังก์ชัน login_user
        response = supabase_client.rpc(
            'login_user',
            {
                'p_username': user.username,
                'p_password': user.password
            }
        ).execute()
        
        # ตรวจสอบการเข้าสู่ระบบ
        if not response.data or not response.data[0].get('login_success'):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"
            )
        
        # ดึงข้อมูลผู้ใช้
        user_id = response.data[0]['user_id']
        username = response.data[0]['username']
        email = response.data[0]['email']
        role = response.data[0]['role']
        
        # สร้าง JWT token
        token_data = {
            "sub": str(user_id),
            "username": username,
            "role": role
        }
        access_token = create_access_token(token_data, timedelta(days=7))
        
        # บันทึกกิจกรรม
        supabase_client.rpc(
            'log_activity',
            {
                'p_user_id': user_id,
                'p_action': 'login',
                'p_description': 'เข้าสู่ระบบ',
                'p_ip_address': request.client.host if request.client else None,
                'p_user_agent': request.headers.get("user-agent")
            }
        ).execute()
        
        return {
            "id": user_id,
            "username": username,
            "email": email,
            "role": role,
            "token": access_token
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการเข้าสู่ระบบ: {str(e)}"
        )

@auth_router.post("/logout")
async def logout(request: Request):
    """ออกจากระบบ (ฝั่ง client จะต้องลบ token เอง)"""
    # เนื่องจากใช้ JWT ไม่ต้องทำอะไรในฝั่ง server
    return {"message": "ออกจากระบบสำเร็จ"}

@auth_router.get("/me", response_model=UserInfo)
async def get_current_user(request: Request):
    """ดึงข้อมูลผู้ใช้ปัจจุบัน"""
    try:
        # ดึง token จาก header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="ไม่ได้เข้าสู่ระบบ"
            )
        
        token = auth_header.split(" ")[1]
        
        # ตรวจสอบ JWT token
        payload = decode_access_token(token)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token ไม่ถูกต้องหรือหมดอายุ"
            )
        
        # ดึงข้อมูลผู้ใช้จากฐานข้อมูล
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token ไม่ถูกต้อง"
            )
            
        user_data = supabase_client.table("users").select("*").eq("id", user_id).single().execute()
        
        if not user_data.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ไม่พบข้อมูลผู้ใช้"
            )
        
        return {
            "id": user_data.data.get("id"),
            "username": user_data.data.get("username"),
            "email": user_data.data.get("email"),
            "role": user_data.data.get("role")
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting current user: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาด: {str(e)}"
        )