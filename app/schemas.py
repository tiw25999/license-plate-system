from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

# Models สำหรับข้อมูลทะเบียน
class PlateBase(BaseModel):
    plate: str
    province: Optional[str] = None
    id_camera: Optional[str] = None
    camera_name: Optional[str] = None

class PlateCreate(PlateBase):
    pass

class PlateModel(PlateBase):
    timestamp: str

class CharacterConfidenceItem(BaseModel):
    char: str = Field(..., description="ตัวอักษรในป้ายทะเบียน")
    confidence: float = Field(..., ge=0, le=100, description="ค่าความแม่นยำ (0-100)")

class PlateAddDetailedRequest(BaseModel):
    plate_number: str
    province: Optional[str] = Field(default=None)
    province_confidence: Optional[float] = Field(default=None)
    character_confidences: Optional[List[CharacterConfidenceItem]] = Field(default=None)
    id_camera: Optional[str] = Field(default=None)
    camera_name: Optional[str] = Field(default=None)

class PlateResponse(BaseModel):
    status: Optional[str] = None
    plate_number: str
    timestamp: str
    province: Optional[str] = None
    id_camera: Optional[str] = None
    camera_name: Optional[str] = None
    character_confidences: Optional[List[CharacterConfidenceItem]] = None
    province_confidence: Optional[float] = None

# Models สำหรับการค้นหา
class SearchParams(BaseModel):
    search_term: Optional[str] = Field(None, description="คำค้นหาสำหรับทะเบียนรถ เช่น 'ABC'")
    start_date: Optional[str] = Field(None, description="วันที่เริ่มต้นในรูปแบบ DD/MM/YYYY")
    end_date: Optional[str] = Field(None, description="วันที่สิ้นสุดในรูปแบบ DD/MM/YYYY")
    start_month: Optional[str] = Field(None, description="เดือนเริ่มต้น (1-12)")
    end_month: Optional[str] = Field(None, description="เดือนสิ้นสุด (1-12)")
    start_year: Optional[str] = Field(None, description="ปีเริ่มต้น (เช่น 2023)")
    end_year: Optional[str] = Field(None, description="ปีสิ้นสุด (เช่น 2023)")
    start_hour: Optional[str] = Field(None, description="ชั่วโมงเริ่มต้น (0-23)")
    end_hour: Optional[str] = Field(None, description="ชั่วโมงสิ้นสุด (0-23)")
    province: Optional[str] = Field(None, description="จังหวัดของทะเบียนรถ")
    id_camera: Optional[str] = Field(None, description="รหัสกล้อง")
    camera_name: Optional[str] = Field(None, description="ชื่อกล้อง")
    limit: int = Field(5000, ge=1, le=5000, description="จำนวนผลลัพธ์สูงสุด (1-5000)")

# Models สำหรับ Authentication
class UserBase(BaseModel):
    username: str
    email: Optional[str] = None

class UserLogin(UserBase):
    password: str

class UserSignUp(UserBase):
    password: str
    confirm_password: str

class UserResponse(UserBase):
    id: str
    role: Optional[str] = None
    token: str

class UserRoleUpdate(BaseModel):
    user_id: str
    role: str

class UserInfo(UserBase):
    id: str
    role: Optional[str] = None

class ChangePassword(BaseModel):
    current_password: str
    new_password: str

# Models สำหรับ Session และ Activity Log
class SessionInfo(BaseModel):
    id: str
    user_id: str
    session_token: str
    expires_at: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    last_active_at: Optional[str] = None
    created_at: Optional[str] = None

class ActivityLog(BaseModel):
    id: str
    user_id: str
    action: str
    table_name: Optional[str] = None
    record_id: Optional[str] = None
    description: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: str

# Models สำหรับกล้องและกลุ่มกล้อง
class CameraGroupBase(BaseModel):
    name: str
    description: Optional[str] = None

class CameraGroupCreate(CameraGroupBase):
    pass

class CameraGroupResponse(CameraGroupBase):
    id: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

class CameraBase(BaseModel):
    camera_id: str
    name: str
    location: Optional[str] = None
    ip_address: Optional[str] = None
    status: str = "active"
    group_id: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None

class CameraCreate(CameraBase):
    pass

class CameraResponse(CameraBase):
    id: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

# Models สำหรับการติดตามและแจ้งเตือน
class WatchlistBase(BaseModel):
    plate: str
    province: Optional[str] = None
    reason: Optional[str] = None
    status: str = "active"
    priority: int = 0

class WatchlistCreate(WatchlistBase):
    pass

class WatchlistResponse(WatchlistBase):
    id: str
    user_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

class AlertBase(BaseModel):
    plate_id: str
    watchlist_id: str
    status: str = "new"
    notes: Optional[str] = None

class AlertCreate(AlertBase):
    pass

class AlertResponse(AlertBase):
    id: str
    handled_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    plate: Optional[Dict[str, Any]] = None
    watchlist: Optional[Dict[str, Any]] = None

# Models สำหรับการตั้งค่าระบบ
class SystemSettingBase(BaseModel):
    setting_key: str
    setting_value: str
    description: Optional[str] = None

class SystemSettingCreate(SystemSettingBase):
    pass

class SystemSettingResponse(SystemSettingBase):
    id: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
