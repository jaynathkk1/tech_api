from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()                         # reads .env

class Database:
    client: Optional[AsyncIOMotorClient] = None
    database: Optional[AsyncIOMotorDatabase] = None

database = Database()

async def connect_to_mongo() -> None:
    """Create a MongoDB connection using required env vars (no defaults)."""
    mongodb_url  = os.getenv("MONGODB_URL")     # returns None if missing[12]
    database_name = os.getenv("DATABASE_NAME")  # returns None if missing[12]

    if not mongodb_url:
        raise RuntimeError("MONGODB_URL environment variable is required")
    if not database_name:
        raise RuntimeError("DATABASE_NAME environment variable is required")

    database.client = AsyncIOMotorClient(mongodb_url)
    database.database = database.client[database_name]

    await database.client.admin.command("ping")
    print(f"Connected to MongoDB at {mongodb_url} — DB: {database_name}")

async def close_mongo_connection() -> None:
    if database.client:
        database.client.close()
        print("Disconnected from MongoDB")

def get_database() -> AsyncIOMotorDatabase:
    """Get database instance"""
    return database.database
