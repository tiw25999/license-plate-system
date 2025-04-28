from fastapi import APIRouter, Query, HTTPException, Path, Depends, Request
from app.schemas import PlateModel, PlateResponse, SearchParams
from app.database import add_plate, get_plate, get_plates, search_plates, get_cameras, get_watchlists, get_alerts, clear_caches
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

@plates_router.get("/get_plates")
async def get_plates_route(request: Request = None):
    """ดึงทะเบียนทั้งหมด"""
    try:
        # ใช้ฟังก์ชัน get_plates จาก database.py
        plates = await get_plates()
        
        return plates
    except Exception as e:
        logger.error(f"Error fetching plates: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@plates_router.get("/search")
async def search_plates_route(
    request: Request,
    search_term: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    start_month: Optional[str] = None,
    end_month: Optional[str] = None,
    start_year: Optional[str] = None,
    end_year: Optional[str] = None,
    start_hour: Optional[str] = None,
    end_hour: Optional[str] = None,
    province: Optional[str] = None,
    id_camera: Optional[str] = None,
    camera_name: Optional[str] = None,
    limit: int = 5000
):
    """ค้นหาทะเบียนรถตามเงื่อนไข"""
    try:
        # ใช้ฟังก์ชัน search_plates จาก database.py
        results = await search_plates(
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
        
        return results
    except Exception as e:
        logger.error(f"Error searching plates: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@plates_router.get("/get_cameras")
async def get_cameras_route(request: Request = None):
    """ดึงรายการกล้องทั้งหมด"""
    try:
        # ใช้ฟังก์ชัน get_cameras จาก database.py
        cameras = await get_cameras()
        
        return cameras
    except Exception as e:
        logger.error(f"Error fetching cameras: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@plates_router.get("/get_watchlists")
async def get_watchlists_route(request: Request = None, user = Depends(require_auth)):
    """ดึงรายการทะเบียนที่ต้องการติดตาม"""
    try:
        # ดึง user_id และตรวจสอบว่าเป็น admin หรือไม่
        user_id = user.get('id') if isinstance(user, dict) else user.id
        is_admin = request.state.role == "admin" if hasattr(request.state, "role") else False
        
        # ใช้ฟังก์ชัน get_watchlists จาก database.py
        watchlists = await get_watchlists(user_id=user_id, is_admin=is_admin)
        
        return watchlists
    except Exception as e:
        logger.error(f"Error fetching watchlists: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

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
        user_id = user.get('id') if isinstance(user, dict) else user.id
        
        # เพิ่มทะเบียน
        await add_plate(plate_number, province, id_camera, camera_name, user_id)
        
        # ดึงข้อมูลที่เพิ่งเพิ่มเพื่อรับ timestamp ที่ถูกต้อง
        result = await get_plate(plate_number)
        
        # ลบการบันทึกกิจกรรม
        
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
                "timestamp": datetime.now(pytz.timezone('Asia/Bangkok')).strftime("%d/%m/%Y %H:%M:%S"),
                "province": province,
                "id_camera": id_camera,
                "camera_name": camera_name
            }
    except Exception as e:
        logger.error(f"Error adding plate: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@plates_router.delete("/delete_watchlist/{watchlist_id}")
async def delete_watchlist(
    watchlist_id: str,
    request: Request,
    user = Depends(require_auth)
):
    """ลบรายการทะเบียนรถที่ต้องการติดตาม"""
    try:
        user_id = user.get('id') if isinstance(user, dict) else user.id
        is_admin = request.state.role == "admin" if hasattr(request.state, "role") else False
        
        # ดึงข้อมูลรายการติดตามก่อนลบเพื่อใช้ในการบันทึก log
        watchlist_data = supabase_client.table("watchlists").select("*").eq("id", watchlist_id).single().execute()
        
        if not watchlist_data.data:
            raise HTTPException(status_code=404, detail="ไม่พบรายการติดตามที่ระบุ")
        
        # ตรวจสอบสิทธิ์ในการลบ
        if not is_admin and watchlist_data.data.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="คุณไม่มีสิทธิ์ลบรายการนี้")
        
        # ลบการแจ้งเตือนที่เกี่ยวข้องกับรายการติดตามนี้
        supabase_client.table("alerts").delete().eq("watchlist_id", watchlist_id).execute()
        
        # ลบรายการติดตาม
        response = supabase_client.table("watchlists").delete().eq("id", watchlist_id).execute()
        
        if hasattr(response, 'error') and response.error:
            raise HTTPException(status_code=500, detail=f"Error deleting watchlist: {response.error}")
        
        # ลบการบันทึกกิจกรรม
        
        return {"message": "ลบรายการติดตามสำเร็จ"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting watchlist: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@plates_router.get("/get_alerts")
async def get_alerts_route(request: Request, status: Optional[str] = None, user = Depends(require_auth)):
    """ดึงรายการแจ้งเตือน"""
    try:
        # ใช้ฟังก์ชัน get_alerts จาก database.py
        alerts = await get_alerts(status)
        
        return alerts
    except Exception as e:
        logger.error(f"Error fetching alerts: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@plates_router.put("/update_alert/{alert_id}")
async def update_alert(
    alert_id: str,
    status: str,
    notes: Optional[str] = None,
    request: Request = None,
    user = Depends(require_auth)
):
    """อัปเดตสถานะการแจ้งเตือน"""
    try:
        user_id = user.get('id') if isinstance(user, dict) else user.id
        
        # ตรวจสอบสถานะ
        if status not in ["new", "viewed", "handled", "ignored"]:
            raise HTTPException(status_code=400, detail="สถานะไม่ถูกต้อง (ต้องเป็น 'new', 'viewed', 'handled' หรือ 'ignored')")
        
        # ดึงข้อมูลการแจ้งเตือนเดิม
        alert_data = supabase_client.table("alerts").select("*").eq("id", alert_id).single().execute()
        
        if not alert_data.data:
            raise HTTPException(status_code=404, detail="ไม่พบการแจ้งเตือนที่ระบุ")
        
        # อัปเดตสถานะ
        data = {
            "status": status,
            "notes": notes,
            "updated_at": "now()"
        }
        
        if status in ["handled", "ignored"]:
            data["handled_by"] = user_id
        
        response = supabase_client.table("alerts").update(data).eq("id", alert_id).execute()
        
        if hasattr(response, 'error') and response.error:
            raise HTTPException(status_code=500, detail=f"Error updating alert: {response.error}")
        
        # ลบการบันทึกกิจกรรม
        
        return {"message": "อัปเดตสถานะการแจ้งเตือนสำเร็จ", "data": response.data[0] if response.data else None}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating alert: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))