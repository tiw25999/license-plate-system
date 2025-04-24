from fastapi import Request, HTTPException, status
from app.config import supabase_client
import logging

logger = logging.getLogger(__name__)

async def verify_token(request: Request):
    """ตรวจสอบ token ของผู้ใช้
    สามารถใช้ได้ทั้ง session token และ JWT token ของ Supabase
    """
    try:
        # ดึง token จาก header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None
        
        token = auth_header.split(" ")[1]
        
        # ลองตรวจสอบกับ session ก่อน (เนื่องจากอาจเป็น session token ที่เราสร้างเอง)
        session_data = supabase_client.rpc(
            'validate_session',
            {'p_session_token': token}
        ).execute()
        
        if session_data.data and session_data.data[0]['is_valid']:
            # ถ้า session token ถูกต้อง
            user_id = session_data.data[0]['user_id']
            role = session_data.data[0]['role']
            
            # ดึงข้อมูลผู้ใช้จาก auth.users
            user_data = supabase_client.table("auth.users").select("*").eq("id", user_id).single().execute()
            
            if user_data.data:
                # เก็บข้อมูลผู้ใช้ใน request state
                request.state.user = user_data.data
                request.state.role = role
                request.state.session_token = token
                return request.state.user
        
        # ถ้า session token ไม่ถูกต้อง ให้ลองตรวจสอบกับ JWT token ของ Supabase
        response = supabase_client.auth.get_user(token)
        
        if not hasattr(response, 'error') or not response.error:
            # เก็บข้อมูลผู้ใช้ใน request state
            request.state.user = response.user
            
            # ดึงข้อมูล role
            role_data = supabase_client.table("user_roles").select("role").eq("user_id", response.user.id).execute()
            
            if role_data.data and len(role_data.data) > 0:
                request.state.role = role_data.data[0]["role"]
            else:
                request.state.role = "member"  # ค่าเริ่มต้น
            
            request.state.jwt_token = token
            return request.state.user
        
        return None
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
    if hasattr(request.state, "session_token") or hasattr(request.state, "jwt_token"):
        try:
            # บันทึกกิจกรรมการใช้งาน API
            supabase_client.rpc(
                'log_activity',
                {
                    'p_user_id': user.id if hasattr(user, 'id') else user['id'],
                    'p_action': f"API_{request.method}",
                    'p_table_name': None,
                    'p_record_id': None,
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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="คุณไม่มีสิทธิ์ในการเข้าถึงส่วนนี้"
        )
    
    # บันทึกกิจกรรม admin
    if hasattr(request.state, "session_token") or hasattr(request.state, "jwt_token"):
        try:
            # บันทึกกิจกรรมการใช้งาน API โดย admin
            supabase_client.rpc(
                'log_activity',
                {
                    'p_user_id': user.id if hasattr(user, 'id') else user['id'],
                    'p_action': f"ADMIN_{request.method}",
                    'p_table_name': None,
                    'p_record_id': None,
                    'p_description': f"Admin API Request: {request.url.path}",
                    'p_ip_address': request.client.host if request.client else None,
                    'p_user_agent': request.headers.get("user-agent")
                }
            ).execute()
        except Exception as e:
            logger.error(f"Error logging admin activity: {str(e)}")
    
    return user