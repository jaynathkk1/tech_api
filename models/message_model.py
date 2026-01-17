from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from bson import ObjectId
from .user_model import PyObjectId


class MessageModel(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    sender_id: str
    chat_id: str
    content: Optional[str] = None
    media_url: Optional[str] = None
    message_type: str = "text"
    caption: Optional[str] = None
    file_size: Optional[int] = None
    file_name: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    status: str = "sent"
    is_deleted: bool = False

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class MessageCreate(BaseModel):
    chat_id: str
    sender_id: str
    status:str
    message_type: str = Field(default_factory="text")
    content: Optional[str] = None
    media_url: Optional[str] = None
    caption: Optional[str] = None
    file_size: Optional[int] = None
    file_name: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
   


class MessageResponse(BaseModel):
    id: str
    sender_id: str
    content: str
    media_url: Optional[str] = None
    message_type: str = "text"
    caption: Optional[str] = None
    file_size: Optional[int] = None
    file_name: Optional[str] = None
    timestamp: datetime
    status: str 
    is_uploading: bool = False


class MessagesListResponse(BaseModel):
    messages: List[MessageResponse]  # Updated comment: List of message responses


# from datetime import datetime
# from typing import Optional,List
# from pydantic import BaseModel, Field
# from bson import ObjectId
# from .user_model import PyObjectId

# class MessageModel(BaseModel):
#     id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
#     sender_id: str
#     receiver_id: str
#     chat_id: str
#     content: str
#     media_url: Optional[str] = None
#     media_type: Optional[str] = None
#     caption: Optional[str] = None
#     file_size: Optional[int] = None
#     file_name: Optional[str] = None
#     timestamp: datetime = Field(default_factory=datetime.utcnow)
#     status: str = "sent"
#     is_deleted: bool = False

#     class Config:
#         allow_population_by_field_name = True
#         arbitrary_types_allowed = True
#         json_encoders = {ObjectId: str}

# class MessageCreate(BaseModel):
#     chat_id: str
#     receiver_id: str
#     content: str
#     media_url: Optional[str] = None
#     media_type: Optional[str] = None
#     caption: Optional[str] = None
#     file_size: Optional[int] = None
#     file_name: Optional[str] = None

# class MessageResponse(BaseModel):
#     id: str
#     sender_id: str
#     receiver_id: str
#     content: str
#     media_url: Optional[str] = None
#     media_type: Optional[str] = None
#     caption: Optional[str] = None
#     file_size: Optional[int] = None
#     file_name: Optional[str] = None
#     timestamp: datetime
#     status: str = "sent"
#     is_uploading: bool = False

# class MessagesListResponse(BaseModel):
#     messages: List[MessageResponse]
