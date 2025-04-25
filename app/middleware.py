from fastapi import Request, HTTPException, status
from app.security import verify_token as jwt_verify_token
from app.config import supabase_client
import logging

logger = logging.getLogger(__name__)

async def verify_token(request: Request):
    """ตรวจสอบ token ของผู้ใช้ (JWT)"""
    try:
        # ดึง token จาก header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None
        
        token = auth_header.split(" ")[1]
        
        # ตรวจสอบ JWT token
        payload = jwt_verify_token(token)
        if not payload:
            return None
        
        # ดึงข้อมูลผู้ใช้จากฐานข้อมูล
        user_id = payload.get("sub")
        if not user_id:
            return None
            
        user_data = supabase_client.table("users").select("*").eq("id", user_id).single().execute()
        
        if not user_data.data:
            return None
            
        # เก็บข้อมูลผู้ใช้ใน request state
        request.state.user = user_data.data
        request.state.role = user_data.data.get("role")
        request.state.token = token
        
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
    
    # บันทึกกิจกรรม
    if hasattr(request.state, "user"):
        try:
            # บันทึกกิจกรรมการใช้งาน API
            supabase_client.rpc(
                'log_activity',
                {
                    'p_user_id': user.get('id'),
                    'p_action': f"API_{request.method}",
                    'p_description': f"API Request: {request.url.path}",
                    'p_ip_address': request.client.host if request.client else None,
                    'p_user_agent': request.headers.get("user-agent")
                }
            ).execute()
        except Exception as e:
            logger.error(f"Error logging activity: {str(e)}")
    
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
        # ตรวจสอบว่าเป็น admin หรือไม่
        if user.get("role") != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="คุณไม่มีสิทธิ์ในการเข้าถึงส่วนนี้"
            )
        
        # เก็บบทบาทใน request state
        request.state.role = "admin"
    
    return user