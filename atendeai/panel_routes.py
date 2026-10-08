"""Interface do operador; dados continuam protegidos pelas rotas administrativas."""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


def panel_router():
    router = APIRouter()
    static = Path(__file__).parent / "static"
    headers = {
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'self'",
    }

    @router.get("/painel", include_in_schema=False)
    def panel():
        return FileResponse(static / "panel.html", media_type="text/html", headers=headers)

    @router.get("/painel/painel.css", include_in_schema=False)
    def stylesheet():
        return FileResponse(static / "panel.css", media_type="text/css", headers=headers)

    @router.get("/painel/painel.js", include_in_schema=False)
    def script():
        return FileResponse(static / "panel.js", media_type="application/javascript", headers=headers)

    return router
