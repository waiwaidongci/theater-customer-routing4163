from datetime import UTC
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from src.config.database import connection
from src.constants.enums import Role
from src.controllers.auth import allow, current
from src.models.identity import User
from src.schemas.requests import RuleRequest
from src.services import rules
from src.utils import views

router = APIRouter(prefix='/rules')


@router.get('')
def index(db: Session = Depends(connection), actor: User = Depends(current)):
    # 已发布版本全量可查，发布中断不会波及旧版。
    return [views.rule(item) for item in rules.published(db)]


@router.post('', status_code=201)
def publish(body: RuleRequest, db: Session = Depends(connection),
            actor: User = Depends(allow(Role.ADMIN, Role.ANALYST))):
    if body.effective_at.tzinfo is None:
        raise ValueError('生效时刻需要明确时区')
    effective_at = body.effective_at.astimezone(UTC).replace(tzinfo=None)
    item = rules.publish(db, actor, body, effective_at)
    return views.rule(rules.as_dict(item))
