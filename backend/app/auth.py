import jwt
import os
from datetime import datetime, timedelta
from fastapi import HTTPException, status

# For now, we'll create a simple auth module
# In production, this would integrate with the OAuth system

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-here")
ALGORITHM = "HS256"

def verify_token(token: str) -> int:
    """
    Verify JWT token and return user ID
    For now, this is a placeholder that returns a test user ID
    """
    try:
        # In production, this would verify the JWT token
        # For development, we'll return a test user ID
        if token == "test-token":
            return 1
        
        # Attempt to decode JWT (if implemented)
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )
        return user_id
        
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

def create_access_token(user_id: int) -> str:
    """
    Create JWT access token for user
    """
    expire = datetime.utcnow() + timedelta(hours=24)
    payload = {
        "user_id": user_id,
        "exp": expire
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
