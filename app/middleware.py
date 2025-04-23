from fastapi import Request, HTTPException, status
from app.config import supabase_client
import logging

logger = logging.getLogger(__name__)

async def verify_token(request: Request):
    """ตรวจสอบ token ของผู้ใช้"""
    try:
        # ดึง token จาก header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None
        
        token = auth_header.split(" ")[1]
        
        # ตรวจสอบ token กับ Supabase
        response = supabase_client.auth.get_user(token)
        
        if response.error:
            return None
        
        # เก็บข้อมูลผู้ใช้ใน request state
        request.state.user = response.user
        
        # ดึงข้อมูล role
        role_data = supabase_client.table("user_roles").select("role").eq("user_id", response.user.id).execute()
        
        if role_data.data and len(role_data.data) > 0:
            request.state.role = role_data.data[0]["role"]
        else:
            request.state.role = "member"  # ค่าเริ่มต้น
        
        return request.state.user
    except Exception as e:
        logger.error(f"Token verification error: {str(e)}")
        return None

async def require_auth(request: Request):
    """บังคับให้ผู้ใช้ต้องเข้าสู่ระบบก่อน"""
    user = await verify_token(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="กรุณาเข้าสู่ระบบก่อนใช้งาน"
        )
    return user

async def require_admin(request: Request):
    """บังคับให้ผู้ใช้ต้องเป็น admin"""
    user = await verify_token(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="กรุณาเข้าสู่ระบบก่อนใช้งาน"
        )
    
    if not hasattr(request.state, "role") or request.state.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="คุณไม่มีสิทธิ์ในการเข้าถึงส่วนนี้"
        )
    
    return user