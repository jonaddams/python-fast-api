from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from nutrient_sdk import License

from app.auth import SharedSecretMiddleware, warn_if_open
from app.config import NUTRIENT_LICENSE_KEY, ALLOWED_ORIGINS
from app.routers import health, conversion, editor, forms, signing, extraction, templates, redaction

License.register_key(NUTRIENT_LICENSE_KEY)

app = FastAPI(title="Nutrient Python SDK Demo")

warn_if_open()

# Order matters. Starlette applies the LAST-added middleware outermost, so the
# auth check is added first and CORS wraps it — otherwise a 401 would come back
# without CORS headers and reach the browser as an opaque network error rather
# than the status it actually is.
app.add_middleware(SharedSecretMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(conversion.router)
app.include_router(editor.router)
app.include_router(forms.router)
app.include_router(signing.router)
app.include_router(extraction.router)
app.include_router(templates.router)
app.include_router(redaction.router)
