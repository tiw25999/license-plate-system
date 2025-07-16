from typing import Optional, List
from datetime import datetime
import logging
from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Form
from app.config import supabase_client
import uuid

from app.routes.auth import get_current_user
from app.routes.auth_extra import is_admin
from app.schemas import (
    PlateModel,
    PlateResponse,
    SearchParams,
    PlateAddDetailedRequest,
    CharacterConfidenceItem,
)
from app.database import (
    get_plate_candidates,
    add_plate_candidate,
    verify_plate_candidate,
    get_plates,
    search_plates,
    get_cameras,
    get_watchlists,
    get_alerts,
    edit_plate,
    add_plate_image,
)
from app.utils.log_utils import log_activity
from app.config import supabase_client, SUPABASE_URL

logger = logging.getLogger(__name__)
plates_router = APIRouter(prefix="/plates", tags=["plates"])

@plates_router.post("/add_plate", response_model=PlateResponse)
async def add_plate_route(
    candidate: PlateAddDetailedRequest
):
    """
    รับข้อมูล plate candidate จาก Cira core
    → ไม่ต้องมี JWT
    → เซิร์ฟเวอร์กำหนด timestamp เอง
    → คืนค่า PlateResponse พร้อม correlation_id
    """
    try:
        # บันทึกลงฐานข้อมูล (timestamp ใช้ default ของ add_plate_candidate)
        row = await add_plate_candidate(
            plate_number=candidate.plate_number,
            province=candidate.province,
            id_camera=candidate.id_camera,
            camera_name=candidate.camera_name,
            user_id=None,  # ไม่มีผู้ใช้ (หรือใส่ค่าอื่นตามต้องการ)
            # ลบการอ้างอิง candidate.timestamp ออก
            character_confidences=[ci.confidence for ci in candidate.character_confidences],
            province_confidence=candidate.province_confidence
        )

        # เขียน log กิจกรรม (user_id=None)
        await log_activity(
            user_id=None,
            action="add_plate_candidate",
            description=f"Plate candidate added: {row['correlation_id']}"
        )

        # สร้าง Response ตาม schema
        return PlateResponse(
            id=row["id"],
            correlation_id=row["correlation_id"],
            status="candidate_submitted",
            plate_number=row["plate"],
            timestamp=row["created_at"],
            province=row.get("province"),
            id_camera=row.get("id_camera"),
            camera_name=row.get("camera_name"),
            character_confidences=[
                CharacterConfidenceItem(char=ci.char, confidence=ci.confidence)
                for ci in candidate.character_confidences
            ],
            province_confidence=row.get("province_confidence")
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@plates_router.post("/upload_image")
async def upload_image_no_auth(
    file: UploadFile = File(...)
):
    try:
        filename = file.filename
        contents = await file.read()

        supabase_client.storage.from_("plates").upload(
            path=filename,
            file=contents,
        )

        now = datetime.utcnow().isoformat()
        image_id = str(uuid.uuid4())

        supabase_client.table("plate_images").insert({
            "id": image_id,
            "image_path": filename,
            "image_name": filename,
            "uploaded_at": now,
            "is_verified": False
        }).execute()

        return {"status": "success", "image_id": image_id}
    except Exception as e:
        return {"status": "error", "detail": str(e)}





@plates_router.get("/candidates", response_model=List[PlateResponse])
async def list_plate_candidates_route(current_user=Depends(is_admin)):
    items = await get_plate_candidates()
    out: List[PlateResponse] = []
    for item in items:
        raw = item.get("character_confidences") or []
        chars = [
            CharacterConfidenceItem(char=ch, confidence=conf)
            for ch, conf in zip(item["plate"], raw)
        ]
        out.append(PlateResponse(
            id=item["id"],
            correlation_id=item["correlation_id"],
            status="candidate",
            plate_number=item["plate"],
            timestamp=item["created_at"],
            province=item.get("province"),
            id_camera=item.get("id_camera"),
            camera_name=item.get("camera_name"),
            character_confidences=chars,
            province_confidence=item.get("province_confidence")
        ))
    return out

@plates_router.post("/verify_plate/{candidate_id}")
async def verify_plate_candidate_route(
    candidate_id: str,
    user: dict = Depends(get_current_user)
):
    try:
        plate_id = await verify_plate_candidate(candidate_id, verified_by_user_id=user["user_id"])
        return {"message": "Verified successfully", "plate_id": plate_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@plates_router.delete("/candidates/{candidate_id}")
async def reject_plate_candidate_route(
    candidate_id: str,
    user: dict = Depends(get_current_user)
):
    resp = supabase_client.table("plate_candidates") \
                         .delete() \
                         .eq("id", candidate_id) \
                         .execute()
    if getattr(resp, "error", None):
        logger.error(f"Error rejecting candidate: {resp.error}")
        raise HTTPException(status_code=500, detail=str(resp.error))
    await log_activity(
        user["user_id"],
        "reject_plate",
        f"Rejected plate candidate {candidate_id}"
    )
    return {"message": "Rejected successfully"}


@plates_router.get("/get_plates", response_model=List[PlateModel])
async def get_plates_route():
    """
    ดึงป้ายที่ verify แล้วทั้งหมด
    → เรียงลำดับใหม่สุดก่อน ตาม created_at
    """
    try:
        # เรียก Supabase client แบบ synchronous (ไม่ต้อง await)
        resp = supabase_client \
            .table("plates") \
            .select("*") \
            .order("created_at", desc=True) \
            .execute()

        # เช็ค error จาก APIResponse
        if getattr(resp, "error", None):
            logger.error(f"Error fetching plates: {resp.error}")
            raise HTTPException(status_code=500, detail=str(resp.error))

        # คืน data หรือคืน empty list ถ้าไม่มี
        return resp.data or []

    except Exception as e:
        logger.error(f"Get Plates Exception: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    


@plates_router.delete("/delete_plate/{plate_id}")
async def delete_plate_route(
    plate_id: int,
    current_user=Depends(is_admin)
):
    """
    ลบป้ายที่ verify แล้ว จากตาราง `plates`
    → เฉพาะ admin เท่านั้น
    """
    try:
        # ลบ row จาก Supabase
        resp = supabase_client \
            .table("plates") \
            .delete() \
            .eq("id", plate_id) \
            .execute()

        if getattr(resp, "error", None):
            logger.error(f"Error deleting plate: {resp.error}")
            raise HTTPException(status_code=500, detail=str(resp.error))

        # เขียน log กิจกรรม
        await log_activity(
            user_id=current_user["user_id"],
            action="delete_plate",
            description=f"Deleted plate {plate_id}"
        )

        return {"message": "Deleted successfully", "deleted_id": plate_id}
    except Exception as e:
        logger.error(f"Delete Plate Exception: {e}")
        raise HTTPException(status_code=500, detail=str(e))



@plates_router.get("/search", response_model=List[PlateModel])
async def search_plates_route(params: SearchParams = Depends()):
    return await search_plates(**params.dict(exclude_none=True))


@plates_router.get("/get_cameras")
async def get_cameras_route():
    return await get_cameras()


@plates_router.get("/get_watchlists")
async def get_watchlists_route():
    return await get_watchlists(user_id=None, is_admin=False)


@plates_router.get("/get_alerts")
async def get_alerts_route(status: Optional[str] = None):
    return await get_alerts(status)


@plates_router.put("/edit_plate/{plate_id}")
async def edit_plate_route(
    plate_id: str,
    new_plate: str,
    reason: Optional[str] = None,
    request=None,
    current_user=Depends(is_admin)
):
    result = await edit_plate(
        plate_id,
        new_plate,
        edited_by=current_user["user_id"],
        reason=reason
    )
    await log_activity(
        user_id=current_user["user_id"],
        action="edit_plate",
        description=f"Edited plate {plate_id} → {new_plate}. Reason: {reason}",
        ip=request.client.host if request else None,
        user_agent=request.headers.get("user-agent") if request else None
    )
    return result


@plates_router.get("/plate/history/{plate_id}")
async def get_plate_history_route(
    plate_id: str,
    current_user=Depends(get_current_user)
):
    resp = supabase_client.table("plate_edits") \
                         .select("*") \
                         .eq("plate_id", plate_id) \
                         .order("edited_at", desc=True) \
                         .execute()
    if getattr(resp, "error", None):
        raise HTTPException(status_code=500, detail=str(resp.error))
    return resp.data or []


@plates_router.get("/logs/activity")
async def get_activity_logs_route(
    current_user=Depends(is_admin)
):
    resp = supabase_client.table("activity_logs") \
                         .select("*") \
                         .order("created_at", desc=True) \
                         .limit(100) \
                         .execute()
    if getattr(resp, "error", None):
        raise HTTPException(status_code=500, detail=str(resp.error))
    return resp.data or []
