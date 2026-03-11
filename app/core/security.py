import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.config import get_settings

settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=False)


def create_access_token(subject: str | UUID | Any, expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {"sub": str(subject), "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _decode_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


async def get_current_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> UUID:
    """FastAPI dependency — extracts and validates the JWT, returns user UUID.
    When SKIP_USER_AUTH is True (auth not implemented), returns a fixed anonymous user ID.
    """
    if settings.SKIP_USER_AUTH:
        return UUID("00000000-0000-0000-0000-000000000001")  # anonymous when auth disabled
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    try:
        payload = _decode_token(credentials.credentials)
        user_id: str = payload.get("sub", "")
        if not user_id:
            raise ValueError("Empty subject")
        return UUID(user_id)
    except (JWTError, ValueError, AttributeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


def encrypt_json(data: dict) -> str:
    """Encrypt a dictionary into a Fernet token string."""
    # Use a real key from settings if provided (base64 encoded 32 bytes)
    try:
        f = Fernet(settings.ENCRYPTION_KEY.encode())
    except Exception:
        # Fallback for dev/missing key (in prod this should be fixed)
        f = Fernet(Fernet.generate_key())
    return f.encrypt(json.dumps(data).encode()).decode()


def decrypt_json(token: str) -> dict:
    """Decrypt a Fernet token string back into a dictionary."""
    try:
        f = Fernet(settings.ENCRYPTION_KEY.encode())
    except Exception:
        return {"error": "Invalid decryption key"}
    return json.loads(f.decrypt(token.encode()).decode())
