from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
from uuid import UUID

# ——————————————————————————————————————————
# Model สำหรับรายการความแม่นยำแต่ละตัวอักษร
class CharacterConfidenceItem(BaseModel):
    char: str = Field(..., description="ตัวอักษรในป้ายทะเบียน")
    confidence: float = Field(
        ..., ge=0, le=100,
        description="ค่าความแม่นยำของตัวอักษร (0-100)"
    )

# Request model สำหรับส่งเพิ่ม plate candidate
class PlateAddDetailedRequest(BaseModel):
    plate_number: str = Field(..., description="เลขทะเบียนที่จะเพิ่ม")
    province: Optional[str] = Field(
        None, description="ชื่อจังหวัด (ถ้ามี)"
    )
    province_confidence: Optional[float] = Field(
        None, ge=0, le=100,
        description="ค่าความแม่นยำของจังหวัด (0-100)"
    )
    character_confidences: List[CharacterConfidenceItem] = Field(
        ..., description="รายการความแม่นยำแต่ละตัวอักษร"
    )
    id_camera: Optional[str] = Field(
        None, description="รหัสกล้อง (ถ้ามี)"
    )
    camera_name: Optional[str] = Field(
        None, description="ชื่อกล้อง (ถ้ามี)"
    )
    

# Response model สำหรับ add_plate
class PlateResponse(BaseModel):
    id: str = Field(..., description="UUID ของ candidate")
    correlation_id: UUID = Field(..., description="รหัสเชื่อมข้อมูลระหว่าง candidate ↔ image")
    status: str = Field(..., description="สถานะการดำเนินการ")
    plate_number: str = Field(..., description="เลขทะเบียน")
    timestamp: Union[datetime, str] = Field(..., description="เวลาที่ดำเนินการ (ISO UTC หรือ สตริง)")
    province: Optional[str] = Field(None, description="ชื่อจังหวัด")
    id_camera: Optional[str] = Field(None, description="รหัสกล้อง")
    camera_name: Optional[str] = Field(None, description="ชื่อกล้อง")
    character_confidences: List[CharacterConfidenceItem] = Field(
        ..., description="รายการความแม่นยำแต่ละตัวอักษร"
    )
    province_confidence: Optional[float] = Field(
        None, ge=0, le=100,
        description="ค่าความแม่นยำของจังหวัด (0-100)"
    )
    




# ——————————————————————————————————————————
# Base model สำหรับ Plate ทั่วไป
class PlateBase(BaseModel):
    plate: str = Field(..., description="เลขทะเบียน")
    province: Optional[str] = Field(None, description="ชื่อจังหวัด")
    id_camera: Optional[str] = Field(None, description="รหัสกล้อง")
    camera_name: Optional[str] = Field(None, description="ชื่อกล้อง")

class PlateModel(PlateBase):
    timestamp: str = Field(..., description="เวลาที่สร้าง (แสดงผลไทย)")

# ——————————————————————————————————————————
# Model สำหรับการค้นหา
class SearchParams(BaseModel):
    search_term: Optional[str] = Field(
        None, description="คำค้นหาสำหรับทะเบียน เช่น 'ABC'"
    )
    start_date: Optional[str] = Field(
        None, description="วันที่เริ่มต้น DD/MM/YYYY"
    )
    end_date: Optional[str] = Field(
        None, description="วันที่สิ้นสุด DD/MM/YYYY"
    )
    start_month: Optional[int] = Field(
        None, ge=1, le=12, description="เดือนเริ่มต้น (1-12)"
    )
    end_month: Optional[int] = Field(
        None, ge=1, le=12, description="เดือนสิ้นสุด (1-12)"
    )
    start_year: Optional[int] = Field(
        None, description="ปีเริ่มต้น เช่น 2023"
    )
    end_year: Optional[int] = Field(
        None, description="ปีสิ้นสุด เช่น 2023"
    )
    start_hour: Optional[int] = Field(
        None, ge=0, le=23, description="ชั่วโมงเริ่มต้น (0-23)"
    )
    end_hour: Optional[int] = Field(
        None, ge=0, le=23, description="ชั่วโมงสิ้นสุด (0-23)"
    )
    province: Optional[str] = Field(None, description="กรองตามจังหวัด")
    id_camera: Optional[str] = Field(None, description="กรองตามรหัสกล้อง")
    camera_name: Optional[str] = Field(None, description="กรองตามชื่อกล้อง")
    limit: int = Field(
        5000, ge=1, le=5000,
        description="จำนวนผลลัพธ์สูงสุด (1-5000)"
    )

# ——————————————————————————————————————————
# Models สำหรับ Authentication และผู้ใช้
class UserBase(BaseModel):
    username: str = Field(..., description="ชื่อผู้ใช้")
    email: Optional[str] = Field(None, description="อีเมล")

class UserLogin(UserBase):
    password: str = Field(..., description="รหัสผ่าน")

class UserSignUp(UserBase):
    password: str = Field(..., description="รหัสผ่าน")
    confirm_password: str = Field(..., description="ยืนยันรหัสผ่าน")

class UserResponse(UserBase):
    id: str = Field(..., description="รหัสผู้ใช้")
    role: Optional[str] = Field(None, description="สิทธิ์ผู้ใช้")
    token: str = Field(..., description="JWT token")

class UserRoleUpdate(BaseModel):
    user_id: str = Field(..., description="รหัสผู้ใช้ที่จะปรับสิทธิ์")
    role: str = Field(..., description="สิทธิ์ใหม่ (admin/member)")

class ChangePassword(BaseModel):
    current_password: str = Field(..., description="รหัสผ่านปัจจุบัน")
    new_password: str = Field(..., description="รหัสผ่านใหม่")

# ——————————————————————————————————————————
# Models สำหรับ Session และ Activity Log
class SessionInfo(BaseModel):
    id: str
    user_id: str
    session_token: str
    expires_at: Optional[datetime]
    ip_address: Optional[str]
    user_agent: Optional[str]
    last_active_at: Optional[datetime]
    created_at: Optional[datetime]

class ActivityLog(BaseModel):
    id: str
    user_id: str
    action: str
    table_name: Optional[str]
    record_id: Optional[str]
    description: Optional[str]
    ip_address: Optional[str]
    user_agent: Optional[str]
    created_at: datetime

# ——————————————————————————————————————————
# Models สำหรับกล้อง และกลุ่มกล้อง
class CameraGroupBase(BaseModel):
    name: str
    description: Optional[str] = None

class CameraGroupResponse(CameraGroupBase):
    id: str
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

class CameraBase(BaseModel):
    camera_id: str
    name: str
    location: Optional[str] = None
    ip_address: Optional[str] = None
    status: str = Field("active", description="สถานะกล้อง")
    group_id: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None

class CameraResponse(CameraBase):
    id: str
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

# ——————————————————————————————————————————
# Models สำหรับ Watchlist และ Alert
class WatchlistBase(BaseModel):
    plate: str
    province: Optional[str] = None
    reason: Optional[str] = None
    status: str = Field("active", description="สถานะรายการ")
    priority: int = Field(0, description="ลำดับความสำคัญ")

class WatchlistResponse(WatchlistBase):
    id: str
    user_id: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

class AlertBase(BaseModel):
    plate_id: str
    watchlist_id: str
    status: str = Field("new", description="สถานะการแจ้งเตือน")
    notes: Optional[str] = None

class AlertResponse(AlertBase):
    id: str
    handled_by: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    plate: Optional[Dict[str, Any]]
    watchlist: Optional[Dict[str, Any]]

# ——————————————————————————————————————————
# Models สำหรับตั้งค่าระบบ
class SystemSettingBase(BaseModel):
    setting_key: str
    setting_value: str
    description: Optional[str] = None

class SystemSettingResponse(SystemSettingBase):
    id: str
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


