import logging
from datetime import datetime
from app.config import supabase_client
from typing import Optional


logger = logging.getLogger(__name__)

async def log_activity(
    user_id: str,
    action: str,
    description: Optional[str] = "",
    ip: Optional[str] = None,
    user_agent: Optional[str] = None
):
    """
    บันทึก log กิจกรรมของผู้ใช้ลงใน Supabase
    """
    try:
        data = {
            "user_id": user_id,
            "action": action,
            "description": description,
            "ip_address": ip,
            "user_agent": user_agent,
            "created_at": datetime.utcnow().isoformat()
        }
        response = supabase_client.table("activity_logs").insert(data).execute()
        if hasattr(response, "error") and response.error:
            logger.error(f"Error logging activity: {response.error}")
    except Exception as e:
        logger.error(f"Exception while logging activity: {e}")
