# app/routes/auth.py

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from datetime import datetime, timedelta
from jose import jwt, JWTError
from passlib.hash import bcrypt
from slowapi.extension import Limiter
from slowapi.util import get_remote_address
from dotenv import load_dotenv
import os

from app.config import supabase_client
from app.utils.log_utils import log_activity

# โหลดตัวแปรแวดล้อมจาก .env
load_dotenv()

# คอนสแตนต์สำหรับ JWT
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60       # อายุ token (นาที)
REFRESH_TOKEN_EXPIRE_DAYS = 7          # อายุ refresh token (วัน)

# ตั้ง rate limiter และ HTTP Bearer
limiter = Limiter(key_func=get_remote_address)
security = HTTPBearer()

# สร้าง router พร้อม prefix /auth
auth_router = APIRouter(prefix="/auth", tags=["auth"])


# ——— Schemas ———

class SignupRequest(BaseModel):
    username: str
    password: str
    email: str = None

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    token: str
    refresh_token: str
    user_id: str
    username: str
    role: str

class RefreshTokenRequest(BaseModel):
    refresh_token: str

class LogoutRequest(BaseModel):
    refresh_token: str

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


# ——— ฟังก์ชันช่วยสร้างและตรวจสอบ JWT ———

def create_token(data: dict, expires_delta: timedelta = None):
    """
    สร้าง JWT token จากข้อมูล data และกำหนดวันหมดอายุ
    """
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {**data, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str):
    """
    ตรวจสอบ JWT token และ decode คืน payload หรือโยน HTTPException
    """
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token หมดอายุ")
    except JWTError:
        raise HTTPException(status_code=401, detail="Token ไม่ถูกต้อง")

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    ดึงข้อมูลผู้ใช้จาก token ใน header Authorization
    """
    payload = verify_token(credentials.credentials)
    return {
        "user_id": payload.get("user_id"),
        "username": payload.get("username"),
        "role": payload.get("role", "member")
    }


# ——— เส้นทาง /auth ———

@auth_router.post("/signup", response_model=TokenResponse)
async def signup(payload: SignupRequest, request: Request):
    """
    สมัครสมาชิก → คืน token, refresh_token, user_id, username, role
    """
    # ตรวจว่ามี username ซ้ำหรือไม่
    existing = supabase_client.table("users") \
        .select("*").eq("username", payload.username).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="ชื่อผู้ใช้ซ้ำ")

    # เข้ารหัสรหัสผ่าน
    hashed_pw = bcrypt.hash(payload.password)
    resp = supabase_client.table("users").insert({
        "username": payload.username,
        "password": hashed_pw,
        "email": payload.email,
        "role": "member"
    }).execute()
    if resp.error:
        raise HTTPException(status_code=500, detail="สมัครสมาชิกไม่สำเร็จ")

    user = resp.data[0]
    # สร้าง token และ refresh token
    token = create_token({
        "user_id": user["id"],
        "username": user["username"],
        "role": user["role"]
    })
    refresh_token = create_token({
        "user_id": user["id"],
        "username": user["username"],
        "role": user["role"]
    }, expires_delta=timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS))

    # เก็บ refresh token ในตาราง user_sessions
    supabase_client.table("user_sessions").insert({
        "user_id": user["id"],
        "refresh_token": refresh_token,
        "ip_address": request.client.host,
        "user_agent": request.headers.get("user-agent"),
        "expires_at": (datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)).isoformat()
    }).execute()

    # บันทึก activity log
    await log_activity(
        user_id=user["id"],
        action="signup",
        description=f"สมัครสมาชิก: {user['username']}",
        ip=request.client.host,
        user_agent=request.headers.get("user-agent")
    )

    return {
        "token": token,
        "refresh_token": refresh_token,
        "user_id": user["id"],
        "username": user["username"],
        "role": user["role"]
    }


@auth_router.post("/login", response_model=TokenResponse)
@limiter.limit("15/minute")
async def login(payload: LoginRequest, request: Request):
    """
    เข้าสู่ระบบ → คืน token, refresh_token, user_id, username, role
    """
    user_res = supabase_client.table("users") \
        .select("*").eq("username", payload.username).single().execute()
    if not user_res.data or not bcrypt.verify(payload.password, user_res.data["password"]):
        raise HTTPException(status_code=401, detail="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")

    user = user_res.data
    role = user.get("role", "member")
    token = create_token({
        "user_id": user["id"],
        "username": user["username"],
        "role": role
    })
    refresh_token = create_token({
        "user_id": user["id"],
        "username": user["username"],
        "role": role
    }, expires_delta=timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS))

    supabase_client.table("user_sessions").insert({
        "user_id": user["id"],
        "refresh_token": refresh_token,
        "ip_address": request.client.host,
        "user_agent": request.headers.get("user-agent"),
        "expires_at": (datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)).isoformat()
    }).execute()

    await log_activity(
        user_id=user["id"],
        action="login",
        description=f"เข้าสู่ระบบ: {user['username']}",
        ip=request.client.host,
        user_agent=request.headers.get("user-agent")
    )

    return {
        "token": token,
        "refresh_token": refresh_token,
        "user_id": user["id"],
        "username": user["username"],
        "role": role
    }


@auth_router.post("/refresh_token")
async def refresh_token(payload: RefreshTokenRequest, request: Request):
    """
    ต่ออายุ refresh token (ยังไม่ implement)
    """
    raise HTTPException(status_code=404, detail="ยังไม่พร้อมใช้งาน")


@auth_router.post("/logout")
async def logout(payload: LogoutRequest, request: Request):
    """
    ออกจากระบบ (ยังไม่ implement)
    """
    raise HTTPException(status_code=404, detail="ยังไม่พร้อมใช้งาน")


@auth_router.get("/users/me")
async def get_me(current_user=Depends(get_current_user)):
    """
    ดึงข้อมูลผู้ใช้ปัจจุบันจาก token
    """
    return {
        "user_id": current_user["user_id"],
        "username": current_user["username"],
        "role": current_user["role"]
    }
