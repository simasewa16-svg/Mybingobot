"""
=====================================================================
✅ የብዙ አስተዳዳሪዎች ፈቃድ ስርዓት (admin_auth.py) - v1.1 SECURED
=====================================================================
✅ Intersection approach: ብጁ ፈቃዶች የRole ፈቃዶችን ብቻ ይገድባሉ
✅ የተከለከሉ ፈቃዶች ውድቅ ይደረጋሉ
✅ የAdmin ድርጊት ምዝገባ (Audit Log)
✅ የRole ስርዓት: super_admin, sub_admin, finance_admin, moderator, viewer
=====================================================================
"""
import json
import logging
from fastapi import HTTPException
from sqlalchemy.orm import Session
import models

logger = logging.getLogger(__name__)

# =====================================================================
# ✅ ሁሉም የሚቻሉ ፈቃዶች
# =====================================================================
ALL_PERMISSIONS = [
    "view_dashboard",
    "view_players",
    "edit_players",
    "ban_players",
    "adjust_balance",
    "approve_deposits",
    "approve_withdrawals",
    "view_games",
    "control_games",
    "view_reports",
    "export_data",
    "manage_admins",
    "view_audit",
]

# =====================================================================
# ✅ ነባሪ ፈቃዶች በሚና
# =====================================================================
ROLE_PERMISSIONS = {
    "super_admin": ALL_PERMISSIONS,
    "sub_admin": [
        "view_dashboard",
        "view_players",
        "edit_players",
        "ban_players",
        "approve_deposits",
        "approve_withdrawals",
        "view_games",
        "view_reports",
        "export_data",
    ],
    "finance_admin": [
        "view_dashboard",
        "view_players",
        "approve_deposits",
        "approve_withdrawals",
        "view_reports",
        "export_data",
    ],
    "moderator": [
        "view_dashboard",
        "view_players",
        "ban_players",
        "view_games",
        "control_games",
    ],
    "viewer": [
        "view_dashboard",
        "view_players",
        "view_games",
        "view_reports",
    ],
}


def get_admin_user(db: Session, telegram_id: str):
    """የAdmin ተጠቃሚ ማግኘት (ንቁ ብቻ)"""
    if not telegram_id:
        return None
    return db.query(models.AdminUser).filter(
        models.AdminUser.telegram_id == str(telegram_id),
        models.AdminUser.is_active == True
    ).first()


def get_admin_permissions(admin: models.AdminUser) -> list:
    """
    ✅ SECURED: ብጁ ፈቃዶች የRole ፈቃዶችን ብቻ ማጥበብ ይችላሉ,
    ማስፋፋት አይችሉም (Intersection approach)
    """
    if not admin or not admin.is_active:
        return []

    role_perms = set(ROLE_PERMISSIONS.get(admin.role, []))
    if not role_perms:
        return []

    if not admin.permissions:
        return sorted(role_perms)

    try:
        custom = json.loads(admin.permissions)
        if not isinstance(custom, list):
            return sorted(role_perms)

        # ✅ ትክክለኛ የሆኑ ፈቃዶች ብቻ
        allowed = set(ALL_PERMISSIONS)
        safe_custom = {
            p for p in custom
            if isinstance(p, str) and p in allowed
        }

        # ✅ SECURED: Intersection — ብጁ ፈቃዶች የRole ገደብን አያልፉ
        final_perms = role_perms & safe_custom
        return sorted(final_perms) if final_perms else sorted(role_perms)

    except (json.JSONDecodeError, TypeError):
        return sorted(role_perms)


def has_permission(admin: models.AdminUser, permission: str) -> bool:
    """አንድ ፈቃድ ካለው ማረጋገጥ"""
    if not admin or not admin.is_active:
        return False
    if admin.role == "super_admin":
        return True
    perms = get_admin_permissions(admin)
    return permission in perms


def is_super_admin(admin: models.AdminUser) -> bool:
    """Super Admin መሆኑን ማረጋገጥ"""
    return bool(
        admin
        and admin.role == "super_admin"
        and admin.is_active
    )


def require_permission(admin: models.AdminUser, permission: str):
    """የAdmin ፈቃድ ማረጋገጫ (Exception ይጣላል)"""
    if not admin:
        raise HTTPException(status_code=403, detail="የAdmin ፈቃድ የለዎትም")
    if not has_permission(admin, permission):
        raise HTTPException(
            status_code=403,
            detail=f"ይህን ለማድረግ ፈቃድ የለዎትም: {permission}"
        )


def log_admin_action(
    db: Session,
    admin: models.AdminUser,
    action: str,
    target_type: str = None,
    target_id: str = None,
    details: str = None
):
    """የAdmin ድርጊት መዝገብ (Audit Log)"""
    try:
        db.add(models.AuditLog(
            actor_id=admin.telegram_id,
            actor_username=admin.display_name,
            actor_role=admin.role,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            details=details
        ))
    except Exception as e:
        logger.error(f"Audit log error: {e}")
