from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId
from typing import Optional
import os
import logging

logger = logging.getLogger(__name__)

from database.connection import get_database

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

security = HTTPBearer()

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now() + expires_delta
    else:
        expire = datetime.now() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncIOMotorDatabase = Depends(get_database)
) -> dict:
    """Get current authenticated user"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if user is None:
        raise credentials_exception
    
    return user


def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None

# async def verify_token(token:str):
#     try:
#         # Log the incoming connection attempt
#         # logger.info(f"WebSocket connection attempt from {websocket}")
#         # token = websocket.get("token")
#         if not token:
#             logger.warning("WebSocket connection rejected: Token missing")
#             # await websocket.close(code=1008, reason="Token missing")
#             return None
            
#         # Log token presence (don't log actual token for security)
#         logger.debug("Token received, attempting to decode")
        
#         payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
#         # Log successful authentication
#         logger.info(f"Token verified successfully for user: {payload.get('sub', 'unknown')}")
#         return payload
        
#     except JWTError as e:
#         # Log specific JWT errors
#         logger.error(f"JWT verification failed: {str(e)}")
#         return None
        
#     except Exception as e:
#         # Log unexpected errors
#         logger.error(f"Unexpected error in token verification: {str(e)}", exc_info=True)
#         return None

