"""Interface do operador; dados continuam protegidos pelas rotas administrativas."""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

STATIC = Path(__file__).parent / "static"
HEADERS = {
    "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'self'",
}


def application_page():
    markup = (STATIC / "application.html").read_text(encoding="utf-8").replace(
        "<!--APPLICATION_FORM-->", (STATIC / "application-form.html").read_text(encoding="utf-8"))
    return HTMLResponse(markup, headers=HEADERS)


def home_page():
    return FileResponse(STATIC / "home.html", media_type="text/html", headers=HEADERS)


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

    router.add_api_route("/aplicar", application_page, methods=["GET"], include_in_schema=False)

    @router.get("/aplicar/conteudo", include_in_schema=False)
    def application_content():
        return FileResponse(STATIC / "application-form.html", media_type="text/html", headers=HEADERS)

    @router.get("/home/home.css", include_in_schema=False)
    def home_stylesheet():
        return FileResponse(STATIC / "home.css", media_type="text/css", headers=HEADERS)

    @router.get("/home/home.js", include_in_schema=False)
    def home_script():
        return FileResponse(STATIC / "home.js", media_type="application/javascript", headers=HEADERS)

    @router.get("/home/visuais/{asset}", include_in_schema=False)
    def visual_asset(asset: str):
        from fastapi import HTTPException
        types = {"nelvo-intro.mp4": "video/mp4", "nelvo-intro.vtt": "text/vtt",
                 "nelvo-poster.jpg": "image/jpeg", "nelvo-connected.png": "image/png", "nelvo-studio.png": "image/png"}
        if asset not in types:
            raise HTTPException(status_code=404, detail="Recurso não encontrado.")
        return FileResponse(STATIC / "media" / asset, media_type=types[asset], headers=HEADERS)

    @router.get("/marca.png", include_in_schema=False)
    def original_brand():
        return FileResponse(STATIC / "nelvo-logo-transparent.png", media_type="image/png", headers=HEADERS)

    @router.get("/aplicar/formulario.js", include_in_schema=False)
    def application_script():
        return FileResponse(static / "application.js", media_type="application/javascript", headers=HEADERS)

    @router.get("/marca.svg", include_in_schema=False)
    def brand():
        return FileResponse(static / "brand.svg", media_type="image/svg+xml", headers=HEADERS)

    return router
