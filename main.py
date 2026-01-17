from fastapi import FastAPI , WebSocket, status
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn
from routes.websocket_routes import router as websocket_router
from database.connection import connect_to_mongo, close_mongo_connection
from routes.auth_route import router as auth_router
from routes.chat_route import router as chat_router
from routes.message_route import router as message_router
from websocket.websocket import websocket_handler
from auth.dependencies import verify_token

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await connect_to_mongo()
    yield
    # Shutdown
    await close_mongo_connection()

# Create FastAPI app
app = FastAPI(
    title="Chat API",
    version="1.0.0",
    description="A complete chat API with authentication and real-time messaging",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure properly for production
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(message_router)
# websocket_handler(app)
# app.include_router(websocket_router,tags=["WS"])
# app.include_router(websocket_handler)

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Chat API is running",
        "version": "1.0.0",
        "docs": "/docs"
    }

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket_handler(websocket)

# def parse_event(raw: str):
#     if not raw.endswith(SUFFIX):
#         return None, {"status": 400, "message": "Invalid suffix", "data": {"received": raw}}
#     try:
#         event = json.loads(raw[:-len(SUFFIX)])
#         return event, None
#     except json.JSONDecodeError:
#         return None, {"status": 400, "message": "Malformed JSON", "data": {"received": raw}}

# # @app.websocket("/ws")
# # async def websocket_endpoint(websocket: WebSocket):
# #     user_data = await verify_token(websocket)
# #     if not user_data:
# #         await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid authentication")
# #         return
    
# #     await websocket.accept()

# #     try:
# #         while True:
# #             raw_data = await websocket.receive_text()
# #             raw_data = raw_data.strip()

# #             event, error = parse_event(raw_data)
# #             if error:
# #                 await websocket.send_text(json.dumps(error))
# #                 continue
# #             await websocket.send_text(f"Message text was: {data}")
# #     except Exception as e:
# #         print(f"[WebSocket Error] {e}")


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
