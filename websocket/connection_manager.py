import json
import logging
from typing import Dict, Set, List
from fastapi import WebSocket
from datetime import datetime

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        # user_id -> WebSocket connection
        self.active_connections: Dict[str, WebSocket] = {}
        # chat_id -> set of user_ids
        self.chat_participants: Dict[str, Set[str]] = {}
        # user_id -> set of chat_ids user has joined
        self.user_chats: Dict[str, Set[str]] = {}
        # chat_id -> set of user_ids currently typing
        self.typing_status: Dict[str, Set[str]] = {}
        # user_id -> {chat_id: timestamp} for typing expiration
        self.typing_timestamps: Dict[str, Dict[str, datetime]] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        """Accept WebSocket connection and store it"""
        try:
            await websocket.accept()
            self.active_connections[user_id] = websocket
            logger.info(f"User {user_id} connected via WebSocket")
        except Exception as e:
            logger.error(f"Error accepting WebSocket connection for user {user_id}: {e}")
            raise

    def disconnect(self, user_id: str):
        """Remove connection and clean up user data"""
        try:
            # Remove WebSocket connection
            if user_id in self.active_connections:
                del self.active_connections[user_id]
            
            # Remove user from all chat participants
            user_chats = self.user_chats.get(user_id, set()).copy()
            for chat_id in user_chats:
                self.leave_chat(user_id, chat_id)
            
            # Clean up typing status
            if user_id in self.typing_timestamps:
                # Remove from all typing_status sets
                for chat_id, timestamp_dict in self.typing_timestamps[user_id].items():
                    if chat_id in self.typing_status:
                        self.typing_status[chat_id].discard(user_id)
                        if not self.typing_status[chat_id]:
                            del self.typing_status[chat_id]
                
                del self.typing_timestamps[user_id]
            
            logger.info(f"User {user_id} disconnected from WebSocket")
            
        except Exception as e:
            logger.error(f"Error during disconnect cleanup for user {user_id}: {e}")

    async def send_personal_message(self, user_id: str, data: dict):
        """Send message to specific user with error handling"""
        websocket = self.active_connections.get(user_id)
        if not websocket:
            logger.warning(f"No active connection found for user {user_id}")
            return False
        
        try:
            message = json.dumps(data, default=str)
            await websocket.send_text(message)
            return True
        except Exception as e:
            logger.error(f"Error sending message to user {user_id}: {e}")
            # Remove broken connection
            self.disconnect(user_id)
            return False

    async def broadcast_to_chat(self, chat_id: str, data: dict, exclude_user: str = None):
        """Send message to all users in a chat"""
        participants = self.chat_participants.get(chat_id, set()).copy()
        if exclude_user:
            participants.discard(exclude_user)
        
        if not participants:
            logger.debug(f"No participants to broadcast to in chat {chat_id}")
            return
        
        # Track failed sends for cleanup
        disconnected_users = []
        
        for user_id in participants:
            success = await self.send_personal_message(user_id, data)
            if not success:
                disconnected_users.append(user_id)
        
        # Clean up disconnected users
        for user_id in disconnected_users:
            self.leave_chat(user_id, chat_id)
        
        if disconnected_users:
            logger.info(f"Cleaned up {len(disconnected_users)} disconnected users from chat {chat_id}")

    async def broadcast_to_all(self, data: dict, exclude_user: str = None):
        """Send message to all connected users"""
        if not self.active_connections:
            logger.debug("No active connections for broadcast")
            return
        
        disconnected_users = []
        connected_users = list(self.active_connections.keys())
        
        for user_id in connected_users:
            if exclude_user and user_id == exclude_user:
                continue
            
            success = await self.send_personal_message(user_id, data)
            if not success:
                disconnected_users.append(user_id)
        
        if disconnected_users:
            logger.info(f"Cleaned up {len(disconnected_users)} disconnected users during broadcast")

    def join_chat(self, user_id: str, chat_id: str):
        """Add user to chat participants"""
        # Add to chat participants
        if chat_id not in self.chat_participants:
            self.chat_participants[chat_id] = set()
        self.chat_participants[chat_id].add(user_id)
        
        # Track user's chats
        if user_id not in self.user_chats:
            self.user_chats[user_id] = set()
        self.user_chats[user_id].add(chat_id)
        
        logger.info(f"User {user_id} joined chat {chat_id}")

    def leave_chat(self, user_id: str, chat_id: str):
        """Remove user from chat participants"""
        # Remove from chat participants
        if chat_id in self.chat_participants:
            self.chat_participants[chat_id].discard(user_id)
            if not self.chat_participants[chat_id]:
                del self.chat_participants[chat_id]
        
        # Remove from user's chats
        if user_id in self.user_chats:
            self.user_chats[user_id].discard(chat_id)
            if not self.user_chats[user_id]:
                del self.user_chats[user_id]
        
        # Clean up typing status for this chat
        if chat_id in self.typing_status:
            self.typing_status[chat_id].discard(user_id)
            if not self.typing_status[chat_id]:
                del self.typing_status[chat_id]
        
        if user_id in self.typing_timestamps:
            self.typing_timestamps[user_id].pop(chat_id, None)
            if not self.typing_timestamps[user_id]:
                del self.typing_timestamps[user_id]
        
        logger.info(f"User {user_id} left chat {chat_id}")

    def set_typing_status(self, user_id: str, chat_id: str, is_typing: bool):
        """Update user typing status with timestamp tracking"""
        try:
            if is_typing:
                # Add to typing status
                if chat_id not in self.typing_status:
                    self.typing_status[chat_id] = set()
                self.typing_status[chat_id].add(user_id)
                
                # Track timestamp
                if user_id not in self.typing_timestamps:
                    self.typing_timestamps[user_id] = {}
                self.typing_timestamps[user_id][chat_id] = datetime.utcnow()
                
            else:
                # Remove from typing status
                if chat_id in self.typing_status:
                    self.typing_status[chat_id].discard(user_id)
                    if not self.typing_status[chat_id]:
                        del self.typing_status[chat_id]
                
                # Remove timestamp
                if user_id in self.typing_timestamps:
                    self.typing_timestamps[user_id].pop(chat_id, None)
                    if not self.typing_timestamps[user_id]:
                        del self.typing_timestamps[user_id]
                        
        except Exception as e:
            logger.error(f"Error setting typing status for user {user_id} in chat {chat_id}: {e}")

    def get_typing_users(self, chat_id: str, expiry_seconds: int = 5) -> List[str]:
        """Get users currently typing in a chat (with expiration check)"""
        if chat_id not in self.typing_status:
            return []
        
        current_time = datetime.utcnow()
        active_typing_users = []
        expired_users = []
        
        for user_id in self.typing_status[chat_id].copy():
            if (user_id in self.typing_timestamps and 
                chat_id in self.typing_timestamps[user_id]):
                
                time_diff = current_time - self.typing_timestamps[user_id][chat_id]
                if time_diff.total_seconds() <= expiry_seconds:
                    active_typing_users.append(user_id)
                else:
                    expired_users.append(user_id)
        
        # Clean up expired typing status
        for user_id in expired_users:
            self.set_typing_status(user_id, chat_id, False)
        
        return active_typing_users

    def get_chat_participants(self, chat_id: str) -> Set[str]:
        """Get all participants in a chat"""
        return self.chat_participants.get(chat_id, set()).copy()

    def get_user_chats(self, user_id: str) -> Set[str]:
        """Get all chats a user has joined"""
        return self.user_chats.get(user_id, set()).copy()

    def is_user_online(self, user_id: str) -> bool:
        """Check if user is connected"""
        return user_id in self.active_connections

    def get_online_users(self) -> List[str]:
        """Get list of all online users"""
        return list(self.active_connections.keys())

    def get_online_users_in_chat(self, chat_id: str) -> List[str]:
        """Get list of online users in a specific chat"""
        participants = self.get_chat_participants(chat_id)
        return [user_id for user_id in participants if self.is_user_online(user_id)]

    async def cleanup_stale_connections(self):
        """Periodically clean up stale connections and expired typing status"""
        try:
            # Check for stale WebSocket connections
            stale_users = []
            for user_id, websocket in self.active_connections.items():
                try:
                    # Try to ping the connection (this is a simple check)
                    if websocket.client_state.DISCONNECTED:
                        stale_users.append(user_id)
                except Exception:
                    stale_users.append(user_id)
            
            # Clean up stale connections
            for user_id in stale_users:
                logger.info(f"Cleaning up stale connection for user {user_id}")
                self.disconnect(user_id)
            
            # Clean up expired typing status
            current_time = datetime.utcnow()
            for user_id, chat_timestamps in list(self.typing_timestamps.items()):
                for chat_id, timestamp in list(chat_timestamps.items()):
                    if (current_time - timestamp).total_seconds() > 10:  # 10 second expiry
                        self.set_typing_status(user_id, chat_id, False)
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    def get_connection_stats(self) -> dict:
        """Get connection statistics"""
        return {
            "total_connections": len(self.active_connections),
            "total_chats": len(self.chat_participants),
            "total_typing_users": sum(len(users) for users in self.typing_status.values()),
            "active_chats": [
                {
                    "chat_id": chat_id,
                    "participant_count": len(participants),
                    "online_count": len([u for u in participants if self.is_user_online(u)])
                }
                for chat_id, participants in self.chat_participants.items()
            ]
        }

# Global connection manager instance
manager = ConnectionManager()



# from fastapi import WebSocket
# from typing import Dict, List, Set
# import json
# import asyncio
# from datetime import datetime
# import logging

# logger = logging.getLogger(__name__)

# class ConnectionManager:
#     def __init__(self):
#         # user_id -> WebSocket connection
#         self.active_connections: Dict[str, WebSocket] = {}
#         # chat_id -> set of user_ids
#         self.chat_participants: Dict[str, Set[str]] = {}
#         # user_id -> set of chat_ids user has joined
#         self.user_chats: Dict[str, Set[str]] = {}
#         # user_id -> typing status {chat_id: timestamp}
#         self.typing_status: Dict[str, Dict[str, datetime]] = {}

#     async def connect(self, websocket: WebSocket, user_id: str):
#         """Accept WebSocket connection and store it"""
#         await websocket.accept()
#         self.active_connections[user_id] = websocket
#         logger.info(f"User {user_id} connected via WebSocket")

#     def disconnect(self, user_id: str):
#         """Remove connection and clean up user data"""
#         if user_id in self.active_connections:
#             del self.active_connections[user_id]
        
#         # Remove user from all chat participants
#         user_chats = self.user_chats.get(user_id, set()).copy()
#         for chat_id in user_chats:
#             self.leave_chat(user_id, chat_id)
        
#         # Clean up typing status
#         if user_id in self.typing_status:
#             del self.typing_status[user_id]
        
#         logger.info(f"User {user_id} disconnected from WebSocket")

#     async def send_personal_message(self, user_id: str, message: dict):
#         """Send message to specific user"""
#         if user_id in self.active_connections:
#             try:
#                 websocket = self.active_connections[user_id]
#                 await websocket.send_text(json.dumps(message, default=str))
#                 return True
#             except Exception as e:
#                 logger.error(f"Error sending message to user {user_id}: {e}")
#                 # Remove broken connection
#                 self.disconnect(user_id)
#                 return False
#         return False

#     async def broadcast_to_chat(self, chat_id: str, message: dict, exclude_user: str = None):
#         """Send message to all users in a chat"""
#         if chat_id in self.chat_participants:
#             participants = self.chat_participants[chat_id].copy()
#             if exclude_user:
#                 participants.discard(exclude_user)
            
#             # Send to all participants
#             disconnected_users = []
#             for user_id in participants:
#                 success = await self.send_personal_message(user_id, message)
#                 if not success:
#                     disconnected_users.append(user_id)
            
#             # Clean up disconnected users
#             for user_id in disconnected_users:
#                 self.leave_chat(user_id, chat_id)

#     async def broadcast_to_all(self, message: dict, exclude_user: str = None):
#         """Send message to all connected users"""
#         disconnected_users = []
#         for user_id in list(self.active_connections.keys()):
#             if exclude_user and user_id == exclude_user:
#                 continue
#             success = await self.send_personal_message(user_id, message)
#             if not success:
#                 disconnected_users.append(user_id)

#     def join_chat(self, user_id: str, chat_id: str):
#         """Add user to chat participants"""
#         if chat_id not in self.chat_participants:
#             self.chat_participants[chat_id] = set()
#         self.chat_participants[chat_id].add(user_id)
        
#         if user_id not in self.user_chats:
#             self.user_chats[user_id] = set()
#         self.user_chats[user_id].add(chat_id)
        
#         logger.info(f"User {user_id} joined chat {chat_id}")

#     def leave_chat(self, user_id: str, chat_id: str):
#         """Remove user from chat participants"""
#         if chat_id in self.chat_participants:
#             self.chat_participants[chat_id].discard(user_id)
#             if not self.chat_participants[chat_id]:
#                 del self.chat_participants[chat_id]
        
#         if user_id in self.user_chats:
#             self.user_chats[user_id].discard(chat_id)
#             if not self.user_chats[user_id]:
#                 del self.user_chats[user_id]
        
#         logger.info(f"User {user_id} left chat {chat_id}")

#     def get_chat_participants(self, chat_id: str) -> Set[str]:
#         """Get all participants in a chat"""
#         return self.chat_participants.get(chat_id, set()).copy()

#     def is_user_online(self, user_id: str) -> bool:
#         """Check if user is connected"""
#         return user_id in self.active_connections

#     def get_online_users(self) -> List[str]:
#         """Get list of all online users"""
#         return list(self.active_connections.keys())

#     def set_typing_status(self, user_id: str, chat_id: str, is_typing: bool):
#         """Update user typing status"""
#         if user_id not in self.typing_status:
#             self.typing_status[user_id] = {}
        
#         if is_typing:
#             self.typing_status[user_id][chat_id] = datetime.utcnow()
#         else:
#             self.typing_status[user_id].pop(chat_id, None)
#             if not self.typing_status[user_id]:
#                 del self.typing_status[user_id]

#     def get_typing_users(self, chat_id: str) -> List[str]:
#         """Get users currently typing in a chat"""
#         typing_users = []
#         current_time = datetime.utcnow()
        
#         for user_id, chats in self.typing_status.items():
#             if chat_id in chats:
#                 # Consider typing status expired after 3 seconds
#                 if (current_time - chats[chat_id]).seconds <= 3:
#                     typing_users.append(user_id)
        
#         return typing_users

# # Global connection manager instance
# manager = ConnectionManager()
