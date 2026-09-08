from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(tags=["Health"])


# Kept here rather than under app/models/: this is a transverse liveness probe,
# not a business domain, and no other layer will ever import this model.
class HealthResponse(BaseModel):
    status: str = Field(
        description="Always 'ok'. The endpoint answers only if the API process "
        "is alive and serving requests.",
    )


@router.get(
    path="/health",
    response_model=HealthResponse,
    summary="Liveness probe",
    description=(
        "Returns 200 as long as the API process is up. It reports nothing about "
        "the state of any upstream or backing service, so a 200 here does not "
        "promise that a lookup will succeed."
    ),
)
async def get_health() -> HealthResponse:
    # The one tolerated exception to Route → Service → Repository (CLAUDE.md §2):
    # a liveness probe carries no business rule of ours, so a service layer here
    # would be an empty shell forwarding a constant.
    #
    # It stays deliberately minimal and must never grow into a readiness probe:
    # the session pool state and the account count are exploitable by a third
    # party, and this route is the one exempted from the RapidAPI secret
    # middleware (CLAUDE.md §5) — so whatever it returns is public.
    return HealthResponse(status="ok")
