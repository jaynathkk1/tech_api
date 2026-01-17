from fastapi import WebSocket, WebSocketDisconnect
from auth.dependencies import verify_token
import json
from datetime import datetime
from typing import Dict, Set
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SUFFIX = "aabb"

# Global connection tracking
connected_clients: Set[WebSocket] = set()
authenticated_users: Dict[WebSocket, str] = {}  # websocket -> user_id
user_connections: Dict[str, WebSocket] = {}     # user_id -> websocket
message_tracking: Dict[str, Dict] = {}
user_last_read_time: Dict[WebSocket, str] = {}



# Typing status tracking for real-time chat
typing_users: Dict[str, Set[str]] = {}          # chat_id -> set of user_ids currently typing
user_typing_in: Dict[str, str] = {}             # user_id -> chat_id they're typing in




def parse_event(raw: str):
    """Parse incoming WebSocket message with suffix validation"""
    if not raw.endswith(SUFFIX):
        return None, {"status": 400, "message": "Invalid suffix", "data": {"received": raw}}
    
    try:
        event = json.loads(raw[:-len(SUFFIX)])
        return event, None
    except json.JSONDecodeError:
        return None, {"status": 400, "message": "Malformed JSON", "data": {"received": raw}}

async def handle_login(websocket: WebSocket, event_data: dict):
    """Handle user authentication"""
    token = event_data.get("token")
    user_id = verify_token(token)
    
    if user_id:
        # Store user connection mappings
        authenticated_users[websocket] = user_id
        user_connections[user_id] = websocket

        response = {
            "status": 200, 
            "event_name": "auth success",
            "message": "Authentication successful", 
            "event_data": {"user_id": user_id}
        }
        await websocket.send_text(json.dumps(response))
        logger.info(f"User {user_id} authenticated successfully")
        print('User {user_id} authenticated successfully')
        return True
    else:
        await websocket.send_text(json.dumps({"status": 403, "message": "Authentication failed"}))
        await websocket.close()
        return False

async def handle_send_chat(websocket: WebSocket, event_data: dict):
    """
    Complete message sending flow:
    1. Validate sender authentication
    2. Create message tracking record
    3. Send 'sent' acknowledgment to sender
    4. Deliver to recipients if online
    5. Send 'delivered' confirmation to sender
    6. Handle auto-read logic
    """
    
    # 1. Authentication check
    if websocket not in authenticated_users:
        await websocket.send_text(json.dumps({"status": 401, "message": "Not authenticated"}))
        return

    sender_id = authenticated_users[websocket]
    message_id = event_data.get("id")
    receiver_id = event_data.get("receiver_id")  # For direct messages
    message_content = event_data.get("message")
    
    if not message_id:
        await websocket.send_text(json.dumps({
            "status": 400,
            "message": "message_id is required"
        }))
        return

    # 2. Create message with timestamp
    message_timestamp = event_data.get("timestamp", datetime.now().isoformat())
    
    message_data = {
        **event_data,
        "from": sender_id,
        "timestamp": message_timestamp,
        "id": message_id
    }

    # 3. Initialize message tracking
    message_tracking[message_id] = {
        "sender_ws": websocket,
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "status": "sent",
        "timestamp": message_timestamp,
        "recipients": set(),
        "delivered_to": set(),
        "read_by": set(),
        "message_data": message_data
    }

    # 4. Send "SENT" acknowledgment to sender
    await websocket.send_text(json.dumps({
        "status": 200,
        "event_name": "message_sent",
        "event_data": {
            "id": message_id,
            "status": "sent",
            "timestamp": message_timestamp,
            "message_data": message_data
        }
    }))

    # 5. Check if receiver is online and deliver message
    if receiver_id:
        # Direct message to specific user
        await deliver_to_user(message_id, receiver_id, message_data)
    else:
        # Broadcast to all connected users (group chat)
        await broadcast_message(websocket, message_id, message_data)



async def deliver_to_user(message_id: str, receiver_id: str, message_data: dict):
    """Deliver message to specific user"""
    message_info = message_tracking[message_id]
    sender_ws = message_info["sender_ws"]
    sender_id = message_info["sender_id"]
    
    if receiver_id in user_connections:
        receiver_ws = user_connections[receiver_id]
        
        try:
            # Send message to receiver
            await receiver_ws.send_text(json.dumps({
                "event_name": "receive_message",
                "event_data": message_data
            }))
            
            # Update tracking
            message_info["recipients"].add(receiver_ws)
            message_info["delivered_to"].add(receiver_ws)
            message_info["status"] = "delivered"
            
            # Notify sender about delivery
            await sender_ws.send_text(json.dumps({
                "event_name": "message_status_update",
                "event_data": {
                    "id": message_id,
                    "receiver_id": receiver_id,
                    "status": "delivered",
                    "delivered_at": datetime.now().isoformat()
                }
            }))
            
            # Check for auto-read
            await auto_check_read_status(receiver_ws, message_id, message_data["timestamp"])
            
        except Exception as e:
            logger.error(f"Error delivering message to {receiver_id}: {e}")
    else:
        # Receiver is offline - message stays as "sent"
        await sender_ws.send_text(json.dumps({
            "event_name": "message_status",
            "event_data": {
                "id": message_id,
                "receiver_id": receiver_id,
                "status": "sent",
                "reason": "user_offline"
            }
        }))

async def broadcast_message(sender_ws: WebSocket, message_id: str, message_data: dict):
    """Broadcast message to all connected users except sender"""
    message_info = message_tracking[message_id]
    recipients_count = 0
    
    for client_ws in connected_clients:
        if client_ws != sender_ws and client_ws in authenticated_users:
            try:
                await client_ws.send_text(json.dumps({
                    "event_name": "receive_message",
                    "event_data": message_data
                }))
                
                message_info["recipients"].add(client_ws)
                recipients_count += 1
                
                # Auto-check read status for each recipient
                await auto_check_read_status(client_ws, message_id, message_data["timestamp"])
                
            except Exception as e:
                logger.error(f"Error broadcasting to client: {e}")
                connected_clients.discard(client_ws)
    
    # Notify sender about broadcast
    if recipients_count > 0:
        message_info["status"] = "delivered"
        await sender_ws.send_text(json.dumps({
            "event_name": "message_broadcast",
            "event_data": {
                "id": message_id,
                "recipients_count": recipients_count,
                "status": "delivered"
            }
        }))

async def auto_check_read_status(recipient_ws: WebSocket, message_id: str, message_timestamp: str):
    """Auto-mark message as read if recipient has recent activity"""
    if recipient_ws not in user_last_read_time or message_id not in message_tracking:
        return
    
    message_info = message_tracking[message_id]
    recipient_id = authenticated_users.get(recipient_ws)
    
    if not recipient_id or recipient_ws in message_info["read_by"]:
        return
    
    try:
        last_read_time = user_last_read_time[recipient_ws]
        message_dt = datetime.fromisoformat(message_timestamp.replace('Z', '+00:00'))
        last_read_dt = datetime.fromisoformat(last_read_time.replace('Z', '+00:00'))
        
        if last_read_dt >= message_dt:
            # Auto-mark as read
            message_info["read_by"].add(recipient_ws)
            
            # Notify sender about read receipt
            sender_ws = message_info["sender_ws"]
            if sender_ws in connected_clients:
                await sender_ws.send_text(json.dumps({
                    "event_name": "message_read",
                    "event_data": {
                        "id": message_id,
                        "reader_id": recipient_id,
                        "read_at": datetime.now().isoformat(),
                        "auto_read": True
                    }
                }))
                
    except Exception as e:
        logger.error(f"Error in auto_check_read_status: {e}")

async def handle_message_read(websocket: WebSocket, event_data: dict):
    """Handle manual message read confirmation"""
    if websocket not in authenticated_users:
        await websocket.send_text(json.dumps({"status": 401, "message": "Not authenticated"}))
        return
    
    message_id = event_data.get("id")
    if not message_id or message_id not in message_tracking:
        await websocket.send_text(json.dumps({
            "status": 404,
            "message": "Message not found"
        }))
        return
    
    message_info = message_tracking[message_id]
    reader_id = authenticated_users[websocket]
    
    # Prevent sender from marking own message as read
    if websocket == message_info["sender_ws"]:
        await websocket.send_text(json.dumps({
            "status": 403,
            "message": "Cannot mark own message as read"
        }))
        return
    
    # Mark as read
    message_info["read_by"].add(websocket)
    read_timestamp = datetime.now().isoformat()
    
    # Confirm to reader
    await websocket.send_text(json.dumps({
        "status": 200,
        "event_name": "read_confirmed",
        "event_data": {
            "id": message_id,
            "read_at": read_timestamp
        }
    }))
    
    # Notify sender
    sender_ws = message_info["sender_ws"]
    if sender_ws in connected_clients:
        await sender_ws.send_text(json.dumps({
            "event_name": "message_read",
            "event_data": {
                "id": message_id,
                "reader_id": reader_id,
                "read_at": read_timestamp,
                "manual_read": True
            }
        }))

async def handle_update_last_read_time(websocket: WebSocket, event_data: dict):
    """Update user's last active/read time"""
    if websocket not in authenticated_users:
        return
    
    last_message_time = event_data.get("last_message_time")
    if last_message_time:
        user_last_read_time[websocket] = last_message_time
        
        # Check all pending messages for auto-read
        await check_all_messages_for_auto_read(websocket, last_message_time)

async def check_all_messages_for_auto_read(websocket: WebSocket, last_read_time: str):
    """Check all tracked messages for auto-read based on last_read_time"""
    reader_id = authenticated_users.get(websocket)
    if not reader_id:
        return
    
    for message_id, message_info in message_tracking.items():
        if (websocket != message_info["sender_ws"] and 
            websocket not in message_info["read_by"] and 
            websocket in message_info["recipients"]):
            
            try:
                message_dt = datetime.fromisoformat(message_info["timestamp"].replace('Z', '+00:00'))
                last_read_dt = datetime.fromisoformat(last_read_time.replace('Z', '+00:00'))
                
                if last_read_dt >= message_dt:
                    message_info["read_by"].add(websocket)
                    
                    # Notify sender
                    sender_ws = message_info["sender_ws"]
                    if sender_ws in connected_clients:
                        await sender_ws.send_text(json.dumps({
                            "event_name": "message_read",
                            "event_data": {
                                "id": message_id,
                                "reader_id": reader_id,
                                "read_at": datetime.now().isoformat(),
                                "auto_read": True
                            }
                        }))
            except Exception as e:
                logger.error(f"Error in bulk auto-read check: {e}")

async def handle_status_check(websocket: WebSocket, event_data: dict):
    """Check if a user is online"""
    if websocket not in authenticated_users:
        return
    
    target_user_id = event_data.get("user_id")
    is_online = target_user_id in user_connections
    
    await websocket.send_text(json.dumps({
        "event_name": "user_status",
        "event_data": {
            "user_id": target_user_id,
            "online": is_online,
            "timestamp": datetime.now().isoformat()
        }
    }))



async def handle_typing_start(websocket: WebSocket, event_data: dict):
    """Handle typing_start event for real-time chat typing indicators"""
    # Authentication check
    if websocket not in authenticated_users:
        await websocket.send_text(json.dumps({"status": 401, "message": "Not authenticated"}))
        return

    user_id = authenticated_users[websocket]
    chat_id = event_data.get("chat_id")
    
    if not chat_id:
        await websocket.send_text(json.dumps({
            "status": 400,
            "message": "chat_id is required for typing events"
        }))
        return

    # Add user to typing status tracking
    if chat_id not in typing_users:
        typing_users[chat_id] = set()
    
    typing_users[chat_id].add(user_id)
    user_typing_in[user_id] = chat_id

    # Send acknowledgment to sender
    await websocket.send_text(json.dumps({
        "status": 200,
        "event_name": "typing_start_ack",
        "event_data": {
            "chat_id": chat_id,
            "user_id": user_id,
            "timestamp": datetime.now().isoformat()
        }
    }))

    # Broadcast typing_start to other users in the same chat
    await broadcast_typing_event(chat_id, user_id, "typing_start")
    
    logger.info(f"User {user_id} started typing in chat {chat_id}")



async def handle_typing_stop(websocket: WebSocket, event_data: dict):
    """Handle typing_stop event for real-time chat typing indicators"""
    # Authentication check
    if websocket not in authenticated_users:
        await websocket.send_text(json.dumps({"status": 401, "message": "Not authenticated"}))
        return

    user_id = authenticated_users[websocket]
    chat_id = event_data.get("chat_id")
    
    if not chat_id:
        await websocket.send_text(json.dumps({
            "status": 400,
            "message": "chat_id is required for typing events"
        }))
        return

    # Remove user from typing status tracking
    if chat_id in typing_users:
        typing_users[chat_id].discard(user_id)
        if not typing_users[chat_id]:  # Remove empty set
            del typing_users[chat_id]
    
    if user_id in user_typing_in and user_typing_in[user_id] == chat_id:
        del user_typing_in[user_id]

    # Send acknowledgment to sender
    await websocket.send_text(json.dumps({
        "status": 200,
        "event_name": "typing_stop_ack",
        "event_data": {
            "chat_id": chat_id,
            "user_id": user_id,
            "timestamp": datetime.now().isoformat()
        }
    }))

    # Broadcast typing_stop to other users in the same chat
    await broadcast_typing_event(chat_id, user_id, "typing_stop")
    
    logger.info(f"User {user_id} stopped typing in chat {chat_id}")


async def broadcast_typing_event(chat_id: str, typing_user_id: str, event_name: str):
    """Broadcast typing events to other users in the same chat room"""
    broadcast_message = json.dumps({
        "event_name": event_name,
        "event_data": {
            "chat_id": chat_id,
            "typing_user_id": typing_user_id,
            "timestamp": datetime.now().isoformat()
        }
    })
    
    # Send to all authenticated users except the typing user
    disconnected_users = []
    
    for client_ws in connected_clients:
        if (client_ws in authenticated_users and 
            authenticated_users[client_ws] != typing_user_id):
            try:
                await client_ws.send_text(broadcast_message)
            except Exception as e:
                logger.error(f"Error broadcasting typing event to user: {e}")
                disconnected_users.append(client_ws)
    
    # Cleanup disconnected clients
    for client_ws in disconnected_users:
        connected_clients.discard(client_ws)


async def websocket_handler(websocket: WebSocket):
    """Main WebSocket connection handler"""
    await websocket.accept()
    connected_clients.add(websocket)
    
    try:
        while True:
            raw_data = await websocket.receive_text()
            raw_data = raw_data.strip()
            
            event, error = parse_event(raw_data)
            
            if error:
                await websocket.send_text(json.dumps(error))
                continue
            
            event_name = event.get("event_name")
            event_data = event.get("event_data", {})
            
            # Route events to handlers
            if event_name == "login":
                success = await handle_login(websocket, event_data)
                if not success:
                    break
        
            elif event_name == "send_chat":
                await handle_send_chat(websocket, event_data)
                
            elif event_name == "typing_start":
                await handle_typing_start(websocket, event_data)
                
            elif event_name == "typing_stop":
                await handle_typing_stop(websocket, event_data)
            elif event_name == "message_read":
                await handle_message_read(websocket, event_data)
                
            elif event_name == "update_last_read_time":
                await handle_update_last_read_time(websocket, event_data)
                
            elif event_name == "status_check":
                await handle_status_check(websocket, event_data)
                
            else:
                await websocket.send_text(json.dumps({
                    "status": 404,
                    "message": f"Unknown event: {event_name}"
                }))
                
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected normally")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        # Cleanup connections
        await cleanup_connection(websocket)

async def cleanup_connection(websocket: WebSocket):
    """Clean up user connection and tracking data"""
    connected_clients.discard(websocket)
    
    if websocket in authenticated_users:
        user_id = authenticated_users[websocket]
        user_connections.pop(user_id, None)
        authenticated_users.pop(websocket, None)
        
        # Clean up typing status if user was typing
        if user_id in user_typing_in:
            chat_id = user_typing_in[user_id]
            if chat_id in typing_users:
                typing_users[chat_id].discard(user_id)
                if not typing_users[chat_id]:
                    del typing_users[chat_id]
            del user_typing_in[user_id]
            
            # Broadcast typing_stop for this user
            await broadcast_typing_event(chat_id, user_id, "typing_stop")

    user_last_read_time.pop(websocket, None)
    
    
    # Clean up message tracking
    for message_info in message_tracking.values():
        message_info["recipients"].discard(websocket)
        message_info["delivered_to"].discard(websocket)
        message_info["read_by"].discard(websocket)
    
    try:
        await websocket.close()
    except:
        pass

