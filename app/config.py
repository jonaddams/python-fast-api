import os
from dotenv import load_dotenv

load_dotenv()

NUTRIENT_LICENSE_KEY = os.environ.get("NUTRIENT_LICENSE_KEY", "")
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
PORT = int(os.environ.get("PORT", "8080"))
