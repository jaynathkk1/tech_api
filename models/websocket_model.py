from pydantic import BaseModel
from enum import Enum
from typing import Dict, Any, Optional

class WebSocketEventType(Enum):
    CONNECTION_ACK = "connection_ack"
    LOGIN = "login"
    SEND_MESSAGE = "send_message"
    SEND_CHAT = "send_chat" 
    SEND_MEDIA = "send_media"
    RECEIVE_MESSAGE = "receive_message"
    RECEIVE_CHAT = "receive_chat"
    JOIN_CHAT = "join_chat"
    LEAVE_CHAT = "leave_chat"
    TYPING_START = "typing_start"
    TYPING_STOP = "typing_stop"
    MESSAGE_READ = "message_read"

class WebSocketEvent(BaseModel):
    event_name: WebSocketEventType
    event_data: Dict[str, Any] = {}


# from pydantic import BaseModel, Field
# from typing import Dict, Any, Optional, Union
# from enum import Enum
# from datetime import datetime

# class WebSocketEventType(str, Enum):
#     # Authentication events
#     LOGIN = "login"
#     LOGOUT = "logout"
    
#     # Chat events
#     JOIN_CHAT = "join_chat"
#     LEAVE_CHAT = "leave_chat"
#     SEND_MESSAGE = "send_message"
#     MESSAGE_RECEIVED = "message_received"
#     MESSAGE_DELIVERED = "message_delivered"
#     MESSAGE_READ = "message_read"
    
#     # Typing events
#     TYPING_START = "typing_start"
#     TYPING_STOP = "typing_stop"
#     USER_TYPING = "user_typing"
    
#     # User status events
#     USER_ONLINE = "user_online"
#     USER_OFFLINE = "user_offline"
#     USER_STATUS_UPDATE = "user_status_update"
    
#     # System events
#     ERROR = "error"
#     SUCCESS = "success"
#     CONNECTION_ACK = "connection_ack"

# class WebSocketEvent(BaseModel):
#     event_name: WebSocketEventType
#     event_data: Dict[str, Any] = Field(default_factory=dict)
#     timestamp: datetime = Field(default_factory=datetime.utcnow)
#     user_id: Optional[str] = None

# class LoginEventData(BaseModel):
#     token: str

# class JoinChatEventData(BaseModel):
#     chat_id: str

# class LeaveChatEventData(BaseModel):
#     chat_id: str

# class SendMessageEventData(BaseModel):
#     chat_id: str
#     content: Optional[str] = None
#     message_type: str = "text"
#     media_info: Optional[Dict[str, Any]] = None
#     reply_to: Optional[str] = None

# class MessageReceivedEventData(BaseModel):
#     message_id: str
#     chat_id: str
#     sender_id: str
#     content: Optional[str] = None
#     message_type: str
#     media_info: Optional[Dict[str, Any]] = None
#     reply_to: Optional[str] = None
#     created_at: datetime

# class TypingEventData(BaseModel):
#     chat_id: str

# class UserTypingEventData(BaseModel):
#     chat_id: str
#     user_id: str
#     username: str

# class UserStatusEventData(BaseModel):
#     user_id: str
#     username: str
#     is_online: bool
#     last_seen: Optional[datetime] = None

# class ErrorEventData(BaseModel):
#     message: str
#     code: Optional[str] = None

# class SuccessEventData(BaseModel):
#     message: str
#     data: Optional[Dict[str, Any]] = None
