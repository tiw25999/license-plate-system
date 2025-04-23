from fastapi import APIRouter, Query, HTTPException, Path, Depends, Request
from app.schemas import PlateModel, PlateResponse, SearchParams
from app.database import add_plate, get_plate, get_plates, search_plates
from app.middleware import verify_token, require_auth, require_admin
from app.config import supabase_client
from datetime import datetime
import pytz
from typing import Optional, List
import logging
import re

# ตั้งค่า logging
logger = logging.getLogger(__name__)

plates_router = APIRouter()

@plates_router.post("/add_plate", response_model=PlateResponse)
async def add_plate_route(
    plate_number: str,
    province: Optional[str] = None,
    id_camera: Optional[str] = None,
    camera_name: Optional[str] = None,
    request: Request = None,
    user = Depends(require_auth)
):
    """เพิ่มทะเบียนใหม่ (ต้อง login ก่อน)"""
    try:
        # ดึง user_id จาก request state
        user_id = request.state.user.id if hasattr(request.state, "user") else None
        
        # เพิ่มทะเบียน
        await add_plate(plate_number, province, id_camera, camera_name, user_id)
        
        # ดึงข้อมูลที่เพิ่งเพิ่มเพื่อรับ timestamp ที่ถูกต้อง
        result = await get_plate(plate_number)
        
        if result:
            return {
                "status": "success",
                "plate_number": plate_number,
                "timestamp": result["timestamp"],
                "province": result.get("province"),
                "id_camera": result.get("id_camera"),
                "camera_name": result.get("camera_name")
            }
        else:
            return {
                "status": "success",
                "plate_number": plate_number,
                "timestamp": "N/A",
                "province": province,
                "id_camera": id_camera,
                "camera_name": camera_name
            }
    except Exception as e:
        logger.error(f"Error adding plate: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@plates_router.get("/get_plates", response_model=List[PlateModel])
async def fetch_plates(plate_number: Optional[str] = Query(None)):
    """ดึงข้อมูลทะเบียนตามเลขทะเบียน หรือดึงทั้งหมด 1000 รายการล่าสุดถ้าไม่ระบุ"""
    try:
        if plate_number:
            result = await get_plate(plate_number)
            if result:
                return [PlateModel(
                    plate=result["plate"],
                    timestamp=result["timestamp"],
                    province=result.get("province"),
                    id_camera=result.get("id_camera"),
                    camera_name=result.get("camera_name")
                )]
            raise HTTPException(status_code=404, detail="Plate not found")
        else:
            plates = await get_plates()
            # Filter out the id field from each plate record
            filtered_plates = []
            for plate in plates:
                filtered_plates.append(PlateModel(
                    plate=plate["plate"],
                    timestamp=plate["timestamp"],
                    province=plate.get("province"),
                    id_camera=plate.get("id_camera"),
                    camera_name=plate.get("camera_name")
                ))
            return filtered_plates
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching plates: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@plates_router.post("/search", response_model=List[PlateModel])
async def search_plates_route(search_params: SearchParams):
    """
    ค้นหาทะเบียนตามเงื่อนไขต่างๆ:
    - ค้นหาทะเบียนที่มีตัวอักษรหรือตัวเลขที่ต้องการปรากฏอยู่ (ไม่จำเป็นต้องขึ้นต้น)
    - ค้นหาตามช่วงวันที่ เช่น วันที่ 01/01/1990 ถึง 31/12/2023
    - ค้นหาตามช่วงเดือน เช่น เดือน 1 ปี 1990 ถึง เดือน 12 ปี 2023
    - ค้นหาตามช่วงปี เช่น ปี 1990 ถึง 2023
    - ค้นหาตามช่วงเวลา เช่น 8:00-17:00
    - ค้นหาตามจังหวัด
    - ค้นหาตามรหัสกล้อง
    - ค้นหาตามชื่อกล้อง
    """
    try:
        # ตรวจสอบความถูกต้องของรูปแบบวันที่
        if search_params.start_date or search_params.end_date:
            date_pattern = r"^\d{2}/\d{2}/\d{4}$"
            
            if (search_params.start_date and not re.match(date_pattern, search_params.start_date)) or \
               (search_params.end_date and not re.match(date_pattern, search_params.end_date)):
                raise HTTPException(status_code=400, detail="รูปแบบวันที่ไม่ถูกต้อง ต้องเป็น DD/MM/YYYY")
                
            # ถ้ามีเพียงค่าใดค่าหนึ่ง ให้แจ้งเตือน
            if bool(search_params.start_date) != bool(search_params.end_date):
                raise HTTPException(status_code=400, detail="ต้องระบุทั้งวันที่เริ่มต้นและวันที่สิ้นสุด")
        
        # ตรวจสอบความถูกต้องของเดือนและปี
        if search_params.start_month or search_params.end_month or search_params.start_year or search_params.end_year:
            # ตรวจสอบว่ามีข้อมูลครบถ้วนหรือไม่
            has_start_month = bool(search_params.start_month)
            has_end_month = bool(search_params.end_month)
            has_start_year = bool(search_params.start_year)
            has_end_year = bool(search_params.end_year)
            
            # กรณีค้นหาตามช่วงเดือน
            if has_start_month or has_end_month:
                if not (has_start_month and has_end_month and has_start_year and has_end_year):
                    raise HTTPException(status_code=400, detail="ต้องระบุทั้งเดือนและปีเริ่มต้น รวมถึงเดือนและปีสิ้นสุด")
                
                # ตรวจสอบความถูกต้องของค่าเดือน
                try:
                    start_month = int(search_params.start_month)
                    end_month = int(search_params.end_month)
                    
                    if start_month < 1 or start_month > 12 or end_month < 1 or end_month > 12:
                        raise HTTPException(status_code=400, detail="เดือนต้องเป็นตัวเลข 1-12")
                except ValueError:
                    raise HTTPException(status_code=400, detail="เดือนต้องเป็นตัวเลข 1-12")
            
            # กรณีค้นหาตามช่วงปี
            elif has_start_year or has_end_year:
                if not (has_start_year and has_end_year):
                    raise HTTPException(status_code=400, detail="ต้องระบุทั้งปีเริ่มต้นและปีสิ้นสุด")
                
                # ตรวจสอบความถูกต้องของค่าปี
                try:
                    int(search_params.start_year)
                    int(search_params.end_year)
                except ValueError:
                    raise HTTPException(status_code=400, detail="ปีต้องเป็นตัวเลข")
        
        # ตรวจสอบความถูกต้องของช่วงเวลา
        if search_params.start_hour or search_params.end_hour:
            if bool(search_params.start_hour) != bool(search_params.end_hour):
                raise HTTPException(status_code=400, detail="ต้องระบุทั้งเวลาเริ่มต้นและเวลาสิ้นสุด")
            
            try:
                start_hour = int(search_params.start_hour)
                end_hour = int(search_params.end_hour)
                
                if start_hour < 0 or start_hour > 23 or end_hour < 0 or end_hour > 23:
                    raise HTTPException(status_code=400, detail="ช่วงเวลาต้องเป็นตัวเลข 0-23")
                
                if start_hour > end_hour:
                    raise HTTPException(status_code=400, detail="เวลาเริ่มต้นต้องน้อยกว่าหรือเท่ากับเวลาสิ้นสุด")
            except ValueError:
                raise HTTPException(status_code=400, detail="ช่วงเวลาต้องเป็นตัวเลข")
        
        # เรียกใช้ฟังก์ชันค้นหา
        results = await search_plates(
            search_term=search_params.search_term,
            start_date=search_params.start_date,
            end_date=search_params.end_date,
            start_month=search_params.start_month,
            end_month=search_params.end_month,
            start_year=search_params.start_year,
            end_year=search_params.end_year,
            start_hour=search_params.start_hour,
            end_hour=search_params.end_hour,
            province=search_params.province,
            id_camera=search_params.id_camera,
            camera_name=search_params.camera_name,
            limit=search_params.limit
        )
        
        # แปลงผลลัพธ์เป็น PlateModel
        filtered_plates = []
        for plate in results:
            filtered_plates.append(PlateModel(
                plate=plate["plate"],
                timestamp=plate["timestamp"],
                province=plate.get("province"),
                id_camera=plate.get("id_camera"),
                camera_name=plate.get("camera_name")
            ))
        
        return filtered_plates
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error searching plates: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error searching plates: {str(e)}")

@plates_router.get("/search", response_model=List[PlateModel])
async def search_plates_get(
    search_term: Optional[str] = Query(None, description="คำค้นหาสำหรับทะเบียนรถ เช่น 'A', '123'"),
    start_date: Optional[str] = Query(None, description="วันที่เริ่มต้นในรูปแบบ DD/MM/YYYY"),
    end_date: Optional[str] = Query(None, description="วันที่สิ้นสุดในรูปแบบ DD/MM/YYYY"),
    start_month: Optional[str] = Query(None, description="เดือนเริ่มต้น (1-12)"),
    end_month: Optional[str] = Query(None, description="เดือนสิ้นสุด (1-12)"),
    start_year: Optional[str] = Query(None, description="ปีเริ่มต้น (เช่น 1990)"),
    end_year: Optional[str] = Query(None, description="ปีสิ้นสุด (เช่น 2023)"),
    start_hour: Optional[str] = Query(None, description="ชั่วโมงเริ่มต้น (0-23)"),
    end_hour: Optional[str] = Query(None, description="ชั่วโมงสิ้นสุด (0-23)"),
    province: Optional[str] = Query(None, description="จังหวัดของทะเบียนรถ"),
    id_camera: Optional[str] = Query(None, description="รหัสกล้อง"),
    camera_name: Optional[str] = Query(None, description="ชื่อกล้อง"),
    limit: int = Query(1000, ge=1, le=1000, description="จำนวนผลลัพธ์สูงสุด (1-1000)")
):
    """
    ค้นหาทะเบียนตามเงื่อนไขต่างๆด้วย GET method:
    - ค้นหาทะเบียนที่มีตัวอักษรหรือตัวเลขที่ต้องการปรากฏอยู่ (ไม่จำเป็นต้องขึ้นต้น)
    - ค้นหาตามช่วงวันที่ เดือน ปี
    - ค้นหาตามช่วงเวลาของวัน
    - ค้นหาตามจังหวัด
    - ค้นหาตามรหัสกล้อง
    - ค้นหาตามชื่อกล้อง
    """
    # สร้าง SearchParams จาก query parameters
    search_params = SearchParams(
        search_term=search_term,
        start_date=start_date,
        end_date=end_date,
        start_month=start_month,
        end_month=end_month,
        start_year=start_year,
        end_year=end_year,
        start_hour=start_hour,
        end_hour=end_hour,
        province=province,
        id_camera=id_camera,
        camera_name=camera_name,
        limit=limit
    )
    
    # เรียกใช้ฟังก์ชันค้นหาที่มีอยู่แล้ว
    return await search_plates_route(search_params)

@plates_router.delete("/delete_plate/{plate_id}")
async def delete_plate(plate_id: str, user = Depends(require_admin)):
    """ลบทะเบียนตาม ID (เฉพาะ admin เท่านั้น)"""
    try:
        # ลบข้อมูลจาก Supabase
        response = supabase_client.table("plates").delete().eq("id", plate_id).execute()
        
        if hasattr(response, 'error') and response.error:
            raise HTTPException(status_code=500, detail=f"Error deleting plate: {response.error}")
        
        # ล้าง cache
        from app.database import clear_caches
        await clear_caches()
        
        return {"message": "ลบข้อมูลทะเบียนเรียบร้อยแล้ว"}
    except Exception as e:
        logger.error(f"Error deleting plate: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@plates_router.get("/get_provinces", response_model=List[str])
async def get_provinces():
    """ดึงรายชื่อจังหวัดทั้งหมดที่มีในระบบ"""
    try:
        # ดึงข้อมูลจังหวัดที่ไม่ซ้ำกันจาก Supabase
        response = supabase_client.table("plates").select("province").execute()
        
        if hasattr(response, 'error') and response.error:
            raise HTTPException(status_code=500, detail=f"Error fetching provinces: {response.error}")
        
        # กรองเฉพาะค่าที่ไม่ซ้ำและไม่เป็น null
        provinces = set()
        for item in response.data:
            if item.get("province"):
                provinces.add(item["province"])
        
        return sorted(list(provinces))
    except Exception as e:
        logger.error(f"Error fetching provinces: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@plates_router.get("/get_cameras", response_model=List[dict])
async def get_cameras():
    """ดึงรายการกล้องทั้งหมดที่มีในระบบ"""
    try:
        # ดึงข้อมูลกล้องที่ไม่ซ้ำกันจาก Supabase
        response = supabase_client.table("plates").select("id_camera, camera_name").execute()
        
        if hasattr(response, 'error') and response.error:
            raise HTTPException(status_code=500, detail=f"Error fetching cameras: {response.error}")
        
        # กรองเฉพาะค่าที่ไม่ซ้ำและไม่เป็น null
        cameras = {}
        for item in response.data:
            if item.get("id_camera") and item.get("camera_name"):
                cameras[item["id_camera"]] = item["camera_name"]
        
        result = [{"id_camera": k, "camera_name": v} for k, v in cameras.items()]
        return sorted(result, key=lambda x: x["id_camera"])
    except Exception as e:
        logger.error(f"Error fetching cameras: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))