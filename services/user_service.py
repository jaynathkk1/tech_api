from passlib.context import CryptContext
from bson import ObjectId
from datetime import datetime
from typing import List, Optional

from models.user_model import UserCreate, UserResponse
from database.connection import get_database

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class UserService:
    def __init__(self, db: get_database):
        self.db = db

    async def create_user(self, user_data: UserCreate) -> dict:
        """Create a new user"""
        # Check if user exists
        existing_user = await self.db.users.find_one({
            "$or": [
                {"email": user_data.email},
                {"username": user_data.username}
            ]
        })
        
        if existing_user:
            raise ValueError("User with this email or username already exists")
        
        # Hash password
        password_hash = pwd_context.hash(user_data.password)
        
        # Create user document
        user_doc = {
            "username": user_data.username,
            "email": user_data.email,
            "password_hash": password_hash,
            "is_online": False,
            "created_at": datetime.utcnow()
        }
        
        # Insert user
        result = await self.db.users.insert_one(user_doc)
        
        # Get created user
        created_user = await self.db.users.find_one({"_id": result.inserted_id})
        return created_user

    async def authenticate_user(self, email: str, password: str) -> Optional[dict]:
        """Authenticate user login"""
        user = await self.db.users.find_one({"email": email})
        
        if not user or not pwd_context.verify(password, user["password_hash"]):
            return None
        
        # Update online status
        await self.db.users.update_one(
            {"_id": user["_id"]},
            {
                "$set": {
                    "is_online": True,
                    "last_seen": datetime.utcnow()
                }
            }
        )
        
        return user

    async def get_all_users_except(self, user_id: str) -> List[dict]:
        """Get all users except specified user"""
        cursor = self.db.users.find(
            {"_id": {"$ne": ObjectId(user_id)}},
            {"password_hash": 0}  # Exclude password
        )
        return await cursor.to_list(length=None)

    async def update_online_status(self, user_id: str, is_online: bool):
        """Update user online status"""
        await self.db.users.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "is_online": is_online,
                    "last_seen": datetime.utcnow()
                }
            }
        )

    async def update_user_status(self, user_id: str, is_online: bool):
        return await self.update_online_status(user_id, is_online)
    @staticmethod
    def format_user_response(user: dict) -> UserResponse:
        """Format user data for response"""
        return UserResponse(
            id=str(user["_id"]),
            username=user["username"],
            email=user["email"],
            avatar_url=user.get("avatar_url"),
            is_online=user.get("is_online", False),
            last_seen=user.get("last_seen")
        )

    async def get_user_by_id(self, user_id: str) -> Optional[dict]:
        return await self.db.users.find_one({"_id": ObjectId(user_id)})