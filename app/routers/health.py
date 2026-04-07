from fastapi import APIRouter

router = APIRouter()


@router.get("/api/health")
def health():
    return {"status": "ok", "service": "nutrient-python-sdk-demo"}
