from pydantic import BaseModel, Field
from typing import Optional, List
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

class PlateResponse(BaseModel):
    status: str
    plate_number: str
    timestamp: str
    province: Optional[str] = None
    id_camera: Optional[str] = None
    camera_name: Optional[str] = None

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
    email: str

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