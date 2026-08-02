"""Aplicatia web."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from orar.web.deps import AICI, context_saptamana, templates
from orar.web.routers import grupa, index, sala

app = FastAPI(
    title="Orarul Sălilor — FMI",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
app.mount("/static", StaticFiles(directory=str(AICI / "static")), name="static")

app.include_router(index.router)
app.include_router(grupa.router)
app.include_router(sala.router)


@app.exception_handler(404)
async def not_found(request: Request, _exc: object) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="404.html",
        context=context_saptamana(),
        status_code=404,
    )


__all__ = ["app"]
