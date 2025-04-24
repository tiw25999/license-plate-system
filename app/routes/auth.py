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
async def signup(user: UserSignUp, request: Request):
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
        if hasattr(response, 'error') and response.error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"การสมัครสมาชิกล้มเหลว: {response.error.message}"
            )
        
        # ดึงข้อมูลผู้ใช้และ token
        user_data = response.user
        session = response.session
        
        # กำหนดให้เป็น member โดยค่าเริ่มต้น
        supabase_client.rpc(
            'set_user_role',
            {
                'target_user_id': user_data.id,
                'new_role': 'member'
            }
        ).execute()
        
        # สร้าง session ใหม่
        session_data = supabase_client.rpc(
            'create_user_session',
            {
                'p_user_id': user_data.id,
                'p_ip_address': request.client.host if request.client else None,
                'p_user_agent': request.headers.get("user-agent")
            }
        ).execute()
        
        session_token = None
        if session_data.data and len(session_data.data) > 0:
            session_token = session_data.data[0]['session_token']
        
        # บันทึกกิจกรรม
        supabase_client.rpc(
            'log_activity',
            {
                'p_user_id': user_data.id,
                'p_action': 'signup',
                'p_table_name': 'auth.users',
                'p_record_id': user_data.id,
                'p_description': 'สมัครสมาชิกใหม่',
                'p_ip_address': request.client.host if request.client else None,
                'p_user_agent': request.headers.get("user-agent")
            }
        ).execute()
        
        return {
            "id": user_data.id,
            "email": user_data.email,
            "role": "member",
            "token": session_token or session.access_token
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
        # เข้าสู่ระบบด้วย Supabase Auth
        response = supabase_client.auth.sign_in_with_password({
            "email": user.email,
            "password": user.password
        })
        
        # ตรวจสอบการเข้าสู่ระบบ
        if hasattr(response, 'error') and response.error:
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
        
        # สร้าง session ใหม่
        session_data = supabase_client.rpc(
            'create_user_session',
            {
                'p_user_id': user_data.id,
                'p_ip_address': request.client.host if request.client else None,
                'p_user_agent': request.headers.get("user-agent")
            }
        ).execute()
        
        session_token = None
        if session_data.data and len(session_data.data) > 0:
            session_token = session_data.data[0]['session_token']
            
        # บันทึกกิจกรรม
        supabase_client.rpc(
            'log_activity',
            {
                'p_user_id': user_data.id,
                'p_action': 'login',
                'p_description': 'เข้าสู่ระบบ',
                'p_ip_address': request.client.host if request.client else None,
                'p_user_agent': request.headers.get("user-agent")
            }
        ).execute()
        
        return {
            "id": user_data.id,
            "email": user_data.email,
            "role": role,
            "token": session_token or session.access_token
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
async def logout(token: str, request: Request):
    """ออกจากระบบ"""
    try:
        user_id = None
        
        # ตรวจสอบว่าเป็น session token หรือไม่
        session_data = supabase_client.rpc(
            'validate_session',
            {'p_session_token': token}
        ).execute()
        
        if session_data.data and session_data.data[0]['is_valid']:
            # ถ้าเป็น session token
            user_id = session_data.data[0]['user_id']
            
            # ยกเลิก session
            supabase_client.rpc(
                'end_session',
                {'p_session_token': token}
            ).execute()
        else:
            # ถ้าเป็น JWT token ของ Supabase
            response = supabase_client.auth.get_user(token)
            if not hasattr(response, 'error') or not response.error:
                user_id = response.user.id
            
            # ออกจากระบบด้วย Supabase Auth
            supabase_client.auth.sign_out(token)
        
        # บันทึกกิจกรรม
        if user_id:
            supabase_client.rpc(
                'log_activity',
                {
                    'p_user_id': user_id,
                    'p_action': 'logout',
                    'p_description': 'ออกจากระบบ',
                    'p_ip_address': request.client.host if request.client else None,
                    'p_user_agent': request.headers.get("user-agent")
                }
            ).execute()
        
        return {"message": "ออกจากระบบสำเร็จ"}
    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการออกจากระบบ: {str(e)}"
        )

@auth_router.post("/logout-all")
async def logout_all(token: str, request: Request):
    """ออกจากระบบทุกอุปกรณ์"""
    try:
        user_id = None
        
        # ตรวจสอบว่าเป็น session token หรือไม่
        session_data = supabase_client.rpc(
            'validate_session',
            {'p_session_token': token}
        ).execute()
        
        if session_data.data and session_data.data[0]['is_valid']:
            # ถ้าเป็น session token
            user_id = session_data.data[0]['user_id']
        else:
            # ถ้าเป็น JWT token ของ Supabase
            response = supabase_client.auth.get_user(token)
            if not hasattr(response, 'error') or not response.error:
                user_id = response.user.id
        
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token ไม่ถูกต้องหรือหมดอายุ"
            )
        
        # ยกเลิก session ทั้งหมด
        supabase_client.rpc(
            'end_all_user_sessions',
            {'p_user_id': user_id}
        ).execute()
        
        # บันทึกกิจกรรม
        supabase_client.rpc(
            'log_activity',
            {
                'p_user_id': user_id,
                'p_action': 'logout_all',
                'p_description': 'ออกจากระบบทุกอุปกรณ์',
                'p_ip_address': request.client.host if request.client else None,
                'p_user_agent': request.headers.get("user-agent")
            }
        ).execute()
        
        return {"message": "ออกจากระบบทุกอุปกรณ์สำเร็จ"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Logout all error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการออกจากระบบทุกอุปกรณ์: {str(e)}"
        )

@auth_router.get("/me", response_model=UserInfo)
async def get_current_user(token: str):
    """ดึงข้อมูลผู้ใช้ปัจจุบัน"""
    try:
        # ตรวจสอบว่าเป็น session token หรือไม่
        session_data = supabase_client.rpc(
            'validate_session',
            {'p_session_token': token}
        ).execute()
        
        if session_data.data and session_data.data[0]['is_valid']:
            # ถ้าเป็น session token
            user_id = session_data.data[0]['user_id']
            role = session_data.data[0]['role']
            
            # ดึงข้อมูลผู้ใช้จาก auth.users
            user_data = supabase_client.table("auth.users").select("*").eq("id", user_id).single().execute()
            
            if not user_data.data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="ไม่พบข้อมูลผู้ใช้"
                )
            
            return {
                "id": user_id,
                "email": user_data.data["email"],
                "role": role
            }
        else:
            # ถ้าเป็น JWT token ของ Supabase
            response = supabase_client.auth.get_user(token)
            
            if hasattr(response, 'error') and response.error:
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
    except HTTPException:
        raise
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
        is_admin = False
        user_id = None
        
        # ตรวจสอบว่าเป็น session token หรือไม่
        session_data = supabase_client.rpc(
            'validate_session',
            {'p_session_token': token}
        ).execute()
        
        if session_data.data and session_data.data[0]['is_valid']:
            # ถ้าเป็น session token
            user_id = session_data.data[0]['user_id']
            role = session_data.data[0]['role']
            is_admin = (role == 'admin')
        else:
            # ถ้าเป็น JWT token ของ Supabase
            response = supabase_client.auth.get_user(token)
            
            if hasattr(response, 'error') and response.error:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token ไม่ถูกต้องหรือหมดอายุ"
                )
            
            user_id = response.user.id
            
            # ตรวจสอบว่าเป็น admin หรือไม่
            is_admin_result = supabase_client.rpc(
                'is_admin',
                {'user_id': user_id}
            ).execute()
            
            if is_admin_result.data:
                is_admin = is_admin_result.data
        
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="คุณไม่มีสิทธิ์ในการดูรายชื่อผู้ใช้ทั้งหมด"
            )
        
        # ดึงข้อมูลผู้ใช้จาก Supabase
        users_with_roles = supabase_client.rpc(
            'get_users_with_roles'
        ).execute()
        
        if hasattr(users_with_roles, 'error') and users_with_roles.error:
            raise Exception(f"Error fetching users: {users_with_roles.error.message}")
        
        return users_with_roles.data
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get users error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาด: {str(e)}"
        )

@auth_router.post("/update-role")
async def update_user_role(role_update: UserRoleUpdate, token: str, request: Request):
    """อัพเดท role ของผู้ใช้ (สำหรับ admin เท่านั้น)"""
    try:
        is_admin = False
        user_id = None
        
        # ตรวจสอบว่าเป็น session token หรือไม่
        session_data = supabase_client.rpc(
            'validate_session',
            {'p_session_token': token}
        ).execute()
        
        if session_data.data and session_data.data[0]['is_valid']:
            # ถ้าเป็น session token
            user_id = session_data.data[0]['user_id']
            role = session_data.data[0]['role']
            is_admin = (role == 'admin')
        else:
            # ถ้าเป็น JWT token ของ Supabase
            response = supabase_client.auth.get_user(token)
            
            if hasattr(response, 'error') and response.error:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token ไม่ถูกต้องหรือหมดอายุ"
                )
            
            user_id = response.user.id
            
            # ตรวจสอบว่าเป็น admin หรือไม่
            is_admin_result = supabase_client.rpc(
                'is_admin',
                {'user_id': user_id}
            ).execute()
            
            if is_admin_result.data:
                is_admin = is_admin_result.data
        
        if not is_admin:
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
        result = supabase_client.rpc(
            'set_user_role',
            {
                'target_user_id': role_update.user_id,
                'new_role': role_update.role
            }
        ).execute()
        
        if hasattr(result, 'error') and result.error:
            raise Exception(f"Error updating role: {result.error.message}")
        
        # บันทึกกิจกรรม
        supabase_client.rpc(
            'log_activity',
            {
                'p_user_id': user_id,
                'p_action': 'update_role',
                'p_table_name': 'user_roles',
                'p_record_id': role_update.user_id,
                'p_description': f'อัพเดท role ของผู้ใช้ {role_update.user_id} เป็น {role_update.role}',
                'p_ip_address': request.client.host if request.client else None,
                'p_user_agent': request.headers.get("user-agent")
            }
        ).execute()
        
        return {"message": f"อัพเดท role เป็น {role_update.role} สำเร็จ"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update role error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาด: {str(e)}"
        )

@auth_router.post("/change-password")
async def change_password(password_data: ChangePassword, token: str, request: Request):
    """เปลี่ยนรหัสผ่าน"""
    try:
        user_id = None
        user_email = None
        
        # ตรวจสอบว่าเป็น session token หรือไม่
        session_data = supabase_client.rpc(
            'validate_session',
            {'p_session_token': token}
        ).execute()
        
        if session_data.data and session_data.data[0]['is_valid']:
            # ถ้าเป็น session token
            user_id = session_data.data[0]['user_id']
            
            # ดึงข้อมูลผู้ใช้จาก auth.users
            user_data = supabase_client.table("auth.users").select("*").eq("id", user_id).single().execute()
            
            if user_data.data:
                user_email = user_data.data["email"]
        else:
            # ถ้าเป็น JWT token ของ Supabase
            response = supabase_client.auth.get_user(token)
            
            if hasattr(response, 'error') and response.error:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token ไม่ถูกต้องหรือหมดอายุ"
                )
            
            user_id = response.user.id
            user_email = response.user.email
        
        if not user_id or not user_email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="ไม่สามารถระบุตัวตนผู้ใช้ได้"
            )
        
        # ตรวจสอบรหัสผ่านปัจจุบัน
        try:
            login_response = supabase_client.auth.sign_in_with_password({
                "email": user_email,
                "password": password_data.current_password
            })
            
            if hasattr(login_response, 'error') and login_response.error:
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
            user_id,
            {"password": password_data.new_password}
        )
        
        if hasattr(update_response, 'error') and update_response.error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"การเปลี่ยนรหัสผ่านล้มเหลว: {update_response.error.message}"
            )
        
        # ออกจากระบบทุกอุปกรณ์ยกเว้นอุปกรณ์ปัจจุบัน
        if hasattr(session_data, 'data') and session_data.data and session_data.data[0]['is_valid']:
            current_session_token = token
            
            # ยกเลิก session ทั้งหมดยกเว้น session ปัจจุบัน
            supabase_client.table("user_sessions").delete().eq("user_id", user_id).neq("session_token", current_session_token).execute()
        else:
            # ยกเลิก session ทั้งหมด
            supabase_client.rpc(
                'end_all_user_sessions',
                {'p_user_id': user_id}
            ).execute()
        
        # บันทึกกิจกรรม
        supabase_client.rpc(
            'log_activity',
            {
                'p_user_id': user_id,
                'p_action': 'change_password',
                'p_description': 'เปลี่ยนรหัสผ่าน',
                'p_ip_address': request.client.host if request.client else None,
                'p_user_agent': request.headers.get("user-agent")
            }
        ).execute()
        
        return {"message": "เปลี่ยนรหัสผ่านสำเร็จ"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Change password error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาดในการเปลี่ยนรหัสผ่าน: {str(e)}"
        )

@auth_router.get("/sessions")
async def get_user_sessions(token: str):
    """ดึงรายการ session ทั้งหมดของผู้ใช้"""
    try:
        user_id = None
        
        # ตรวจสอบว่าเป็น session token หรือไม่
        session_data = supabase_client.rpc(
            'validate_session',
            {'p_session_token': token}
        ).execute()
        
        if session_data.data and session_data.data[0]['is_valid']:
            # ถ้าเป็น session token
            user_id = session_data.data[0]['user_id']
        else:
            # ถ้าเป็น JWT token ของ Supabase
            response = supabase_client.auth.get_user(token)
            
            if hasattr(response, 'error') and response.error:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token ไม่ถูกต้องหรือหมดอายุ"
                )
            
            user_id = response.user.id
        
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="ไม่สามารถระบุตัวตนผู้ใช้ได้"
            )
        
        # ดึงรายการ session
        sessions = supabase_client.table("user_sessions").select(
            "id, session_token, expires_at, ip_address, user_agent, last_active_at, created_at"
        ).eq("user_id", user_id).order("created_at", desc=True).execute()
        
        if hasattr(sessions, 'error') and sessions.error:
            raise Exception(f"Error fetching sessions: {sessions.error.message}")
        
        return sessions.data
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get sessions error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาด: {str(e)}"
        )

@auth_router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, token: str, request: Request):
    """ลบ session ตามที่ระบุ"""
    try:
        user_id = None
        
        # ตรวจสอบว่าเป็น session token หรือไม่
        session_data = supabase_client.rpc(
            'validate_session',
            {'p_session_token': token}
        ).execute()
        
        if session_data.data and session_data.data[0]['is_valid']:
            # ถ้าเป็น session token
            user_id = session_data.data[0]['user_id']
        else:
            # ถ้าเป็น JWT token ของ Supabase
            response = supabase_client.auth.get_user(token)
            
            if hasattr(response, 'error') and response.error:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token ไม่ถูกต้องหรือหมดอายุ"
                )
            
            user_id = response.user.id
        
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="ไม่สามารถระบุตัวตนผู้ใช้ได้"
            )
        
        # ตรวจสอบว่า session เป็นของผู้ใช้จริงๆ
        session = supabase_client.table("user_sessions").select("*").eq("id", session_id).eq("user_id", user_id).single().execute()
        
        if not session.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ไม่พบ session ที่ระบุ หรือคุณไม่มีสิทธิ์ในการลบ session นี้"
            )
        
        # ลบ session
        delete_result = supabase_client.table("user_sessions").delete().eq("id", session_id).eq("user_id", user_id).execute()
        
        if hasattr(delete_result, 'error') and delete_result.error:
            raise Exception(f"Error deleting session: {delete_result.error.message}")
        
        # บันทึกกิจกรรม
        supabase_client.rpc(
            'log_activity',
            {
                'p_user_id': user_id,
                'p_action': 'delete_session',
                'p_table_name': 'user_sessions',
                'p_record_id': session_id,
                'p_description': 'ลบ session',
                'p_ip_address': request.client.host if request.client else None,
                'p_user_agent': request.headers.get("user-agent")
            }
        ).execute()
        
        return {"message": "ลบ session สำเร็จ"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete session error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาด: {str(e)}"
        )

@auth_router.get("/activity-logs")
async def get_activity_logs(token: str, limit: int = 100):
    """ดึงรายการกิจกรรมของผู้ใช้"""
    try:
        user_id = None
        is_admin = False
        
        # ตรวจสอบว่าเป็น session token หรือไม่
        session_data = supabase_client.rpc(
            'validate_session',
            {'p_session_token': token}
        ).execute()
        
        if session_data.data and session_data.data[0]['is_valid']:
            # ถ้าเป็น session token
            user_id = session_data.data[0]['user_id']
            role = session_data.data[0]['role']
            is_admin = (role == 'admin')
        else:
            # ถ้าเป็น JWT token ของ Supabase
            response = supabase_client.auth.get_user(token)
            
            if hasattr(response, 'error') and response.error:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token ไม่ถูกต้องหรือหมดอายุ"
                )
            
            user_id = response.user.id
            
            # ตรวจสอบว่าเป็น admin หรือไม่
            is_admin_result = supabase_client.rpc(
                'is_admin',
                {'user_id': user_id}
            ).execute()
            
            if is_admin_result.data:
                is_admin = is_admin_result.data
        
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="ไม่สามารถระบุตัวตนผู้ใช้ได้"
            )
        
        # ดึงรายการกิจกรรม
        query = supabase_client.table("activity_logs").select("*")
        
        if not is_admin:
            # ถ้าไม่ใช่ admin ให้ดึงเฉพาะกิจกรรมของตัวเอง
            query = query.eq("user_id", user_id)
        
        logs = query.order("created_at", desc=True).limit(limit).execute()
        
        if hasattr(logs, 'error') and logs.error:
            raise Exception(f"Error fetching activity logs: {logs.error.message}")
        
        return logs.data
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get activity logs error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"เกิดข้อผิดพลาด: {str(e)}"
        )