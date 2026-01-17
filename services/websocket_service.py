from __future__ import annotations
import logging
from datetime import datetime
from typing import Dict, Optional, Tuple
from motor.motor_asyncio import AsyncIOMotorDatabase

# from auth.dependencies import verify_token
from models.message_model import MessageCreate
from services.chat_service import ChatService
from services.message_service import MessageService
from services.user_service import UserService
from websocket.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

class WebSocketService:
    """
    High-level wrapper that connects WebSocket events to
    user/chat/message business logic and the ConnectionManager.
    Enhanced with token-based authentication without URL user_id.
    """

    def __init__(
        self,
        database: AsyncIOMotorDatabase,
        connection_manager: ConnectionManager,
    ) -> None:
        self.db = database
        self.manager = connection_manager
        self.user_service = UserService(database)
        self.chat_service = ChatService(database)
        self.message_service = MessageService(database)

    # --------------------------------------------------------------------- #
    #  Authentication helpers - Updated to extract user_id from token
    # --------------------------------------------------------------------- #

    async def authenticate_websocket_connection(self, token: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Authenticate WebSocket connection using verify_token function.
        Extracts user_id from JWT token payload and validates user existence.
        Returns (is_authenticated, user_id, error_message)
        """
        try:
            if not token:
                return False, None, "Token is required for WebSocket connection"

            # Extract user_id from token payload - FIXED: Remove await
            token_payload = verify_token(token)
            if not token_payload:
                return False, None, "Invalid or expired token"

            user_id = token_payload.get("sub")
            if not user_id:
                return False, None, "Invalid token: missing user ID"

            # Verify user exists and is active in database
            user = await self.user_service.get_user_by_id(user_id)
            if not user:
                return False, None, "User not found"

            # Check if user is active/not banned
            if hasattr(user, 'is_active') and not user.is_active:
                return False, None, "User account is deactivated"

            return True, user_id, None

        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return False, None, "Authentication service error"

    async def authenticate_user(self, token: str) -> Optional[str]:
        """
        Return user_id if token is valid using verify_token; otherwise None.
        """
        try:
            # FIXED: Remove await
            token_payload = verify_token(token)
            if not token_payload:
                return None

            user_id = token_payload.get("sub")
            if not user_id:
                return None

            # Verify user exists
            user = await self.user_service.get_user_by_id(user_id)
            return user_id if user else None

        except Exception as e:
            logger.error(f"Token authentication error: {e}")
            return None

    async def refresh_user_session(self, user_id: str, token: str) -> bool:
        """
        Refresh user session and update last active timestamp using verify_token.
        Called periodically to maintain active connection status.
        """
        try:
            # FIXED: Remove await - Validate token using verify_token
            token_payload = verify_token(token)
            if not token_payload:
                return False

            # Verify user_id matches token
            if token_payload.get("sub") != user_id:
                return False

            # Update user's last active timestamp
            await self.user_service.update_last_active(user_id, datetime.utcnow())
            return True

        except Exception as e:
            logger.error(f"Error refreshing session for user {user_id}: {e}")
            return False

    async def validate_user_permissions(self, token: str, required_permissions: list = None) -> tuple[bool, dict]:
        """
        Validate user permissions from token payload.
        Returns (has_permissions, user_info)
        """
        try:
            # FIXED: Remove await
            token_payload = verify_token(token)
            if not token_payload:
                return False, {}

            user_permissions = token_payload.get("permissions", [])
            user_role = token_payload.get("role", "user")

            # Check if user has required permissions
            if required_permissions:
                has_permissions = all(perm in user_permissions for perm in required_permissions)
                if not has_permissions and user_role != "admin":  # Admin bypasses permission checks
                    return False, token_payload

            return True, token_payload

        except Exception as e:
            logger.error(f"Error validating permissions: {e}")
            return False, {}

    # --------------------------------------------------------------------- #
    #  Event handlers - Updated to work without URL user_id
    # --------------------------------------------------------------------- #

    async def handle_connection_established(self, user_id: str, token: str) -> tuple[bool, Optional[str]]:
        """
        Handle initial WebSocket connection establishment with verify_token authentication.
        Returns (success, error_message)
        """
        try:
            # Update user online status
            await self.user_service.update_online_status(user_id, True)
            await self.user_service.update_last_active(user_id, datetime.utcnow())

            # Broadcast user came online
            await self.broadcast_user_status(user_id, True)
            
            logger.info(f"User {user_id} successfully connected via WebSocket with verified token")
            return True, None

        except Exception as e:
            logger.error(f"Error establishing connection for user {user_id}: {e}")
            return False, "Connection establishment failed"

    async def handle_login(self, user_id: str, event_data: Dict) -> None:
        """Handle LOGIN event - Updated to use token-extracted user_id."""
        try:
            token = event_data.get("token")
            if not token:
                await self.send_error(user_id, "Token is required for login")
                return

            # FIXED: Remove await - Re-authenticate with provided token using verify_token
            token_payload = verify_token(token)
            if not token_payload or token_payload.get("sub") != user_id:
                await self.send_error(user_id, "Login failed: Invalid token")
                return

            # Update user status
            await self.user_service.update_user_status(user_id, True)
            await self.user_service.update_last_active(user_id, datetime.utcnow())

            # Get user details for response
            user = await self.user_service.get_user_by_id(user_id)
            
            await self.manager.send_personal_message(
                user_id,
                {
                    "event_name": "SUCCESS",
                    "event_data": {
                        "message": "Login successful",
                        "user_id": user_id,
                        "username": user.username if user else "Unknown",
                        "authenticated": True,
                        "permissions": token_payload.get("permissions", []),
                        "role": token_payload.get("role", "user"),
                    },
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

            await self.broadcast_user_status(user_id, True)
            logger.info("User %s logged in via WebSocket with verified token", user_id)

        except Exception as exc:
            logger.exception("Error in handle_login: %s", exc)
            await self.send_error(user_id, "Login failed")

    async def handle_logout(self, user_id: str) -> None:
        """Handle internal logout/cleanup (called in finally block)."""
        try:
            await self.user_service.update_online_status(user_id, False)
            await self.user_service.update_last_active(user_id, datetime.utcnow())
            await self.broadcast_user_status(user_id, False)
            logger.info("User %s logged out via WebSocket", user_id)
        except Exception as exc:
            logger.exception("Error in handle_logout: %s", exc)

    async def handle_join_chat(self, user_id: str, event_data: Dict) -> None:
        """Handle JOIN_CHAT event."""
        try:
            chat_id = event_data.get("chat_id")
            if not chat_id:
                await self.send_error(user_id, "Chat ID is required")
                return

            # Check token permissions for joining chats
            token = event_data.get("token")
            if token:
                has_permissions, user_info = await self.validate_user_permissions(token, ["join_chats"])
                if not has_permissions:
                    await self.send_error(user_id, "Insufficient permissions to join chat")
                    return

            chat = await self.chat_service.get_chat_by_id(chat_id, user_id)
            if not chat or user_id not in chat.participants:
                await self.send_error(user_id, "You are not a participant in this chat")
                return

            self.manager.join_chat(user_id, chat_id)

            await self.manager.send_personal_message(
                user_id,
                {
                    "event_name": "SUCCESS",
                    "event_data": {
                        "message": f"Joined chat {chat_id}",
                        "chat_id": chat_id,
                    },
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )
            logger.info("User %s joined chat %s", user_id, chat_id)

        except Exception as exc:
            logger.exception("Error in handle_join_chat: %s", exc)
            await self.send_error(user_id, "Failed to join chat")

    async def handle_send_message(self, user_id: str, event_data: Dict) -> None:
        """Handle SEND_MESSAGE event."""
        try:
            chat_id = event_data.get("chat_id")
            if not chat_id:
                await self.send_error(user_id, "Chat ID is required")
                return

            # Check token permissions for sending messages
            token = event_data.get("token")
            if token:
                has_permissions, user_info = await self.validate_user_permissions(token, ["send_messages"])
                if not has_permissions:
                    await self.send_error(user_id, "Insufficient permissions to send messages")
                    return

            chat = await self.chat_service.get_chat_by_id(chat_id, user_id)
            if not chat or user_id not in chat.participants:
                await self.send_error(user_id, "You are not a participant in this chat")
                return

            message = await self.message_service.create_message(
                user_id,
                MessageCreate(
                    chat_id=chat_id,
                    content=event_data.get("content"),
                    message_type=event_data.get("message_type", "text"),
                    media_info=event_data.get("media_info"),
                    reply_to=event_data.get("reply_to"),
                ),
            )

            await self.chat_service.update_last_message(chat_id, str(message.id))

            await self.manager.broadcast_to_chat(
                chat_id,
                {
                    "event_name": "MESSAGE_RECEIVED",
                    "event_data": {
                        "message_id": str(message.id),
                        "chat_id": message.chat_id,
                        "sender_id": message.sender_id,
                        "content": message.content,
                        "message_type": message.message_type,
                        "media_info": message.media_info,
                        "reply_to": message.reply_to,
                        "created_at": message.created_at.isoformat(),
                    },
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )
            logger.info("User %s sent message to chat %s", user_id, chat_id)

        except Exception as exc:
            logger.exception("Error in handle_send_message: %s", exc)
            await self.send_error(user_id, "Failed to send message")

    async def handle_leave_chat(self, user_id: str, event_data: Dict) -> None:
        """Handle LEAVE_CHAT event."""
        try:
            chat_id = event_data.get("chat_id")
            if not chat_id:
                await self.send_error(user_id, "Chat ID is required")
                return

            self.manager.leave_chat(user_id, chat_id)

            await self.manager.send_personal_message(
                user_id,
                {
                    "event_name": "SUCCESS",
                    "event_data": {
                        "message": f"Left chat {chat_id}",
                        "chat_id": chat_id,
                    },
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )
            logger.info("User %s left chat %s", user_id, chat_id)

        except Exception as exc:
            logger.exception("Error in handle_leave_chat: %s", exc)

    async def handle_typing_start(self, user_id: str, event_data: Dict) -> None:
        """Handle TYPING_START event."""
        try:
            chat_id = event_data.get("chat_id")
            if not chat_id:
                return

            self.manager.set_typing_status(user_id, chat_id, True)

            user = await self.user_service.get_user_by_id(user_id)
            if not user:
                return

            await self.manager.broadcast_to_chat(
                chat_id,
                {
                    "event_name": "USER_TYPING",
                    "event_data": {
                        "chat_id": chat_id,
                        "user_id": user_id,
                        "username": user.username,
                    },
                    "timestamp": datetime.utcnow().isoformat(),
                },
                exclude_user=user_id,
            )
        except Exception as exc:
            logger.exception("Error in handle_typing_start: %s", exc)

    async def handle_typing_stop(self, user_id: str, event_data: Dict) -> None:
        """Handle TYPING_STOP event."""
        try:
            chat_id = event_data.get("chat_id")
            if chat_id:
                self.manager.set_typing_status(user_id, chat_id, False)
        except Exception as exc:
            logger.exception("Error in handle_typing_stop: %s", exc)

    async def handle_message_read(self, user_id: str, event_data: Dict) -> None:
        """Handle MESSAGE_READ event."""
        try:
            message_id = event_data.get("message_id")
            if not message_id:
                await self.send_error(user_id, "Message ID is required")
                return

            if not await self.message_service.mark_message_read(message_id, user_id):
                await self.send_error(user_id, "Failed to mark message as read")
                return

            message = await self.message_service.get_message_by_id(message_id)
            if message:
                await self.manager.send_personal_message(
                    message.sender_id,
                    {
                        "event_name": "MESSAGE_READ",
                        "event_data": {
                            "message_id": message_id,
                            "reader_id": user_id,
                            "chat_id": message.chat_id,
                        },
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                )
        except Exception as exc:
            logger.exception("Error in handle_message_read: %s", exc)

    # --------------------------------------------------------------------- #
    #  Helper utilities
    # --------------------------------------------------------------------- #

    async def send_error(
        self,
        user_id: str,
        message: str,
        code: str | None = None,
    ) -> None:
        """Send standardized error format to one user."""
        await self.manager.send_personal_message(
            user_id,
            {
                "event_name": "ERROR",
                "event_data": {
                    "message": message,
                    "code": code,
                },
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    async def broadcast_user_status(self, user_id: str, is_online: bool) -> None:
        """
        Broadcast user's online/offline status to everyone who shares a chat
        with them.
        """
        try:
            user = await self.user_service.get_user_by_id(user_id)
            if not user:
                return

            chats = await self.chat_service.get_user_chats(user_id)
            recipients: set[str] = {uid for chat in chats if isinstance(chat, dict) and 'participants' in chat for uid in chat['participants']}
            recipients.discard(user_id)

            payload = {
                "event_name": "USER_STATUS_UPDATE",
                "event_data": {
                    "user_id": user_id,
                    "username": user.username,
                    "is_online": is_online,
                    "last_seen": (
                        user.last_seen.isoformat() if user.last_seen else None
                    ),
                },
                "timestamp": datetime.utcnow().isoformat(),
            }

            for rid in recipients:
                await self.manager.send_personal_message(rid, payload)

        except Exception as exc:
            logger.exception("Error broadcasting user status: %s", exc)
