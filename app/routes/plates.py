from typing import Optional, List, Dict, Any
from datetime import datetime
import logging
import json
from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Body, Request
from app.config import supabase_client, SUPABASE_URL
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
    edit_plate,
    add_plate_image,
    edit_plate_candidate,
)
from app.utils.log_utils import log_activity

logger = logging.getLogger(__name__)
plates_router = APIRouter(prefix="/plates", tags=["plates"])


@plates_router.post("/add_plate", response_model=PlateResponse)
async def add_plate_route(candidate: PlateAddDetailedRequest, request: Request):
    """
    รับข้อมูล plate candidate จาก Cira core
    → ไม่ต้องมี JWT
    → เซิร์ฟเวอร์กำหนด timestamp เอง
    → คืนค่า PlateResponse พร้อม correlation_id
    """
    try:
        row = await add_plate_candidate(
            plate_number=candidate.plate_number,
            province=candidate.province,
            id_camera=candidate.id_camera,
            camera_name=candidate.camera_name,
            user_id=None,
            character_confidences=[ci.confidence for ci in candidate.character_confidences],
            province_confidence=candidate.province_confidence
        )
        await log_activity(
            user_id=None,
            action="add_plate_candidate",
            description=f"Plate candidate added: {row['correlation_id']}",
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent")
        )
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
async def upload_image_no_auth(file: UploadFile = File(...), request: Request = None):
    """
    อัปโหลดภาพเข้าที่ storage และบันทึก record ใน plate_images (ไม่ผูกผู้ใช้)
    """
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

        await log_activity(
            user_id=None,
            action="upload_image",
            description=f"uploaded={filename}",
            ip=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent") if request else None
        )
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
    user: dict = Depends(get_current_user),
    request: Request = None
):
    try:
        plate_id = await verify_plate_candidate(candidate_id, verified_by_user_id=user["user_id"])
        await log_activity(
            user_id=user["user_id"],
            action="verify_plate",
            description=f"candidate={candidate_id} -> plate={plate_id}",
            ip=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent") if request else None
        )
        return {"message": "Verified successfully", "plate_id": plate_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@plates_router.delete("/candidates/{candidate_id}")
async def reject_plate_candidate_route(
    candidate_id: str,
    user: dict = Depends(get_current_user),
    request: Request = None
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
        f"Rejected plate candidate {candidate_id}",
        ip=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent") if request else None
    )
    return {"message": "Rejected successfully"}


@plates_router.get("/get_plates", response_model=List[PlateModel])
async def get_plates_route():
    """
    ดึงป้ายที่ verify แล้วทั้งหมด
    → เรียงลำดับใหม่สุดก่อน ตาม created_at
    → คืน raw dict พร้อม `id` และ `timestamp`
    """
    try:
        resp = supabase_client \
            .table("plates") \
            .select("*") \
            .order("created_at", desc=True) \
            .execute()
        if getattr(resp, "error", None):
            logger.error(f"Error fetching plates: {resp.error}")
            raise HTTPException(status_code=500, detail=str(resp.error))

        data = resp.data or []
        # แปลงชื่อคีย์ created_at → timestamp
        for item in data:
            item["timestamp"] = item.pop("created_at")
        return data

    except Exception as e:
        logger.error(f"Get Plates Exception: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@plates_router.get("/db_images")
async def get_plate_images_from_db(limit: int = 30, current_user=Depends(get_current_user)):
    try:
        resp = supabase_client.table("plate_images") \
            .select("image_name") \
            .eq("is_verified", False) \
            .order("uploaded_at", desc=True) \
            .limit(limit) \
            .execute()
        if getattr(resp, "error", None):
            logger.error(f"Error fetching plate_images: {resp.error}")
            raise HTTPException(status_code=500, detail=str(resp.error))
        images = [
            {
                "name": item["image_name"],
                "url": f"{SUPABASE_URL}/storage/v1/object/public/plates/{item['image_name']}"
            }
            for item in resp.data or []
        ]
        return images
    except Exception as e:
        logger.error(f"Get plate_images error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@plates_router.delete("/delete_plate/{plate_id}")
async def delete_plate_route(
    plate_id: str,
    current_user=Depends(is_admin),
    request: Request = None
):
    """
    ลบป้ายที่ verify แล้ว จากตาราง `plates`
    → เฉพาะ admin เท่านั้น
    """
    try:
        resp = supabase_client \
            .table("plates") \
            .delete() \
            .eq("id", plate_id) \
            .execute()
        if getattr(resp, "error", None):
            logger.error(f"Error deleting plate: {resp.error}")
            raise HTTPException(status_code=500, detail=str(resp.error))

        await log_activity(
            user_id=current_user["user_id"],
            action="delete_plate",
            description=f"Deleted plate {plate_id}",
            ip=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent") if request else None
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


@plates_router.delete("/delete_image/{image_name:path}")
async def delete_plate_image_route(image_name: str, current_user=Depends(get_current_user), request: Request = None):
    try:
        # ลบไฟล์จาก storage
        resp = supabase_client.storage.from_("plates").remove([image_name])
        if getattr(resp, "error", None):
            raise HTTPException(status_code=500, detail=str(resp.error))

        # ลบแถวจาก table plate_images
        supabase_client.table("plate_images") \
            .delete() \
            .eq("image_name", image_name) \
            .execute()

        await log_activity(
            user_id=current_user["user_id"],
            action="delete_plate_image",
            description=f"Deleted image and record: {image_name}",
            ip=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent") if request else None
        )

        return {"status": "success", "deleted": image_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- แก้ไขเฉพาะหน้า Verify + LOG + plate_edits ช่วง pre-verify ----------
@plates_router.patch("/candidates/{candidate_id}")
@plates_router.put("/candidates/{candidate_id}")
async def edit_plate_candidate_route(
    candidate_id: str,
    update_data: dict = Body(...),
    current_user=Depends(get_current_user),
    request: Request = None
):
    """
    แก้ไขฟิลด์ใดๆ ของ plate_candidates ตาม update_data
    รองรับ front-end field:
      - plate_number  → แปลงเป็น DB col 'plate'
      - province, camera_name, id_camera ฯลฯ
    - ถ้าเลขป้ายเปลี่ยน → แทรก log ลง table `plate_edits` ทันที (ยังไม่มี plate_id ก็ปล่อยให้เป็น NULL)
      และ reason จะถูกตั้งเป็น "pre-verify edit (candidate_id=<id>)"
    - เก็บ activity_logs ด้วย (action=edit_plate_candidate, description=diff old→new)
    """
    # map field จากฝั่ง UI
    mapped: Dict[str, Any] = {}
    for key, value in update_data.items():
        if key == "plate_number":
            mapped["plate"] = value
        else:
            mapped[key] = value

    # ดึงค่าเดิมเพื่อคำนวณ diff
    before_res = supabase_client.table("plate_candidates").select("*").eq("id", candidate_id).single().execute()
    if not before_res.data:
        raise HTTPException(status_code=404, detail="Candidate not found")
    before = before_res.data

    try:
        updated = await edit_plate_candidate(candidate_id, mapped)

        # ทำ diff
        diffs = {}
        for k, new_val in mapped.items():
            label = "plate_number" if k == "plate" else k
            old_val = before.get(k if k != "plate" else "plate")
            if old_val != new_val:
                diffs[label] = {"old": old_val, "new": new_val}

        # ถ้ามีการเปลี่ยนเลขป้ายจริง ให้จดลง plate_edits แบบ pre-verify
        if "plate" in mapped and before.get("plate") != mapped["plate"]:
            reason = f"pre-verify edit (candidate_id={candidate_id})"
            supabase_client.table("plate_edits").insert({
                "id": str(uuid.uuid4()),
                # plate_id ยังไม่ทราบตอนนี้ → ปล่อย NULL
                "old_plate": before.get("plate"),
                "new_plate": mapped["plate"],
                "edited_by": current_user["user_id"],
                "reason": reason
            }).execute()

        # เก็บ activity log
        if diffs:
            await log_activity(
                user_id=current_user["user_id"],
                action="edit_plate_candidate",
                description=json.dumps({
                    "candidate_id": candidate_id,
                    "changes": diffs
                }, ensure_ascii=False),
                ip=request.client.host if request and request.client else None,
                user_agent=request.headers.get("user-agent") if request else None
            )

        return {
            "message": "Updated successfully",
            "updated": updated
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
