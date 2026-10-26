from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(include_in_schema=False)
WEB_ROOT = Path(__file__).resolve().parents[2] / "web"


@router.get("/")
async def portal() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html", media_type="text/html")
