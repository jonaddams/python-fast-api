from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from nutrient_sdk import License

from app.config import NUTRIENT_LICENSE_KEY, ALLOWED_ORIGINS
from app.routers import health, conversion, editor, forms, signing, extraction

License.register_key(NUTRIENT_LICENSE_KEY)

app = FastAPI(title="Nutrient Python SDK Demo")

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
