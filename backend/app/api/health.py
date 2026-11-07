"""Operational health routes that never depend on PostgreSQL or providers."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.dependencies import reject_unexpected_input

router = APIRouter(tags=["health"], prefix="/health", dependencies=[Depends(reject_unexpected_input)],)

class LiveResponse(BaseModel):
    """Liveness only confirms that this process can answer."""

    status: Literal["alive"]

@router.get("/live")
def live() -> LiveResponse:
    """Report that this process can answer HTTP requests."""
    return LiveResponse(status="alive")