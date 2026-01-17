from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId
from datetime import datetime
from typing import List, Optional
from models.message_model import MessageCreate, MessageResponse

class MessageService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def send_message(self, message_data: MessageCreate, sender_id: str) -> dict:
        # Verify chat exists and sender is a participant
        chat = await self.db.chats.find_one({"_id": ObjectId(message_data.chat_id)})
        if not chat or sender_id not in chat["participants"]:
            raise ValueError("Access denied: Chat not found or user not authorized")
        
        message_doc = {
            "sender_id": sender_id,
            "chat_id": message_data.chat_id,
            "content": message_data.content,
            "message_type": message_data.message_type,
            "media_url": message_data.media_url,
            "caption": message_data.caption,
            "file_size": message_data.file_size,
            "file_name": message_data.file_name,
            "timestamp": message_data.timestamp,
            "status": "sent",
            "is_deleted": False
        }
        
        # Insert message into database
        result = await self.db.messages.insert_one(message_doc)
        
        # Update chat's last message timestamp
        await self.db.chats.update_one(
            {"_id": ObjectId(message_data.chat_id)},
            {"$set": {"last_message_time": message_doc["timestamp"]}}
        )
        
        # Retrieve and return the created message
        created_message = await self.db.messages.find_one({"_id": result.inserted_id})
        return self._format_message_response(created_message)

    async def delete_message(self, message_id: str, user_id: str) -> bool:
        """
        Soft delete a message by marking it as deleted.
        Args:
            message_id: ID of the message to delete
            user_id: ID of the user requesting deletion
        Returns:
            bool: True if message was successfully deleted
        Raises:
            ValueError: If message not found or user lacks permission
        """
        # Find message and verify user is the sender
        message = await self.db.messages.find_one({"_id": ObjectId(message_id)})
        if not message:
            raise ValueError("Message not found")
        
        if message["sender_id"] != user_id:
            raise ValueError("Only message sender can delete the message")
        
        # Soft delete the message
        result = await self.db.messages.update_one(
            {"_id": ObjectId(message_id)},
            {"$set": {"is_deleted": True, "deleted_at": datetime.now()}}
        )
        
        return result.modified_count > 0

    async def delete_message_permanently(self, message_id: str, user_id: str) -> bool:
        """
        Permanently delete a message from the database.
        Args:
            message_id: ID of the message to delete permanently
            user_id: ID of the user requesting deletion
        Returns:
            bool: True if message was successfully deleted permanently
        Raises:
            ValueError: If message not found or user lacks permission
        """
        # Find message and verify user is the sender
        message = await self.db.messages.find_one({"_id": ObjectId(message_id)})
        if not message:
            raise ValueError("Message not found")
        
        if message["sender_id"] != user_id:
            raise ValueError("Only message sender can permanently delete the message")
         
        # Permanently delete the message
        result = await self.db.messages.delete_one({"_id": ObjectId(message_id)})
        
        return result.deleted_count > 0

    async def delete_chat_messages(self, chat_id: str, user_id: str) -> int:
        # Verify chat exists and user is a participant
        chat = await self.db.chats.find_one({"_id": ObjectId(chat_id)})
        if not chat or user_id not in chat["participants"]:
            raise ValueError("Access denied: Chat not found or user not authorized")
        
        # Delete all messages in the chat
        result = await self.db.messages.update_many(
            {"chat_id": chat_id},
            {"$set": {"is_deleted": True, "deleted_at": datetime.utcnow()}}
        )
        return result.modified_count

    def _format_message_response(self, message_doc: dict) -> dict:
        """
        Format message document for API response.
        Args:
            message_doc: Raw message document from database
        Returns:
            dict: Formatted message response
        """
        if not message_doc:
            return {}
        
        return {
            "id": str(message_doc["_id"]),
            "sender_id": message_doc["sender_id"],
            "receiver_id": message_doc.get("receiver_id"),
            "chat_id": message_doc["chat_id"],
            "content": message_doc["content"],
            "message_type": message_doc["message_type"],
            "media_url": message_doc.get("media_url"),
            "caption": message_doc.get("caption"),
            "file_size": message_doc.get("file_size"),
            "file_name": message_doc.get("file_name"),
            "timestamp": message_doc["timestamp"],
            "status": message_doc["status"],
            "is_deleted": message_doc.get("is_deleted", False)
        }

    async def get_chat_messages(self, chat_id: str, user_id: str, page: int, limit: int) -> List[dict]:
        """Get messages for a chat with pagination"""
        # Verify user access
        chat = await self.db.chats.find_one({"_id": ObjectId(chat_id)})
        if not chat or user_id not in chat["participants"]:
            raise ValueError("Access denied")
        # Calculate pagination
        skip = (page - 1) * limit
        # Get messages
        cursor = self.db.messages.find(
            {"chat_id": chat_id, "is_deleted": False}
        ).sort("timestamp", -1).skip(skip).limit(limit)
        
        messages = await cursor.to_list(length=None)
        
        return [self._format_message_response(msg) for msg in messages]
    
    async def get_message_by_id(self, message_id: str):
        try:
            message = await self.db.messages.find_one({"_id": ObjectId(message_id)})
            if message:
                return self._format_message_response(message)
            return None
        except Exception as e:
            raise Exception(f"Error retrieving message: {str(e)}")


    async def mark_message_as_read(self, message_id: str, user_id: str) -> bool:
        """Mark message as read"""
        result = await self.db.messages.update_one(
            {"_id": ObjectId(message_id), "receiver_id": user_id},
            {"$set": {"status": "read"}}
        )
        return result.modified_count > 0

    # In your MessageService class
    async def mark_incoming_messages_as_read(self, chat_id: str, user_id: str) -> int:
        """Mark only incoming messages as read for a specific user in a chat"""
        result = await self.db.messages.update_many(
            {
                "chat_id": chat_id,
                "sender_id": {"$ne": user_id},  # Messages NOT sent by current user
                "read_by": {"$not": {"$elemMatch": {"user_id": user_id}}}  # Not already read
            },
            {
                "$addToSet": {
                    "read_by": {
                        "user_id": user_id,
                        "read_at": datetime.utcnow()
                    }
                }
            }
        )
        return result.modified_count

    async def delete_multiple_messages(self, message_ids: List[str], user_id: str) -> dict:
        results = {
            "success": [],
            "failed": [],
            "total_deleted": 0,
            "total_failed": 0
        }
    
        if not message_ids:
            return results
    
    # Process each message ID
        for message_id in message_ids:
            try:
                # Validate ObjectId format
                if not ObjectId.is_valid(message_id):
                    results["failed"].append({
                        "id": message_id,
                        "reason": "Invalid message ID format"
                    })
                    results["total_failed"] += 1
                    continue
            
                # Find message and verify user is the sender
                message = await self.db.messages.find_one({"_id": ObjectId(message_id)})
            
                if not message:
                    results["failed"].append({
                        "id": message_id,
                        "reason": "Message not found"
                    })
                    results["total_failed"] += 1
                    continue
            
                if message["sender_id"] != user_id:
                    results["failed"].append({
                        "id": message_id,
                        "reason": "Only message sender can delete the message"
                    })
                    results["total_failed"] += 1
                    continue
            
                # Soft delete the message
                update_result = await self.db.messages.update_one(
                    {"_id": ObjectId(message_id)},
                    {"$set": {"is_deleted": True, "deleted_at": datetime.utcnow()}}
                )
            
                if update_result.modified_count > 0:
                    results["success"].append(message_id)
                    results["total_deleted"] += 1
                else:
                    results["failed"].append({
                        "id": message_id,
                        "reason": "Failed to update message in database"
                    })
                    results["total_failed"] += 1
                
            except Exception as e:
                results["failed"].append({
                    "id": message_id,
                    "reason": f"Unexpected error: {str(e)}"
                })
                results["total_failed"] += 1
    
        return results


    async def delete_multiple_messages_permanently(self, message_ids: List[str], user_id: str) -> dict:
        """
        Permanently delete multiple messages in bulk operation.
        Args:
         message_ids: List of message IDs to delete permanently
         user_id: ID of the user requesting deletion
        Returns:
         dict: Summary of deletion results with success/failure details
        """
        results = {
            "success": [],
            "failed": [],
            "total_deleted": 0,
            "total_failed": 0
        }
    
        if not message_ids:
            return results
    
        # Process each message ID
        for message_id in message_ids:
            try:
                # Validate ObjectId format
                if not ObjectId.is_valid(message_id):
                    results["failed"].append({
                      "id": message_id,
                        "reason": "Invalid message ID format"
                    })
                    results["total_failed"] += 1
                    continue
            
                # Find message and verify user is the sender
                message = await self.db.messages.find_one({"_id": ObjectId(message_id)})
            
                if not message:
                    results["failed"].append({
                        "id": message_id,
                        "reason": "Message not found"
                    })
                    results["total_failed"] += 1
                    continue
            
                if message["sender_id"] != user_id:
                    results["failed"].append({
                     "id": message_id,
                        "reason": "Only message sender can delete the message"
                    })
                    results["total_failed"] += 1
                    continue
            
                # Permanently delete the message
                delete_result = await self.db.messages.delete_one({"_id": ObjectId(message_id)})
            
                if delete_result.deleted_count > 0:
                    results["success"].append(message_id)
                    results["total_deleted"] += 1
                else:
                    results["failed"].append({
                     "id": message_id,
                        "reason": "Failed to delete message from database"
                    })
                    results["total_failed"] += 1
                
            except Exception as e:
                results["failed"].append({
                    "id": message_id,
                    "reason": f"Unexpected error: {str(e)}"
                })
                results["total_failed"] += 1
    
        return results



