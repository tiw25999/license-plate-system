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
        
        # บันทึกกิจกรรม
        if user_id:
            supabase_client.rpc(
                'log_activity',
                {
                    'p_user_id': user_id,
                    'p_action': 'add_plate',
                    'p_table_name': 'plates',
                    'p_record_id': result.get('id') if result else None,
                    'p_description': f'เพิ่มทะเบียน {plate_number} จังหวัด {province}',
                    'p_ip_address': request.client.host if request.client else None,
                    'p_user_agent': request.headers.get("user-agent")
                }
            ).execute()
        
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
        
        # บันทึกกิจกรรม
        if user_id:
            supabase_client.rpc(
                'log_activity',
                {
                    'p_user_id': user_id,
                    'p_action': 'delete_watchlist',
                    'p_table_name': 'watchlists',
                    'p_record_id': watchlist_id,
                    'p_description': f'ลบทะเบียน {watchlist_data.data.get("plate")} จังหวัด {watchlist_data.data.get("province")} จากรายการติดตาม',
                    'p_ip_address': request.client.host if request.client else None,
                    'p_user_agent': request.headers.get("user-agent")
                }
            ).execute()
        
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
        
        # บันทึกกิจกรรม
        if user_id:
            supabase_client.rpc(
                'log_activity',
                {
                    'p_user_id': user_id,
                    'p_action': 'update_alert',
                    'p_table_name': 'alerts',
                    'p_record_id': alert_id,
                    'p_description': f'อัปเดตสถานะการแจ้งเตือนเป็น {status}',
                    'p_ip_address': request.client.host if request.client else None,
                    'p_user_agent': request.headers.get("user-agent")
                }
            ).execute()
        
        return {"message": "อัปเดตสถานะการแจ้งเตือนสำเร็จ", "data": response.data[0] if response.data else None}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating alert: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))