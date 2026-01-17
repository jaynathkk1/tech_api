from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
from bson import ObjectId
from .user_model import PyObjectId, UserResponse
from .message_model import MessageResponse

class ChatModel(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    name: str
    participants: List[str]
    is_group: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_message_time: Optional[datetime] = None

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

class ChatCreate(BaseModel):
    participants: List[str]
    is_group: bool = False
    name: Optional[str] = None

class ChatResponse(BaseModel):
    id: str
    name: str
    participants: List[str]
    is_group: bool
    created_at: datetime
    last_message_time: Optional[datetime] = None
    last_message: Optional[MessageResponse] = None
    unread_count: int = 0
    other_user: Optional[UserResponse] = None

class ChatsListResponse(BaseModel):
    chats: List[ChatResponse]
