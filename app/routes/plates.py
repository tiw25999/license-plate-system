from fastapi import APIRouter, Query, HTTPException, Path, Request, Depends
from app.schemas import PlateModel, PlateResponse, SearchParams
from app.database import (
    get_plate_candidates, edit_plate, add_plate_candidate, verify_plate_candidate,
    get_plate, get_plates, search_plates, get_cameras, get_watchlists, get_alerts, clear_caches
)
from app.routes.auth import get_current_user
from app.routes.auth_extra import is_admin
from app.utils.log_utils import log_activity
from app.config import supabase_client
from datetime import datetime
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)
plates_router = APIRouter()

@plates_router.post("/verify_plate/{candidate_id}")
async def verify_plate_candidate_route(candidate_id: str, user: dict = Depends(get_current_user)):
    try:
        plate_id = await verify_plate_candidate(candidate_id, verified_by_user_id=user["user_id"])
        await log_activity(user["user_id"], "verify_plate", f"Verified candidate {candidate_id} to plate {plate_id}")
        return {"message": "Verified successfully", "plate_id": plate_id}
    except Exception as e:
        logger.error(f"Error verifying plate candidate: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@plates_router.delete("/candidates/{candidate_id}")
async def reject_plate_candidate_route(candidate_id: str, user: dict = Depends(get_current_user)):
    try:
        response = supabase_client.table("plate_candidates").delete().eq("id", candidate_id).execute()
        if hasattr(response, "error") and response.error:
            raise HTTPException(status_code=500, detail=f"Delete failed: {response.error}")
        await log_activity(user["user_id"], "reject_plate", f"Rejected plate candidate {candidate_id}")
        return {"message": "Rejected successfully"}
    except Exception as e:
        logger.error(f"Reject candidate error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@plates_router.get("/get_plates")
async def get_plates_route():
    try:
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
    try:
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
async def get_cameras_route():
    try:
        cameras = await get_cameras()
        return cameras
    except Exception as e:
        logger.error(f"Error fetching cameras: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@plates_router.get("/get_watchlists")
async def get_watchlists_route():
    try:
        watchlists = await get_watchlists(user_id=None, is_admin=False)
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
    character_confidences: Optional[List[float]] = None,
    province_confidence: Optional[float] = None
):
    try:
        if character_confidences and len(character_confidences) != len(plate_number):
            raise HTTPException(
                status_code=400,
                detail="จำนวน character_confidences ไม่ตรงกับจำนวนตัวอักษรใน plate_number"
            )

        result = await add_plate_candidate(
            plate_number=plate_number,
            province=province,
            id_camera=id_camera,
            camera_name=camera_name,
            user_id=None,
            character_confidences=character_confidences,
            province_confidence=province_confidence
        )

        return {
            "status": "candidate_submitted",
            "plate_number": plate_number,
            "timestamp": result.get("created_at"),
            "province": province,
            "id_camera": id_camera,
            "camera_name": camera_name
        }

    except Exception as e:
        logger.error(f"Error adding plate: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@plates_router.delete("/delete_watchlist/{watchlist_id}")
async def delete_watchlist(watchlist_id: str, request: Request):
    try:
        watchlist_data = supabase_client.table("watchlists").select("*").eq("id", watchlist_id).single().execute()
        if not watchlist_data.data:
            raise HTTPException(status_code=404, detail="ไม่พบรายการติดตามที่ระบุ")
        supabase_client.table("alerts").delete().eq("watchlist_id", watchlist_id).execute()
        response = supabase_client.table("watchlists").delete().eq("id", watchlist_id).execute()
        if hasattr(response, 'error') and response.error:
            raise HTTPException(status_code=500, detail=f"Error deleting watchlist: {response.error}")
        return {"message": "ลบรายการติดตามสำเร็จ"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting watchlist: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@plates_router.get("/get_alerts")
async def get_alerts_route(request: Request, status: Optional[str] = None):
    try:
        alerts = await get_alerts(status)
        return alerts
    except Exception as e:
        logger.error(f"Error fetching alerts: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@plates_router.put("/update_alert/{alert_id}")
async def update_alert(
    alert_id: str,
    status: str,
    notes: Optional[str] = None
):
    try:
        if status not in ["new", "viewed", "handled", "ignored"]:
            raise HTTPException(status_code=400, detail="สถานะไม่ถูกต้อง")
        alert_data = supabase_client.table("alerts").select("*").eq("id", alert_id).single().execute()
        if not alert_data.data:
            raise HTTPException(status_code=404, detail="ไม่พบการแจ้งเตือนที่ระบุ")
        data = {
            "status": status,
            "notes": notes,
            "updated_at": "now()"
        }
        response = supabase_client.table("alerts").update(data).eq("id", alert_id).execute()
        if hasattr(response, 'error') and response.error:
            raise HTTPException(status_code=500, detail=f"Error updating alert: {response.error}")
        return {"message": "อัปเดตสถานะการแจ้งเตือนสำเร็จ", "data": response.data[0] if response.data else None}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating alert: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@plates_router.get("/candidates")
async def list_candidates_route(current_user=Depends(is_admin)):
    return await get_plate_candidates()

@plates_router.put("/edit_plate/{plate_id}")
async def edit_plate_route(
    plate_id: str,
    new_plate: str,
    reason: Optional[str] = None,
    request: Request = None,
    current_user=Depends(is_admin)
):
    result = await edit_plate(plate_id, new_plate, edited_by=current_user["user_id"], reason=reason)
    await log_activity(
        user_id=current_user["user_id"],
        action="edit_plate",
        description=f"Edited plate {plate_id} -> {new_plate}. Reason: {reason}",
        ip=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    return result

@plates_router.get("/plate/history/{plate_id}")
async def get_plate_history_route(plate_id: str, current_user=Depends(get_current_user)):
    try:
        response = supabase_client.table("plate_edits").select("*").eq("plate_id", plate_id).order("edited_at", desc=True).execute()
        if hasattr(response, 'error') and response.error:
            raise HTTPException(status_code=500, detail=response.error)
        return response.data or []
    except Exception as e:
        logger.error(f"Error getting plate history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@plates_router.get("/logs/activity")
async def get_activity_logs(current_user=Depends(is_admin)):
    try:
        response = supabase_client.table("activity_logs").select("*").order("created_at", desc=True).limit(100).execute()
        if hasattr(response, 'error') and response.error:
            raise HTTPException(status_code=500, detail=response.error)
        return response.data or []
    except Exception as e:
        logger.error(f"Error getting logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))
