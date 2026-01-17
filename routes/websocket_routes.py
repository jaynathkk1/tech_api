from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from websocket.connection_manager import manager
from services.websocket_service import WebSocketService
from database.connection import get_database
from auth.dependencies import verify_token, get_current_user
from datetime import datetime
import json
import logging
import asyncio
from typing import Optional

logger = logging.getLogger(__name__)
router = APIRouter()

SUFFIX = "aabb"

@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="JWT authentication token"),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    WebSocket endpoint for real-time bidirectional communication with token-based authentication.
    Authentication via query parameter instead of Bearer token header.
    User ID is extracted from JWT token payload.
    """
    websocket_service = WebSocketService(db, manager)
    
    # Extract user_id from token instead of URL parameter
    try:
        is_authenticated, user_id, error_message = await websocket_service.authenticate_websocket_connection(token)
        if not is_authenticated or not user_id:
            logger.warning(f"Authentication failed: {error_message}")
            await websocket.close(code=4001, reason=f"Authentication failed: {error_message}")
            return
            
        # FIXED: Remove await - Check user permissions for WebSocket access
        token_payload = verify_token(token)
        user_permissions = token_payload.get("permissions", []) if token_payload else []
        user_role = token_payload.get("role", "user") if token_payload else "user"
        
        if "websocket_access" not in user_permissions and user_role != "admin":
            logger.warning(f"User {user_id} lacks WebSocket access permissions")
            await websocket.close(code=4003, reason="Insufficient permissions for WebSocket access")
            return
            
    except Exception as e:
        logger.error(f"Token verification error: {e}")
        await websocket.close(code=4002, reason="Token verification failed")
        return
    
    # Establish WebSocket connection after successful authentication
    await manager.connect(websocket, user_id)
    
    # Handle connection establishment in service layer
    success, conn_error = await websocket_service.handle_connection_established(user_id, token)
    if not success:
        logger.error(f"Connection establishment failed for user {user_id}: {conn_error}")
        await websocket.close(code=4004, reason=f"Connection failed: {conn_error}")
        return
    
    # Send enhanced connection acknowledgment response
    await manager.send_personal_message(user_id, {
        "event_name": "CONNECTION_ACK",
        "event_data": {
            "message": "Connected successfully with token-based authentication",
            "user_id": user_id,
            "authenticated": True,
            "auth_method": "verify_token",
            "permissions": user_permissions,
            "role": user_role,
            "timestamp": datetime.utcnow().isoformat(),
            "server_time": datetime.utcnow().isoformat(),
            "token_expires": token_payload.get("exp") if token_payload else None,
            "session_id": f"ws_{user_id}_{int(datetime.utcnow().timestamp())}"
        },
    })
    
    # Start background task for periodic token validation
    validation_task = asyncio.create_task(
        periodic_token_validation_with_verify_token(websocket_service, user_id, token, websocket)
    )
    
    try:
        while True:
            # Listen for incoming client messages
            raw_data = await websocket.receive_text()
            raw_data = raw_data.strip()
            
            try:
                # Validate and parse incoming event with suffix check
                event_dict, error = parse_event_with_suffix(raw_data)
                
                if error:
                    await websocket_service.send_error(user_id, error["message"], error.get("code"))
                    continue
                
                logger.info(f"Processing event from token-authenticated user {user_id}: {event_dict.get('event_name')}")
                
                # Store token in event data for verify_token validation
                if 'token' not in event_dict.get('event_data', {}):
                    event_dict['event_data']['token'] = token
                
                # Process event and send appropriate responses
                await route_websocket_event_with_response(websocket_service, user_id, event_dict)
                
            except Exception as e:
                logger.error(f"Error processing event from user {user_id}: {e}")
                await websocket_service.send_error(user_id, "Error processing event")
                
    except WebSocketDisconnect:
        logger.info(f"Token-authenticated user {user_id} disconnected gracefully")
    except Exception as e:
        logger.error(f"WebSocket connection error for user {user_id}: {e}")
    finally:
        # Cancel background validation task
        validation_task.cancel()
        try:
            await validation_task
        except asyncio.CancelledError:
            pass
        
        # Cleanup: handle logout and disconnect user
        await websocket_service.handle_logout(user_id)
        manager.disconnect(user_id)

# Background task for periodic token validation
async def periodic_token_validation_with_verify_token(
    websocket_service: WebSocketService, 
    user_id: str, 
    token: str, 
    websocket: WebSocket,
    interval_minutes: int = 15
):
    """
    Periodically validate the user's token using verify_token to ensure session is still valid.
    Closes connection if token becomes invalid.
    """
    try:
        while True:
            await asyncio.sleep(interval_minutes * 60)  # Wait for specified interval
            
            try:
                # FIXED: Remove await - Use verify_token for validation
                token_payload = verify_token(token)
                
                if not token_payload or token_payload.get("sub") != user_id:
                    logger.warning(f"Token validation failed for user {user_id}, closing connection")
                    await websocket.close(code=4005, reason="Token expired or invalid")
                    break
                
                # Update user session
                await websocket_service.user_service.update_last_active(user_id, datetime.utcnow())
                logger.debug(f"Token validation successful for user {user_id}")
                
            except Exception as e:
                logger.error(f"Token validation error for user {user_id}: {e}")
                await websocket.close(code=4006, reason="Token validation error")
                break
                
    except asyncio.CancelledError:
        logger.debug(f"Token validation task cancelled for user {user_id}")
    except Exception as e:
        logger.error(f"Error in token validation task for user {user_id}: {e}")

def parse_event_with_suffix(raw: str):
    """Parse and validate incoming WebSocket event with required suffix"""
    if not raw.endswith(SUFFIX):
        return None, {
            "message": "Invalid message format: missing required suffix",
            "code": "INVALID_FORMAT",
            "data": {"received": raw}
        }
    
    try:
        # Remove suffix and parse JSON
        event_dict = json.loads(raw[:-len(SUFFIX)])
        
        # Basic validation
        if not isinstance(event_dict, dict):
            raise ValueError("Event must be a dictionary")
        
        if "event_name" not in event_dict:
            raise ValueError("Missing required field: event_name")
        
        if "event_data" not in event_dict:
            event_dict["event_data"] = {}
        
        return event_dict, None
        
    except json.JSONDecodeError:
        return None, {
            "message": "Invalid JSON format in message",
            "code": "INVALID_JSON",
            "data": {"received": raw}
        }
    except ValueError as e:
        return None, {
            "message": f"Invalid event structure: {str(e)}",
            "code": "INVALID_STRUCTURE",
            "data": {"received": raw}
        }
    except Exception as e:
        return None, {
            "message": f"Unexpected error parsing event: {str(e)}",
            "code": "PARSE_ERROR",
            "data": {"received": raw}
        }

async def route_websocket_event_with_response(service: WebSocketService, user_id: str, event_dict: dict):
    """Route WebSocket events to handlers and send appropriate responses"""
    
    event_name = event_dict.get("event_name")
    event_data = event_dict.get("event_data", {})
    
    # Event handler mapping with response handling
    event_handlers = {
        "LOGIN": handle_login_with_response,
        "SEND_MESSAGE": handle_send_message_with_response,
        "JOIN_CHAT": handle_join_chat_with_response,
        "LEAVE_CHAT": handle_leave_chat_with_response,
        "TYPING_START": handle_typing_start_with_response,
        "TYPING_STOP": handle_typing_stop_with_response,
        "MESSAGE_READ": handle_message_read_with_response,
    }
    
    handler = event_handlers.get(event_name)
    if handler:
        await handler(service, user_id, event_data)
    else:
        # Send error response for unknown event types
        await service.send_error(user_id, f"Unknown event type: {event_name}", "UNKNOWN_EVENT")

# Event handlers updated to work with token-extracted user_id
async def handle_login_with_response(service: WebSocketService, user_id: str, event_data: dict):
    """Handle user login and send success/failure response with verify_token validation"""
    try:
        # Process login through service (includes verify_token validation)
        await service.handle_login(user_id, event_data)
        
        # FIXED: Remove await - Get token payload using verify_token for enhanced response
        token = event_data.get("token")
        token_payload = verify_token(token) if token else {}
        
        # Get user details for enhanced response
        user = await service.user_service.get_user_by_id(user_id)
        
        # Send enhanced login success response with token details
        await manager.send_personal_message(user_id, {
            "event_name": "LOGIN_SUCCESS",
            "event_data": {
                "user_id": user_id,
                "username": user.username if user else event_data.get("username"),
                "status": "online",
                "authenticated": True,
                "auth_method": "verify_token",
                "permissions": token_payload.get("permissions", []),
                "role": token_payload.get("role", "user"),
                "last_login": datetime.utcnow().isoformat(),
                "session_id": f"session_{user_id}_{int(datetime.utcnow().timestamp())}",
                "device_id": event_data.get("device_id"),
                "token_expires": token_payload.get("exp"),
                "connection_method": "token_based"
            },
            "timestamp": datetime.utcnow().isoformat()
        })
    except Exception as e:
        await service.send_error(user_id, f"Login failed: {str(e)}", "LOGIN_ERROR")

async def handle_send_message_with_response(service: WebSocketService, user_id: str, event_data: dict):
    """Handle message sending with delivery confirmation"""
    try:
        await service.handle_send_message(user_id, event_data)
        
        await manager.send_personal_message(user_id, {
            "event_name": "MESSAGE_SENT",
            "event_data": {
                "chat_id": event_data.get("chat_id"),
                "status": "delivered",
                "timestamp": datetime.utcnow().isoformat(),
                "authenticated_sender": True,
                "auth_method": "verify_token"
            }
        })
        
    except Exception as e:
        await service.send_error(user_id, f"Failed to send message: {str(e)}", "MESSAGE_ERROR")

async def handle_join_chat_with_response(service: WebSocketService, user_id: str, event_data: dict):
    """Handle chat joining with welcome message and participant notification"""
    try:
        await service.handle_join_chat(user_id, event_data)
        
        await manager.send_personal_message(user_id, {
            "event_name": "CHAT_JOINED",
            "event_data": {
                "chat_id": event_data.get("chat_id"),
                "user_id": user_id,
                "role": event_data.get("user_role", "member"),
                "joined_at": datetime.utcnow().isoformat(),
                "authenticated": True,
                "auth_method": "verify_token"
            }
        })
        
        await manager.broadcast_to_chat(event_data.get("chat_id"), {
            "event_name": "USER_JOINED_CHAT",
            "event_data": {
                "chat_id": event_data.get("chat_id"),
                "user_id": user_id,
                "role": event_data.get("user_role", "member"),
                "timestamp": datetime.utcnow().isoformat()
            }
        }, exclude_user=user_id)
        
    except Exception as e:
        await service.send_error(user_id, f"Failed to join chat: {str(e)}", "JOIN_CHAT_ERROR")

async def handle_leave_chat_with_response(service: WebSocketService, user_id: str, event_data: dict):
    """Handle chat leaving with confirmation and participant notification"""
    try:
        await service.handle_leave_chat(user_id, event_data)
        
        await manager.send_personal_message(user_id, {
            "event_name": "CHAT_LEFT",
            "event_data": {
                "chat_id": event_data.get("chat_id"),
                "user_id": user_id,
                "status": "left",
                "timestamp": datetime.utcnow().isoformat()
            }
        })
        
        await manager.broadcast_to_chat(event_data.get("chat_id"), {
            "event_name": "USER_LEFT_CHAT",
            "event_data": {
                "chat_id": event_data.get("chat_id"),
                "user_id": user_id,
                "reason": event_data.get("reason", "user_left"),
                "timestamp": datetime.utcnow().isoformat()
            }
        })
        
    except Exception as e:
        await service.send_error(user_id, f"Failed to leave chat: {str(e)}", "LEAVE_CHAT_ERROR")

async def handle_typing_start_with_response(service: WebSocketService, user_id: str, event_data: dict):
    """Handle typing start indicator with real-time broadcast"""
    try:
        await service.handle_typing_start(user_id, event_data)
    except Exception as e:
        await service.send_error(user_id, f"Failed to update typing status: {str(e)}", "TYPING_ERROR")

async def handle_typing_stop_with_response(service: WebSocketService, user_id: str, event_data: dict):
    """Handle typing stop indicator with real-time broadcast"""
    try:
        await service.handle_typing_stop(user_id, event_data)
        
        await manager.broadcast_to_chat(event_data.get("chat_id"), {
            "event_name": "USER_TYPING_STOP",
            "event_data": {
                "chat_id": event_data.get("chat_id"),
                "user_id": user_id,
                "timestamp": datetime.utcnow().isoformat()
            }
        }, exclude_user=user_id)
        
    except Exception as e:
        await service.send_error(user_id, f"Failed to update typing status: {str(e)}", "TYPING_ERROR")

async def handle_message_read_with_response(service: WebSocketService, user_id: str, event_data: dict):
    """Handle message read receipt with confirmation and sender notification"""
    try:
        await service.handle_message_read(user_id, event_data)
        
        await manager.send_personal_message(user_id, {
            "event_name": "MESSAGE_READ_CONFIRMED",
            "event_data": {
                "message_id": event_data.get("message_id"),
                "chat_id": event_data.get("chat_id"),
                "status": "read",
                "timestamp": datetime.utcnow().isoformat()
            }
        })
        
    except Exception as e:
        await service.send_error(user_id, f"Failed to mark message as read: {str(e)}", "MESSAGE_READ_ERROR")

# REST endpoints with get_current_user dependency (which handles token validation internally)
@router.get("/ws/status")
async def get_websocket_status(current_user=Depends(get_current_user)):
    """Get comprehensive WebSocket connection statistics"""
    return {
        "total_connections": len(manager.active_connections),
        "online_users": manager.get_online_users(),
        "active_chats": len(getattr(manager, 'chat_participants', {})),
        "server_time": datetime.utcnow().isoformat(),
        "uptime_hours": 24.5,
        "authenticated_connections": len(manager.active_connections),
        "auth_method": "verify_token",
        "connection_method": "token_based_no_url_userid",
        "requester": current_user.get("sub") if current_user else "unknown"
    }

@router.get("/ws/chat/{chat_id}/participants")
async def get_chat_participants(chat_id: str, current_user=Depends(get_current_user)):
    """Get real-time list of online participants"""
    participants = manager.get_chat_participants(chat_id)
    return {
        "chat_id": chat_id,
        "participants": list(participants), 
        "participant_count": len(participants),
        "last_updated": datetime.utcnow().isoformat(),
        "all_authenticated": True,
        "auth_method": "verify_token",
        "connection_method": "token_based",
        "requester": current_user.get("sub") if current_user else "unknown"
    }

@router.post("/ws/broadcast/{chat_id}")
async def broadcast_to_chat(chat_id: str, message: dict, current_user=Depends(get_current_user)):
    """Send administrative broadcast message"""
    try:
        # Check admin permissions from verify_token payload
        user_role = current_user.get("role", "user")
        user_permissions = current_user.get("permissions", [])
        
        if user_role != "admin" and "admin_broadcast" not in user_permissions:
            raise HTTPException(status_code=403, detail="Insufficient permissions for admin broadcast")
        
        await manager.broadcast_to_chat(chat_id, {
            "event_name": "ADMIN_BROADCAST",
            "event_data": {
                "chat_id": chat_id,
                "message": message,
                "timestamp": datetime.utcnow().isoformat(),
                "type": "admin",
                "authenticated": True,
                "auth_method": "verify_token",
                "sender": current_user.get("sub")
            }
        })
        return {
            "status": "success", 
            "message": "Broadcast sent", 
            "chat_id": chat_id,
            "sender": current_user.get("sub"),
            "connection_method": "token_based"
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "chat_id": chat_id}
