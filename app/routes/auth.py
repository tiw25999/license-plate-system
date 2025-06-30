from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
from app.utils.log_utils import log_activity
from slowapi.extension import Limiter
from slowapi.util import get_remote_address
from jose import jwt, JWTError
import os
from passlib.hash import bcrypt
from dotenv import load_dotenv
from app.config import supabase_client
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# --- Init ---
limiter = Limiter(key_func=get_remote_address)
security = HTTPBearer()
load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 7

auth_router = APIRouter()

# --- Schemas ---
class LoginRequest(BaseModel):
    username: str
    password: str

class SignupRequest(BaseModel):
    username: str
    password: str
    email: str = None

class TokenResponse(BaseModel):
    token: str
    refresh_token: str
    user_id: str
    username: str
    role: str

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

class RefreshTokenRequest(BaseModel):
    refresh_token: str

class LogoutRequest(BaseModel):
    refresh_token: str

# --- JWT utils ---
def create_token(data: dict, expires_delta: timedelta = None):
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode = {
        "sub": data["user_id"],
        "username": data["username"],
        "role": data["role"],
        "exp": expire
    }
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception:
        raise HTTPException(status_code=401, detail="Token decode error")

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    data = verify_token(token)
    return {
        "user_id": data.get("user_id") or data.get("sub"),
        "username": data.get("username"),
        "role": data.get("role", "member")
    }

# --- Routes ---
@auth_router.post("/auth/signup", response_model=TokenResponse)
async def signup(payload: SignupRequest, request: Request):
    existing = supabase_client.table("users").select("*").eq("username", payload.username).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Username already exists")

    hashed = bcrypt.hash(payload.password)
    response = supabase_client.table("users").insert({
        "username": payload.username,
        "password": hashed,
        "email": payload.email,
        "role": "member"
    }).execute()

    if hasattr(response, "error") and response.error:
        raise HTTPException(status_code=500, detail="Signup failed")

    user = response.data[0]
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

    supabase_client.table("user_sessions").insert({
        "user_id": user["id"],
        "refresh_token": refresh_token,
        "ip_address": request.client.host,
        "user_agent": request.headers.get("user-agent"),
        "expires_at": (datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)).isoformat()
    }).execute()

    await log_activity(
        user_id=user["id"],
        action="signup",
        description=f"User signed up: {user['username']}",
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

@auth_router.post("/auth/login", response_model=TokenResponse)
@limiter.limit("15/minute")
async def login(payload: LoginRequest, request: Request):
    user = supabase_client.table("users").select("*").eq("username", payload.username).single().execute()

    if not user.data or not bcrypt.verify(payload.password, user.data["password"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    role = user.data.get("role", "member")

    token = create_token({
        "user_id": user.data["id"],
        "username": user.data["username"],
        "role": role
    })

    refresh_token = create_token({
        "user_id": user.data["id"],
        "username": user.data["username"],
        "role": role
    }, expires_delta=timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS))

    supabase_client.table("user_sessions").insert({
        "user_id": user.data["id"],
        "refresh_token": refresh_token,
        "ip_address": request.client.host,
        "user_agent": request.headers.get("user-agent"),
        "expires_at": (datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)).isoformat()
    }).execute()

    await log_activity(
        user_id=user.data["id"],
        action="login",
        description=f"User logged in: {user.data['username']}",
        ip=request.client.host,
        user_agent=request.headers.get("user-agent")
    )

    return {
        "token": token,
        "refresh_token": refresh_token,
        "user_id": user.data["id"],
        "username": user.data["username"],
        "role": role
    }

@auth_router.get("/auth/verify")
async def verify(token: str):
    data = verify_token(token)
    return {"valid": True, "user": data}

@auth_router.post("/auth/logout")
async def logout(payload: LogoutRequest, request: Request):
    token = payload.refresh_token
    session_res = supabase_client.table("user_sessions").select("*").eq("refresh_token", token).single().execute()

    if not session_res.data:
        raise HTTPException(status_code=404, detail="Session not found")

    supabase_client.table("user_sessions").delete().eq("id", session_res.data["id"]).execute()

    await log_activity(
        user_id=session_res.data["user_id"],
        action="logout",
        description="User logged out from session",
        ip=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    return {"message": "Logout successful"}

@auth_router.post("/auth/logout_all")
async def logout_all(request: Request, current_user=Depends(get_current_user)):
    user_id = current_user["user_id"]
    supabase_client.table("user_sessions").delete().eq("user_id", user_id).execute()

    await log_activity(
        user_id=user_id,
        action="logout_all",
        description="User logged out from all devices",
        ip=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    return {"message": "All sessions cleared"}

@auth_router.post("/auth/change_password")
async def change_password(payload: ChangePasswordRequest, request: Request, current_user=Depends(get_current_user)):
    user_id = current_user["user_id"]
    user_res = supabase_client.table("users").select("*").eq("id", user_id).single().execute()
    if not user_res.data or not bcrypt.verify(payload.old_password, user_res.data["password"]):
        raise HTTPException(status_code=403, detail="Old password incorrect")

    new_hash = bcrypt.hash(payload.new_password)
    supabase_client.table("users").update({"password": new_hash}).eq("id", user_id).execute()

    await log_activity(
        user_id=user_id,
        action="change_password",
        description="User changed password",
        ip=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    return {"message": "Password changed successfully"}

@auth_router.post("/auth/refresh_token")
async def refresh_token(payload: RefreshTokenRequest, request: Request):
    try:
        token_data = verify_token(payload.refresh_token)
        user_id = token_data.get("user_id") or token_data.get("sub")

        session_res = supabase_client.table("user_sessions")\
            .select("*")\
            .eq("refresh_token", payload.refresh_token)\
            .eq("user_id", user_id)\
            .single()\
            .execute()

        if not session_res.data:
            raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

        expires_at = datetime.fromisoformat(session_res.data["expires_at"].replace("Z", "+00:00"))
        if expires_at < datetime.now(timezone.utc):
            supabase_client.table("user_sessions").delete().eq("id", session_res.data["id"]).execute()
            raise HTTPException(status_code=401, detail="Refresh token expired")

        new_access_token = create_token({
            "user_id": user_id,
            "username": token_data.get("username", ""),
            "role": token_data.get("role", "member")
        })

        await log_activity(
            user_id=user_id,
            action="refresh_token",
            description="User refreshed access token",
            ip=request.client.host,
            user_agent=request.headers.get("user-agent")
        )

        return {"access_token": new_access_token}
    except JWTError:
        raise HTTPException(status_code=401, detail="Token decode failed")

@auth_router.post("/auth/introspect")
async def introspect_token(request: Request):
    token = request.headers.get("authorization")
    if not token or not token.startswith("Bearer "):
        raise HTTPException(status_code=400, detail="Missing or invalid authorization header")

    token = token.split(" ")[1]
    try:
        payload = verify_token(token)
        return {"active": True, "claims": payload}
    except JWTError:
        return {"active": False}

@auth_router.get("/users/me")
async def get_me(current_user=Depends(get_current_user)):
    return {
        "user_id": current_user["user_id"],
        "username": current_user["username"],
        "role": current_user.get("role", "member")
    }
