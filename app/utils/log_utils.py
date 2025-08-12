import logging
from datetime import datetime
from typing import Optional

from app.config import supabase_client

logger = logging.getLogger(__name__)

async def log_activity(
    user_id: Optional[str],
    action: str,
    description: Optional[str] = "",
    ip: Optional[str] = None,
    user_agent: Optional[str] = None
):
    """
    บันทึกกิจกรรมลงตาราง activity_logs
    schema: user_id, action, description, ip_address, user_agent, id, created_at
    *ไม่แก้สคีมา/คอลัมน์ใดๆ*
    """
    try:
        data = {
            "user_id": user_id,
            "action": action,
            "description": description or "",
            "ip_address": ip,
            "user_agent": user_agent,
            # ถ้าตารางมี default ก็ไม่จำเป็น แต่ใส่ไว้ได้ ไม่ผิด
            "created_at": datetime.utcnow().isoformat()
        }
        resp = supabase_client.table("activity_logs").insert(data).execute()
        if hasattr(resp, "error") and resp.error:
            logger.error(f"[log_activity] insert error: {resp.error}")
    except Exception as e:
        logger.error(f"[log_activity] exception: {e}")
