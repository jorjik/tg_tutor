from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import get_settings

_security = HTTPBasic()


def require_admin(credentials: HTTPBasicCredentials = Depends(_security)) -> str:
    """Зависимость FastAPI: проверяет HTTP Basic Auth для веб-админки."""
    settings = get_settings()
    ok_user = secrets.compare_digest(
        credentials.username.encode(), settings.admin_web_username.encode()
    )
    ok_pass = secrets.compare_digest(
        credentials.password.encode(), settings.admin_web_password.encode()
    )
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверные учётные данные",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
