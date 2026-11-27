"""Public read-only exercise category and body-part lookup routes."""

from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import reject_unexpected_input
from app.api.errors import SHARED_RESPONSE_HEADERS, ErrorResponse, error_response


router = APIRouter(
    tags=["exercise lookups"],
    prefix="/api/v1",
    dependencies=[Depends(reject_unexpected_input)],
)


class LookupItem(BaseModel):
    """One stable, active database master-record choice."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(description="Stable database identifier.", examples=[1])
    name: str = Field(
        description="Approved display name.",
        examples=["Barbell"],
    )
    sort_order: int = Field(
        description="Database display position.",
        examples=[1],
    )


class LookupResponse(BaseModel):
    """Exactly the ordered active choices in an items collection."""

    model_config = ConfigDict(extra="forbid")

    items: list[LookupItem]


LOOKUP_ERRORS = {
    422: {
        "model": ErrorResponse,
        "description": "Unsupported query parameter or request body (invalid_request).",
        "headers": SHARED_RESPONSE_HEADERS,
    },
    503: {
        "model": ErrorResponse,
        "description": (
            "Database or required active lookup data unavailable "
            "(database_unavailable or reference_data_unavailable)."
        ),
        "headers": SHARED_RESPONSE_HEADERS,
    },
    500: {
        "model": ErrorResponse,
        "description": "Incompatible schema or unexpected failure (internal_error).",
        "headers": SHARED_RESPONSE_HEADERS,
    },
}


def _get_database_resources(app):
    """Reuse the one process-scoped bounded database pool and executor."""
    from app.api.health import _get_database_readiness

    return _get_database_readiness(app)


async def _lookup(
    request: Request,
    table_name: Literal["exercise_categories", "body_parts"],
) -> LookupResponse | JSONResponse:
    """Run an independent three-second lookup and map only safe outcomes."""
    resources = _get_database_resources(request.app)
    result = await resources.lookup(table_name)
    from app.db.readiness import ReadinessState

    if result.state == ReadinessState.READY:
        return LookupResponse(items=result.items)
    if result.state == ReadinessState.DATABASE_UNAVAILABLE:
        return error_response(
            request,
            503,
            "database_unavailable",
            "The database is temporarily unavailable. Try again shortly.",
        )
    if result.state == ReadinessState.REFERENCE_DATA_UNAVAILABLE:
        return error_response(
            request,
            503,
            "reference_data_unavailable",
            "Required reference data is temporarily unavailable. Try again shortly.",
        )
    return error_response(
        request,
        500,
        "internal_error",
        "An unexpected error occurred.",
    )


@router.get(
    "/exercise-categories",
    response_model=LookupResponse,
    summary="List active exercise categories",
    description=(
        "Load the active exercise-category choices from PostgreSQL. "
        "The response is ordered by stored sort_order and then stable id. "
        "Inactive records remain in the database but are omitted. "
        "This public read-only request requires no sign-in, filtering, "
        "pagination, provider call, seed repair, or database write."
    ),
    response_description="Ordered active category choices.",
    responses={
        **LOOKUP_ERRORS,
        200: {
            "model": LookupResponse,
            "description": "Ordered active exercise-category choices.",
            "headers": SHARED_RESPONSE_HEADERS,
            "content": {
                "application/json": {
                    "examples": {
                        "initial_choices": {
                            "summary": "Approved initial category order",
                            "value": {
                                "items": [
                                    {"id": 1, "name": "Barbell", "sort_order": 1},
                                    {"id": 2, "name": "Dumbbell", "sort_order": 2},
                                    {"id": 3, "name": "Machine/Other", "sort_order": 3},
                                    {"id": 4, "name": "Bodyweight", "sort_order": 4},
                                    {"id": 5, "name": "Assisted Bodyweight", "sort_order": 5},
                                    {"id": 6, "name": "Reps Only", "sort_order": 6},
                                    {"id": 7, "name": "Cardio", "sort_order": 7},
                                    {"id": 8, "name": "Duration", "sort_order": 8},
                                ]
                            },
                        }
                    }
                }
            },
        },
    },
)
async def exercise_categories(request: Request) -> LookupResponse | JSONResponse:
    """Return all active categories in stable database display order."""
    return await _lookup(request, "exercise_categories")


@router.get(
    "/body-parts",
    response_model=LookupResponse,
    summary="List active body parts",
    description=(
        "Load the active body-part choices from PostgreSQL. "
        "The response is ordered by stored sort_order and then stable id. "
        "The None choice is an ordinary active database record; it is never "
        "returned as JSON null or an empty string. Inactive records remain "
        "unchanged and omitted. This public read-only request requires no "
        "sign-in, filtering, pagination, provider call, seed repair, or write."
    ),
    response_description="Ordered active body-part choices.",
    responses={
        **LOOKUP_ERRORS,
        200: {
            "model": LookupResponse,
            "description": "Ordered active body-part choices.",
            "headers": SHARED_RESPONSE_HEADERS,
            "content": {
                "application/json": {
                    "examples": {
                        "initial_choices": {
                            "summary": "Approved initial body-part order",
                            "value": {
                                "items": [
                                    {"id": 1, "name": "None", "sort_order": 1},
                                    {"id": 2, "name": "Arms", "sort_order": 2},
                                    {"id": 3, "name": "Back", "sort_order": 3},
                                    {"id": 4, "name": "Cardio", "sort_order": 4},
                                    {"id": 5, "name": "Chest", "sort_order": 5},
                                    {"id": 6, "name": "Core", "sort_order": 6},
                                    {"id": 7, "name": "Full Body", "sort_order": 7},
                                    {"id": 8, "name": "Legs", "sort_order": 8},
                                    {"id": 9, "name": "Olympic", "sort_order": 9},
                                    {"id": 10, "name": "Other", "sort_order": 10},
                                    {"id": 11, "name": "Shoulders", "sort_order": 11},
                                ]
                            },
                        }
                    }
                }
            },
        },
    },
)
async def body_parts(request: Request) -> LookupResponse | JSONResponse:
    """Return all active body parts in stable database display order."""
    return await _lookup(request, "body_parts")
