from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from style_convert.routers.convert import router as convert_router

_STATIC_DIR = Path(__file__).resolve().parent / "style_convert" / "static"

app = FastAPI(
    title="style-convert",
    description="Apply a reference style to a target image (OpenAI or Anthropic + OpenAI Images), export `.ai` via Convertio.",
    version="0.1.0",
)

app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
app.include_router(convert_router, tags=["convert"])


@app.get("/", include_in_schema=False)
async def serve_ui() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": exc.errors()})
