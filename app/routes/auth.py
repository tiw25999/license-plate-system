from fastapi import APIRouter, Depends, HTTPException, status, Request
from app.schemas import UserLogin, UserSignUp, UserResponse, UserRoleUpdate, UserInfo, ChangePassword
from app.config import supabase_client
from app.security import verify_password, get_password_hash, create_access_token
from app.middleware import verify_token, require_auth, require_admin
from typing import Optional, List
from app.security import decode_access_token
import logging
import re
import uuid
from datetime import timedelta
from pydantic import BaseModel

# ตั้งค่า logging
logger = logging.getLogger(__name__)

auth_router = APIRouter()

# เพิ่ม schema สำหรับการสร้างผู้ใช้โดย admin
class UserCreate(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    role: str = "member"

# เพิ่ม schema สำหรับการลบผู้ใช้
class UserDelete(BaseModel):
    user_id: str


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
        access_token = create_access_token(token_data, timedelta(days=30))  # เพิ่มเป็น 30 วัน
        
        # บันทึกกิจกรรม
        try:
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
        except Exception as log_err:
            logger.error(f"Error logging login activity: {str(log_err)}")
        
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

@auth_router.get("/users")
async def get_users(request: Request, user = Depends(require_admin)):
    """ดึงรายชื่อผู้ใช้ทั้งหมด (สำหรับ admin เท่านั้น)"""
    try:
        # ดึงข้อมูลผู้ใช้ทั้งหมดจากฐานข้อมูล
        response = supabase_client.table("users").select("*").execute()
        
        if hasattr(response, 'error') and response.error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database Error: {response.error}"
            )
        
        # ส่งข้อมูลกลับไป (ไม่รวมรหัสผ่าน)
        users = []
        for user_data in response.data:
            user_info = {
                "id": user_data.get("id"),
                "username": user_data.get("username"),
                "email": user_data.get("email"),
                "role": user_data.get("role"),
                "created_at": user_data.get("created_at")
            }
            users.append(user_info)
        
        return users
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting users: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาด: {str(e)}"
        )

@auth_router.post("/update-role")
async def update_user_role(role_update: UserRoleUpdate, request: Request, user = Depends(require_admin)):
    """อัพเดทสิทธิ์ผู้ใช้ (สำหรับ admin เท่านั้น)"""
    try:
        # ตรวจสอบว่า role ถูกต้องหรือไม่
        if role_update.role not in ["admin", "member"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="สิทธิ์ไม่ถูกต้อง (ต้องเป็น 'admin' หรือ 'member')"
            )
        
        # อัพเดทสิทธิ์ผู้ใช้
        response = supabase_client.table("users").update(
            {"role": role_update.role}
        ).eq("id", role_update.user_id).execute()
        
        if hasattr(response, 'error') and response.error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database Error: {response.error}"
            )
        
        # ตรวจสอบว่ามีการอัพเดทข้อมูลหรือไม่
        if not response.data or len(response.data) == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ไม่พบผู้ใช้ที่ระบุ"
            )
        
        # บันทึกกิจกรรม - แก้ไขการเรียกใช้ log_activity
        admin_id = user.get('id') if isinstance(user, dict) else user.id
        
        # แก้ไขการส่ง record_id
        try:
            # สร้างพารามิเตอร์สำหรับ log_activity โดยไม่รวม p_record_id
            log_params = {
                'p_user_id': admin_id,
                'p_action': 'update_role',
                'p_table_name': 'users',
                'p_description': f'อัพเดทสิทธิ์ผู้ใช้ ID {role_update.user_id} เป็น {role_update.role}',
                'p_ip_address': request.client.host if request.client else None,
                'p_user_agent': request.headers.get("user-agent")
            }
            
            # ทดลองเพิ่ม record_id ถ้ามีการตรวจสอบแล้วว่าเป็น UUID ที่ถูกต้อง
            try:
                if role_update.user_id and isinstance(role_update.user_id, str):
                    uuid_obj = uuid.UUID(role_update.user_id)
                    log_params['p_record_id'] = str(uuid_obj)
            except (ValueError, TypeError):
                # ถ้าแปลงไม่ได้ ไม่ต้องใส่ p_record_id
                logger.warning(f"Invalid UUID format for user_id: {role_update.user_id}")
            
            supabase_client.rpc('log_activity', log_params).execute()
        except Exception as log_err:
            logger.error(f"Error logging role update activity: {str(log_err)}")
        
        return {"message": "อัพเดทสิทธิ์ผู้ใช้สำเร็จ", "user_id": role_update.user_id, "role": role_update.role}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user role: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาด: {str(e)}"
        )

@auth_router.post("/create-user")
async def create_user(user_data: UserCreate, request: Request, current_user = Depends(require_admin)):
    """สร้างผู้ใช้ใหม่ (สำหรับ admin เท่านั้น)"""
    try:
        # ตรวจสอบความถูกต้องของอีเมล
        if user_data.email:
            email_pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
            if not re.match(email_pattern, user_data.email):
                raise HTTPException(status_code=400, detail="รูปแบบอีเมลไม่ถูกต้อง")
        
        # ตรวจสอบความยาวของรหัสผ่าน
        if len(user_data.password) < 6:
            raise HTTPException(status_code=400, detail="รหัสผ่านต้องมีความยาวอย่างน้อย 6 ตัวอักษร")
        
        # ตรวจสอบความยาวของ username
        if len(user_data.username) < 3:
            raise HTTPException(status_code=400, detail="ชื่อผู้ใช้ต้องมีความยาวอย่างน้อย 3 ตัวอักษร")
        
        # ตรวจสอบว่า role ถูกต้องหรือไม่
        if user_data.role not in ["admin", "member"]:
            raise HTTPException(status_code=400, detail="สิทธิ์ไม่ถูกต้อง (ต้องเป็น 'admin' หรือ 'member')")
        
        # สร้างผู้ใช้ใหม่โดยใช้ฟังก์ชัน register_user
        response = supabase_client.rpc(
            'register_user',
            {
                'p_username': user_data.username,
                'p_password': user_data.password,
                'p_email': user_data.email,
                'p_role': user_data.role
            }
        ).execute()
        
        # ตรวจสอบการสร้างผู้ใช้
        if hasattr(response, 'error') and response.error:
            logger.error(f"Register user error: {response.error}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"การสร้างผู้ใช้ล้มเหลว: {response.error}"
            )
        
        # ดึงข้อมูลผู้ใช้
        if not response.data or len(response.data) == 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถสร้างผู้ใช้ได้"
            )
            
        user_id = response.data[0]  # register_user จะ return user_id
        
        # ตรวจสอบว่าได้รับ user_id จริง
        if not user_id:
            logger.error("No user_id returned from register_user function")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่สามารถสร้างผู้ใช้ได้"
            )
        
        # ดึงข้อมูลผู้ใช้จากตาราง users
        user_data_response = supabase_client.table("users").select("*").eq("id", user_id).single().execute()
        
        if not user_data_response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ไม่พบข้อมูลผู้ใช้หลังจากลงทะเบียน"
            )
        
        # บันทึกกิจกรรม - แก้ไขให้ดีขึ้น
        try:
            admin_id = current_user.get('id') if isinstance(current_user, dict) else current_user.id
            
            # สร้างพารามิเตอร์โดยไม่รวม p_record_id
            log_params = {
                'p_user_id': admin_id,
                'p_action': 'create_user',
                'p_table_name': 'users',
                'p_description': f'สร้างผู้ใช้ใหม่: {user_data.username}',
                'p_ip_address': request.client.host if request.client else None,
                'p_user_agent': request.headers.get("user-agent")
            }
            
            # ลดโค้ดที่พยายามจัดการกับ UUID เพื่อหลีกเลี่ยงความผิดพลาด
            # ไม่จำเป็นต้องส่ง p_record_id ในการบันทึกกิจกรรมนี้
            
            supabase_client.rpc('log_activity', log_params).execute()
        except Exception as log_err:
            logger.error(f"Error logging user creation activity: {str(log_err)}")
        
        return {
            "id": user_id,
            "username": user_data_response.data["username"],
            "email": user_data_response.data.get("email"),
            "role": user_data_response.data.get("role")
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating user: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาด: {str(e)}"
        )

@auth_router.post("/delete-user")
async def delete_user(user_data: UserDelete, request: Request, current_user = Depends(require_admin)):
    """ลบผู้ใช้ (สำหรับ admin เท่านั้น)"""
    try:
        # ตรวจสอบว่าไม่ใช่การลบตัวเอง
        admin_id = current_user.get('id') if isinstance(current_user, dict) else current_user.id
        if str(user_data.user_id) == str(admin_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ไม่สามารถลบบัญชีของตัวเองได้"
            )
        
        # ตรวจสอบว่าผู้ใช้มีอยู่หรือไม่
        user_check = supabase_client.table("users").select("id, username").eq("id", user_data.user_id).single().execute()
        
        if not user_check.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ไม่พบผู้ใช้ที่ระบุ"
            )
        
        username = user_check.data.get('username')
        
        # ลบผู้ใช้
        response = supabase_client.table("users").delete().eq("id", user_data.user_id).execute()
        
        if hasattr(response, 'error') and response.error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database Error: {response.error}"
            )
        
        # บันทึกกิจกรรม - แก้ไขการเรียกใช้ log_activity
        try:
            # สร้างพารามิเตอร์โดยไม่รวม p_record_id
            log_params = {
                'p_user_id': admin_id,
                'p_action': 'delete_user',
                'p_table_name': 'users',
                'p_description': f'ลบผู้ใช้: {username}',
                'p_ip_address': request.client.host if request.client else None,
                'p_user_agent': request.headers.get("user-agent")
            }
            
            # ลดโค้ดที่พยายามจัดการกับ UUID เพื่อหลีกเลี่ยงความผิดพลาด
            # ไม่จำเป็นต้องส่ง p_record_id ในการบันทึกกิจกรรมนี้
            
            supabase_client.rpc('log_activity', log_params).execute()
        except Exception as log_err:
            logger.error(f"Error logging user deletion activity: {str(log_err)}")
        
        return {"message": f"ลบผู้ใช้ {username} เรียบร้อยแล้ว", "user_id": user_data.user_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting user: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาด: {str(e)}"
        )