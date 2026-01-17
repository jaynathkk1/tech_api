from fastapi import APIRouter ,Depends, HTTPException, status,Query
from models.message_model import MessagesListResponse,MessageCreate
from motor.motor_asyncio import AsyncIOMotorDatabase
from auth.dependencies import get_current_user
from database.connection import get_database
from services.message_service import MessageCreate,MessageResponse,MessageService
from typing import Dict,List,Any 
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["messages"])

@router.get("/chats/{chat_id}/messages", response_model=MessagesListResponse)
async def get_chat_messages(
    chat_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Get messages for a specific chat with pagination"""
    try:
        user_id = str(current_user["_id"])
        message_service = MessageService(db)
        messages = await message_service.get_chat_messages(chat_id, user_id, page, limit)
        
        return {"messages": messages}
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load messages: {str(e)}"
        )

@router.post("/messages", response_model=dict)
async def send_message(
    message_data: MessageCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Send a new message"""
    try:
        user_id = str(current_user["_id"])
        message_service = MessageService(db)
        message = await message_service.send_message(message_data, user_id)
        
        return {"message": message}
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send message: {str(e)}"
        )

@router.get("/message/{message_id}")
async def get_message_by_id(message_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database)):
    try:
        user_id = str(current_user["_id"])
        message_service = MessageService(db)
        message = await message_service.get_message_by_id(message_id)
        
        if not message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found"
            )
            
        return message
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get message: {str(e)}"
        )

    

@router.patch("/messages/{message_id}/read")
async def mark_message_as_read(
    message_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Mark message as read"""
    try:
        user_id = str(current_user["_id"])
        message_service = MessageService(db)
        success = await message_service.mark_message_as_read(message_id, user_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found or access denied"
            )
        
        return {"message": "Message marked as read"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to mark message as read: {str(e)}"
        )
    
@router.patch("/chats/{chat_id}/read-all")
async def mark_all_messages_as_read(
    chat_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Mark all incoming messages in chat as read"""
    try:
        user_id = str(current_user["_id"])
        message_service = MessageService(db)
        
        # Only mark messages as read where current user is NOT the sender
        count = await message_service.mark_incoming_messages_as_read(chat_id, user_id)
        
        return {"message": f"Marked {count} incoming messages as read"}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to mark messages as read: {str(e)}"
        )
@router.delete('/messages/{message_id}/delete_soft')
async def delelete_message(message_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database)):
    try:
        user_id = str(current_user["_id"])
        message_service = MessageService(db)
        success = await message_service.delete_message(message_id,user_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found or access denied"
            )
    
        return {"message": "Message  deleted "}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete message {str(e)}"
        )


@router.delete('/messages/{message_id}/delete_permanent')
async def delelete_message_permanent(message_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database)):
    try:
        user_id = str(current_user["_id"])
        message_service = MessageService(db)
        success = await message_service.delete_message_permanently(message_id,user_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found or access denied"
            )
        
        return {"message": "Message  deleted permanently"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete message {str(e)}"
        )

class BulkDeleteRequest(BaseModel):
    message_ids: List[str]

@router.delete("/messages/bulk", response_model=Dict[str, Any])  # Better path
async def delete_multiple_messages(
    request: BulkDeleteRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database)  # Add type hint
):
    """Delete multiple messages by their IDs"""
    try:
        user_id = str(current_user["_id"])  # Consistent with other routes
        message_service = MessageService(db)
        results = await message_service.delete_multiple_messages(
            request.message_ids, 
            user_id
        )
        
        return {
            "message": f"Bulk delete completed: {results['total_deleted']} deleted, {results['total_failed']} failed",
            "results": results
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during bulk delete"
        )
    

@router.delete("/messages/bulk/permanently", response_model=Dict[str, Any])  # Better path
async def delete_multiple_messages(
    request: BulkDeleteRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database)  
):
    """Delete multiple messages by their IDs"""
    try:
        user_id = str(current_user["_id"])  # Consistent with other routes
        message_service = MessageService(db)
        results = await message_service.delete_multiple_messages_permanently(
            request.message_ids, 
            user_id
        )
        
        return {
            "message": f"Bulk delete permanent completed: {results['total_deleted']} deleted, {results['total_failed']} failed",
            "results": results
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during bulk delete permanent"
        )