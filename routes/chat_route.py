from fastapi import APIRouter, Depends, HTTPException, status, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import List
from bson import ObjectId
from database.connection import get_database
from models.chat_model import ChatCreate, ChatsListResponse
from models.message_model import MessageCreate, MessagesListResponse
from models.user_model import UserResponse
from services.chat_service import ChatService
from services.message_service import MessageService
from services.user_service import UserService
from auth.dependencies import get_current_user
from bson.errors import InvalidId
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chats"])

@router.get("/chats", response_model=ChatsListResponse)
async def get_user_chats(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    try:
        # Validate authenticated user data
        if not current_user or "_id" not in current_user:
            logger.warning("Invalid user data in authentication")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication data"
            )
        
        # Extract and validate user ID
        try:
            user_id = str(current_user["_id"])
            ObjectId(user_id)  # Validate ObjectId format
        except (KeyError, InvalidId, TypeError) as e:
            logger.error(f"Invalid user ID format: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid user ID format"
            )
        
        # Initialize chat service
        chat_service = ChatService(db)
        
        # Retrieve user's chats
        logger.info(f"Fetching chats for user: {user_id}")
        chats = await chat_service.get_user_chats(user_id)
        
        logger.info(f"Successfully retrieved {len(chats)} chats for user: {user_id}")
        
        return {
            "chats": chats,
            "success": True
        }
        
    except HTTPException:
        raise
    except InvalidId as e:
        logger.error(f"Invalid ObjectId: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid ID format"
        )
    except Exception as e:
        logger.error(f"Error in get_user_chats: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load chats"
        )

@router.get("/chats", response_model=ChatsListResponse)
async def get_user_chats(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Get all chats for the current user"""
    try:
        user_id = str(current_user["_id"])
        chat_service = ChatService(db)
        chats = await chat_service.get_user_chats(user_id)
        
        return {"chats": chats}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load chats: {str(e)}"
        )

@router.get("/users", response_model=dict)
async def get_all_users(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Get all users except current user"""
    try:
        user_id = str(current_user["_id"])
        user_service = UserService(db)
        users = await user_service.get_all_users_except(user_id)
        
        user_list = [
            user_service.format_user_response(user).dict()
            for user in users
        ]
        
        return {"users": user_list}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load users: {str(e)}"
        )

@router.post("/chats", response_model=dict)
async def create_chat(
    chat_data: ChatCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Create a new chat"""
    try:
        user_id = str(current_user["_id"])
        chat_service = ChatService(db)
        chat = await chat_service.create_chat(chat_data, user_id)
        
        return {"chat": chat}
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create chat: {str(e)}"
        )
