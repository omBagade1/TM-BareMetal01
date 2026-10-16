import uvicorn

from app import config
from app.main import app

if __name__ == "__main__":
    config.ensure_dirs()
    uvicorn.run(app, host=config.BACKEND_HOST, port=config.BACKEND_PORT, log_level="info")