import os

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)
_valid_keys: frozenset[str] = frozenset()


def load_keys() -> None:
    """Load API keys from the IPAM_API_KEY environment variable (set via .env).

    IPAM_API_KEY should be a comma-separated list of keys, e.g.:
        IPAM_API_KEY=key1,key2
    """
    global _valid_keys
    raw = os.environ.get("IPAM_API_KEY", "")
    _valid_keys = frozenset(k.strip() for k in raw.split(",") if k.strip())


def verify_api_key(
    creds: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> None:
    if not _valid_keys:
        raise HTTPException(
            status_code=500,
            detail="Server misconfiguration: IPAM_API_KEY is not set",
        )

    if creds is None or creds.credentials not in _valid_keys:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
