from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId
from datetime import datetime
from typing import List, Optional

from models.chat_model import ChatCreate, ChatResponse
from models.message_model import MessageResponse
from services.user_service import UserService

from bson.errors import InvalidId
import logging

logger = logging.getLogger(__name__)

class ChatService:
    def __init__(self, db):
        self.db = db
        # Initialize indexes on startup
        self._setup_indexes()
    
    def _setup_indexes(self):
        """Setup database indexes asynchronously"""
        try:
            # These will be created if they don't exist
            pass
        except Exception as e:
            logger.error(f"Index setup error: {e}")

    async def create_chat(self, chat_data: ChatCreate, current_user_id: str) -> dict:
        """Create a new chat"""
        participants = chat_data.participants.copy()
        
        # Add current user if not in participants
        if current_user_id not in participants:
            participants.append(current_user_id)
        
        # For 1-on-1 chats, check if chat already exists
        if not chat_data.is_group and len(participants) == 2:
            existing_chat = await self.db.chats.find_one({
                "participants": {"$all": participants},
                "is_group": False
            })
            
            if existing_chat:
                return await self._format_chat_response(existing_chat, current_user_id)
        
        # Create new chat
        chat_doc = {
            "name": chat_data.name or "",
            "participants": participants,
            "is_group": chat_data.is_group,
            "created_at": datetime.utcnow()
        }
        
        result = await self.db.chats.insert_one(chat_doc)
        created_chat = await self.db.chats.find_one({"_id": result.inserted_id})
        
        return await self._format_chat_response(created_chat, current_user_id)

    async def get_user_chats(self, user_id: str) -> List[dict]:
        """
        Retrieve all chat conversations for a specific user
        """
        try:
            # Validate user_id format
            if not user_id:
                raise ValueError("User ID is required")
            
            # Verify user exists
            user_exists = await self.db.users.find_one({"_id": ObjectId(user_id)})
            if not user_exists:
                logger.warning(f"User not found: {user_id}")
                return []
            
            # Query chats where user is a participant
            cursor = self.db.chats.find({"participants": user_id})
            chats = await cursor.to_list(length=None)
            
            if not chats:
                return []
            
            # Format each chat
            formatted_chats = []
            for chat in chats:
                try:
                    formatted_chat = await self._format_chat_response(chat, user_id)
                    formatted_chats.append(formatted_chat)
                except Exception as e:
                    logger.error(f"Error formatting chat {chat.get('_id')}: {e}")
                    continue
            
            # Sort by last message time
            formatted_chats.sort(
                key=lambda x: datetime.fromisoformat(x["last_message_time"]) if x["last_message_time"] else datetime.min,
                reverse=True
            )
            
            return formatted_chats
            
        except Exception as e:
            logger.error(f"Error in get_user_chats: {e}")
            raise

    async def get_chat_by_id(self, chat_id: str, user_id: str) -> Optional[dict]:
        """Get specific chat by ID"""
        try:
            chat_object_id = ObjectId(chat_id)
            chat = await self.db.chats.find_one({"_id": chat_object_id})
            
            if not chat or user_id not in chat.get("participants", []):
                return None
            
            # Mark messages as read when chat is opened
            await self.mark_messages_as_read(chat_id, user_id)
            
            return await self._format_chat_response(chat, user_id)
            
        except InvalidId:
            logger.error(f"Invalid chat ID format: {chat_id}")
            return None
        except Exception as e:
            logger.error(f"Error getting chat by ID: {e}")
            return None

    async def mark_messages_as_read(self, chat_id: str, user_id: str) -> int:
        """Mark all unread messages as read"""
        try:
            result = await self.db.messages.update_many(
                {
                    "chat_id": chat_id,
                    "receiver_id": user_id,
                    "status": {"$in": ["sent", "delivered"]},
                    "is_deleted": False
                },
                {
                    "$set": {
                        "status": "read",
                        "read_at": datetime.utcnow()
                    }
                }
            )
            return result.modified_count
        except Exception as e:
            logger.error(f"Error marking messages as read: {e}")
            return 0

    async def get_unread_count_for_chat(self, chat_id: str, user_id: str) -> int:
        """Get unread message count for a chat"""
        try:
            pipeline = [
                {
                    "$match": {
                        "chat_id": chat_id,
                        "receiver_id": user_id,
                        "status": {"$ne": "read"},
                        "is_deleted": False
                    }
                },
                {"$count": "unread_count"}
            ]
            
            result = await self.db.messages.aggregate(pipeline).to_list(1)
            return result[0]["unread_count"] if result else 0
            
        except Exception as e:
            logger.error(f"Error getting unread count: {e}")
            return 0

    async def _format_chat_response(self, chat: dict, current_user_id: str) -> dict:
        """Format chat for API response"""
        try:
            chat_id = str(chat["_id"])
            
            # Get last message
            last_message = await self.db.messages.find_one(
                {"chat_id": chat_id, "is_deleted": False},
                sort=[("timestamp", -1)]
            )
            
            # Get other user info for direct messages
            other_user = None
            chat_name = chat.get("name", "")
            
            if not chat.get("is_group", False):
                other_user_id = None
                for participant_id in chat.get("participants", []):
                    if participant_id != current_user_id:
                        other_user_id = participant_id
                        break
                
                if other_user_id:
                    try:
                        other_user_doc = await self.db.users.find_one({"_id": ObjectId(other_user_id)})
                        if other_user_doc:
                            other_user = {
                                "id": str(other_user_doc["_id"]),
                                "username": other_user_doc.get("username", "Unknown"),
                                "email": other_user_doc.get("email", ""),
                                "avatar_url": other_user_doc.get("avatar_url")
                            }
                            chat_name = other_user_doc.get("username", "Unknown User")
                    except Exception as e:
                        logger.warning(f"Could not fetch other user: {e}")
                        chat_name = "Unknown User"
            
            # Get unread count
            unread_count = await self.get_unread_count_for_chat(chat_id, current_user_id)
            
            # Build response
            chat_data = {
                "id": chat_id,
                "name": chat_name or "Unnamed Chat",
                "participants": chat.get("participants", []),
                "is_group": chat.get("is_group", False),
                "created_at": chat.get("created_at", datetime.utcnow()),
                "unread_count": unread_count,
                "other_user": other_user
            }
            
            # Add last message if exists
            if last_message:
                chat_data["last_message"] = {
                    "id": str(last_message["_id"]),
                    "sender_id": last_message.get("sender_id"),
                    "receiver_id": last_message.get("receiver_id"),
                    "content": last_message.get("content", ""),
                    "media_url": last_message.get("media_url"),
                    "message_type": last_message.get("message_type", "text"),
                    "caption": last_message.get("caption"),
                    "timestamp": last_message.get("timestamp", datetime.utcnow()),
                    "status": last_message.get("status", "sent"),
                    "is_uploading": False
                }
                chat_data["last_message_time"] = last_message["timestamp"].isoformat()
            else:
                chat_data["last_message"] = None
                chat_data["last_message_time"] = None
            
            return chat_data
            
        except Exception as e:
            logger.error(f"Error formatting chat response: {e}")
            raise

    async def create_indexes(self):
        """Create database indexes for optimal performance"""
        try:
            # Unread messages index
            await self.db.messages.create_index([
                ("chat_id", 1),
                ("receiver_id", 1),
                ("status", 1),
                ("is_deleted", 1)
            ], background=True)
            
            # Last message index
            await self.db.messages.create_index([
                ("chat_id", 1),
                ("timestamp", -1),
                ("is_deleted", 1)
            ], background=True)
            
            # Chat participants index
            await self.db.chats.create_index([
                ("participants", 1)
            ], background=True)
            
            logger.info("Database indexes created successfully")
            
        except Exception as e:
            logger.error(f"Error creating indexes: {e}")



# class ChatService:
#     def __init__(self, db: AsyncIOMotorDatabase):
#         self.db = db
#         self.user_service = UserService(db)

#     async def create_chat(self, chat_data: ChatCreate, current_user_id: str) -> dict:
#         """Create a new chat"""
#         participants = chat_data.participants.copy()
        
#         # Add current user if not in participants
#         if current_user_id not in participants:
#             participants.append(current_user_id)
        
#         # For 1-on-1 chats, check if chat already exists
#         if not chat_data.is_group and len(participants) == 2:
#             existing_chat = await self.db.chats.find_one({
#                 "participants": {"$all": participants},
#                 "is_group": False
#             })
            
#             if existing_chat:
#                 return await self._format_chat_response(existing_chat, current_user_id)
        
#         # Create new chat
#         chat_doc = {
#             "name": chat_data.name or "",
#             "participants": participants,
#             "is_group": chat_data.is_group,
#             "created_at": datetime.utcnow()
#         }
        
#         result = await self.db.chats.insert_one(chat_doc)
#         created_chat = await self.db.chats.find_one({"_id": result.inserted_id})
        
#         return await self._format_chat_response(created_chat, current_user_id)

#     async def get_user_chats(self, user_id: str) -> List[dict]:
#         """Get all chats for a user"""
#         cursor = self.db.chats.find({"participants": user_id})
#         chats = await cursor.to_list(length=None)
        
#         formatted_chats = []
#         for chat in chats:
#             formatted_chat = await self._format_chat_response(chat, user_id)
#             formatted_chats.append(formatted_chat)
        
#         # Sort by last message time
#         formatted_chats.sort(
#             key=lambda x: datetime.fromisoformat(x["last_message_time"]) if x["last_message_time"] else datetime.min,
#             reverse=True
#         )
        
#         return formatted_chats

#     async def get_chat_by_id(self, chat_id: str, user_id: str) -> Optional[dict]:
#         """Get specific chat by ID"""
#         chat = await self.db.chats.find_one({"_id": ObjectId(chat_id)})
        
#         if not chat or user_id not in chat["participants"]:
#             return None
        
#         return await self._format_chat_response(chat, user_id)

#     async def _format_chat_response(self, chat: dict, current_user_id: str) -> dict:
#         """Format chat for response"""
#         # Get last message
#         last_message = await self.db.messages.find_one(
#             {"chat_id": str(chat["_id"]), "is_deleted": False},
#             sort=[("timestamp", -1)]
#         )
        
#         # Get other user info for 1-on-1 chats
#         other_user = None
#         chat_name = chat.get("name", "")
        
#         if not chat.get("is_group", False):
#             other_user_id = None
#             for participant_id in chat["participants"]:
#                 if participant_id != current_user_id:
#                     other_user_id = participant_id
#                     break
            
#             if other_user_id:
#                 other_user_doc = await self.db.users.find_one({"_id": ObjectId(other_user_id)})
#                 if other_user_doc:
#                     other_user = self.user_service.format_user_response(other_user_doc).dict()
#                     chat_name = other_user_doc["username"]
        
#         # Count unread messages
#         unread_count = await self.db.messages.count_documents({
#             "chat_id": str(chat["_id"]),
#             "receiver_id": current_user_id,
#             "status": {"$ne": "read"},
#             "is_deleted": False
#         })
        
#         # Format response
#         chat_data = {
#             "id": str(chat["_id"]),
#             "name": chat_name or "Unknown",
#             "participants": chat["participants"],
#             "is_group": chat.get("is_group", False),
#             "created_at": chat.get("created_at", datetime.utcnow()),
#             "unread_count": unread_count,
#             "other_user": other_user
#         }
        
#         # Add last message info
#         if last_message:
#             chat_data["last_message"] = {
#                 "id": str(last_message["_id"]),
#                 "sender_id": last_message["sender_id"],
#                 "receiver_id": last_message["receiver_id"],
#                 "content": last_message["content"],
#                 "media_url": last_message.get("media_url"),
#                 "message_type": last_message.get("media_type"),
#                 "caption": last_message.get("caption"),
#                 "timestamp": last_message["timestamp"],
#                 "status": last_message.get("status", "sent"),
#                 "is_uploading": False
#             }
#             chat_data["last_message_time"] = last_message["timestamp"].isoformat()
#         else:
#             chat_data["last_message"] = None
#             chat_data["last_message_time"] = None
        
#         return chat_data
