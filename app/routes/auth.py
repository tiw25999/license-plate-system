from fastapi import APIRouter, Depends, HTTPException, status, Request
from app.schemas import UserLogin, UserSignUp, UserResponse, UserRoleUpdate, UserInfo, ChangePassword
from app.config import supabase_client
from typing import Optional, List
import logging
import re

# ตั้งค่า logging
logger = logging.getLogger(__name__)

auth_router = APIRouter()

@auth_router.post("/signup", response_model=UserResponse)
async def signup(user: UserSignUp):
    """สมัครสมาชิกใหม่"""
    try:
        # ตรวจสอบความถูกต้องของอีเมล
        email_pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
        if not re.match(email_pattern, user.email):
            raise HTTPException(status_code=400, detail="รูปแบบอีเมลไม่ถูกต้อง")
        
        # ตรวจสอบว่ารหัสผ่านตรงกันหรือไม่
        if user.password != user.confirm_password:
            raise HTTPException(status_code=400, detail="รหัสผ่านไม่ตรงกัน")
        
        # ตรวจสอบความยาวของรหัสผ่าน
        if len(user.password) < 6:
            raise HTTPException(status_code=400, detail="รหัสผ่านต้องมีความยาวอย่างน้อย 6 ตัวอักษร")
        
        # สร้างผู้ใช้ใหม่ใน Supabase Auth
        response = supabase_client.auth.sign_up({
            "email": user.email,
            "password": user.password
        })
        
        # ตรวจสอบการสร้างผู้ใช้
        if response.error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"การสมัครสมาชิกล้มเหลว: {response.error.message}"
            )
        
        # ดึงข้อมูลผู้ใช้และ token
        user_data = response.user
        session = response.session
        
        # กำหนดให้เป็น member โดยค่าเริ่มต้น
        supabase_client.table("user_roles").insert({
            "user_id": user_data.id,
            "role": "member"
        }).execute()
        
        return {
            "id": user_data.id,
            "email": user_data.email,
            "role": "member",
            "token": session.access_token
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
async def login(user: UserLogin):
    """เข้าสู่ระบบ"""
    try:
        # เข้าสู่ระบบด้วย Supabase Auth
        response = supabase_client.auth.sign_in_with_password({
            "email": user.email,
            "password": user.password
        })
        
        # ตรวจสอบการเข้าสู่ระบบ
        if response.error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="อีเมลหรือรหัสผ่านไม่ถูกต้อง"
            )
        
        # ดึงข้อมูลผู้ใช้และ token
        user_data = response.user
        session = response.session
        
        # ดึงข้อมูล role จากตาราง user_roles
        role_data = supabase_client.table("user_roles").select("role").eq("user_id", user_data.id).execute()
        
        role = "member"  # ค่าเริ่มต้น
        if role_data.data and len(role_data.data) > 0:
            role = role_data.data[0]["role"]
        
        return {
            "id": user_data.id,
            "email": user_data.email,
            "role": role,
            "token": session.access_token
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
async def logout(token: str):
    """ออกจากระบบ"""
    try:
        # ออกจากระบบด้วย Supabase Auth
        response = supabase_client.auth.sign_out(token)
        
        if response.error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"การออกจากระบบล้มเหลว: {response.error.message}"
            )
        
        return {"message": "ออกจากระบบสำเร็จ"}
    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการออกจากระบบ: {str(e)}"
        )

@auth_router.get("/me", response_model=UserInfo)
async def get_current_user(token: str):
    """ดึงข้อมูลผู้ใช้ปัจจุบัน"""
    try:
        # ตรวจสอบ token
        response = supabase_client.auth.get_user(token)
        
        if response.error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token ไม่ถูกต้องหรือหมดอายุ"
            )
        
        user_data = response.user
        
        # ดึงข้อมูล role จากตาราง user_roles
        role_data = supabase_client.table("user_roles").select("role").eq("user_id", user_data.id).execute()
        
        role = None
        if role_data.data and len(role_data.data) > 0:
            role = role_data.data[0]["role"]
        
        return {
            "id": user_data.id,
            "email": user_data.email,
            "role": role
        }
    except Exception as e:
        logger.error(f"Get current user error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาด: {str(e)}"
        )

@auth_router.get("/users", response_model=List[UserInfo])
async def get_users(token: str):
    """ดึงรายชื่อผู้ใช้ทั้งหมด (สำหรับ admin เท่านั้น)"""
    try:
        # ตรวจสอบ token
        response = supabase_client.auth.get_user(token)
        
        if response.error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token ไม่ถูกต้องหรือหมดอายุ"
            )
        
        user_data = response.user
        
        # ตรวจสอบว่าเป็น admin หรือไม่
        role_data = supabase_client.table("user_roles").select("role").eq("user_id", user_data.id).execute()
        
        if not role_data.data or len(role_data.data) == 0 or role_data.data[0]["role"] != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="คุณไม่มีสิทธิ์ในการดูรายชื่อผู้ใช้ทั้งหมด"
            )
        
        # ดึงข้อมูลผู้ใช้จาก Supabase
        users_with_roles = supabase_client.rpc(
            'get_users_with_roles'
        ).execute()
        
        if users_with_roles.error:
            raise Exception(f"Error fetching users: {users_with_roles.error.message}")
        
        return users_with_roles.data
    except Exception as e:
        logger.error(f"Get users error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาด: {str(e)}"
        )

@auth_router.post("/update-role")
async def update_user_role(role_update: UserRoleUpdate, token: str):
    """อัพเดท role ของผู้ใช้ (สำหรับ admin เท่านั้น)"""
    try:
        # ตรวจสอบ token
        response = supabase_client.auth.get_user(token)
        
        if response.error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token ไม่ถูกต้องหรือหมดอายุ"
            )
        
        user_data = response.user
        
        # ตรวจสอบว่าเป็น admin หรือไม่
        role_data = supabase_client.table("user_roles").select("role").eq("user_id", user_data.id).execute()
        
        if not role_data.data or len(role_data.data) == 0 or role_data.data[0]["role"] != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="คุณไม่มีสิทธิ์ในการอัพเดท role"
            )
        
        # ตรวจสอบว่า role ที่จะอัพเดทถูกต้องหรือไม่
        if role_update.role not in ["admin", "member"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Role ไม่ถูกต้อง (ต้องเป็น 'admin' หรือ 'member')"
            )
        
        # อัพเดท role
        result = supabase_client.table("user_roles").upsert({
            "user_id": role_update.user_id,
            "role": role_update.role,
            "updated_at": "now()"
        }).execute()
        
        if result.error:
            raise Exception(f"Error updating role: {result.error.message}")
        
        return {"message": f"อัพเดท role เป็น {role_update.role} สำเร็จ"}
    except Exception as e:
        logger.error(f"Update role error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาด: {str(e)}"
        )

@auth_router.post("/change-password")
async def change_password(password_data: ChangePassword, token: str):
    """เปลี่ยนรหัสผ่าน"""
    try:
        # ตรวจสอบ token
        response = supabase_client.auth.get_user(token)
        
        if response.error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token ไม่ถูกต้องหรือหมดอายุ"
            )
        
        user_data = response.user
        
        # ตรวจสอบรหัสผ่านปัจจุบัน
        try:
            login_response = supabase_client.auth.sign_in_with_password({
                "email": user_data.email,
                "password": password_data.current_password
            })
            
            if login_response.error:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="รหัสผ่านปัจจุบันไม่ถูกต้อง"
                )
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="รหัสผ่านปัจจุบันไม่ถูกต้อง"
            )
        
        # ตรวจสอบรหัสผ่านใหม่
        if len(password_data.new_password) < 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="รหัสผ่านใหม่ต้องมีความยาวอย่างน้อย 6 ตัวอักษร"
            )
        
        # เปลี่ยนรหัสผ่าน
        update_response = supabase_client.auth.admin.update_user_by_id(
            user_data.id,
            {"password": password_data.new_password}
        )
        
        if update_response.error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"การเปลี่ยนรหัสผ่านล้มเหลว: {update_response.error.message}"
            )
        
        return {"message": "เปลี่ยนรหัสผ่านสำเร็จ"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Change password error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการเปลี่ยนรหัสผ่าน: {str(e)}"
        )