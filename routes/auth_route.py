from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import timedelta
from auth.dependencies import get_current_user
from database.connection import get_database
from models.user_model import UserCreate, UserLogin
from services.user_service import UserService,UserResponse
from auth.dependencies import create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES

router = APIRouter(prefix="/api/auth", tags=["authentication"])

@router.post("/register", response_model=dict)
async def register_user(
    user_data: UserCreate,
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Register a new user"""
    try:
        user_service = UserService(db)
        user = await user_service.create_user(user_data)
        
        # Create access token
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": str(user["_id"])},
            expires_delta=access_token_expires
        )
        
        return {
            "user": {
                "id": str(user["_id"]),
                "username": user["username"],
                "email": user["email"],
                "token": access_token
            },
            "message": "User registered successfully"
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {str(e)}"
        )

@router.post("/login", response_model=dict)
async def login_user(
    login_data: UserLogin,
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Login user"""
    try:
        user_service = UserService(db)
        user = await user_service.authenticate_user(login_data.email, login_data.password)
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password"
            )
        
        # Create access token
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": str(user["_id"])},
            expires_delta=access_token_expires
        )
        
        return {
            "user": {
                "id": str(user["_id"]),
                "username": user["username"],
                "email": user["email"],
                "token": access_token
            },
            "message": "Login successful"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Login failed: {str(e)}"
        )

@router.post("/logout")
async def logout_user(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Logout user"""
    try:
        user_service = UserService(db)
        await user_service.update_online_status(str(current_user["_id"]), False)
        
        return {"message": "Logout successful"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Logout failed: {str(e)}"
        )
    
@router.get("/user/{user_id}", response_model=UserResponse)
async def get_user_by_id(
    user_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    """Return a single user document by its MongoDB _id."""
    user_service = UserService(db)
    user = await user_service.get_user_by_id(user_id)

    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Map DB document → response model
    return UserResponse(
            id=str(user["_id"]),
            username=user["username"],
            email=user["email"],
            avatar_url=user.get("avatar_url"),
            is_online=user.get("is_online", False),
            last_seen=user.get("last_seen")
        )
