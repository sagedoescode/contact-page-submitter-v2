# app/api/websocket.py - Optimized WebSocket implementation
from fastapi import (
    APIRouter,
    WebSocket,
    WebSocketDisconnect,
    Depends,
    HTTPException,
    status,
    Request,
    Query,
)
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any, List, Set
import json
import asyncio
import logging
import time
from datetime import datetime

from app.core.database import get_db
from app.models.user import User
from app.logging import get_logger

router = APIRouter(prefix="/api/ws", tags=["websocket"], redirect_slashes=False)
logger = get_logger(__name__)


class ConnectionManager:
    def __init__(self):
        self.campaign_connections: Dict[str, Set[WebSocket]] = {}
        self.user_connections: Dict[str, Set[WebSocket]] = {}
        self.connection_meta: Dict[WebSocket, Dict[str, Any]] = {}

    async def connect(self, websocket: WebSocket, campaign_id: str, user_id: str):
        """Accept a WebSocket connection and register it"""
        await websocket.accept()

        if campaign_id not in self.campaign_connections:
            self.campaign_connections[campaign_id] = set()
        self.campaign_connections[campaign_id].add(websocket)

        if user_id not in self.user_connections:
            self.user_connections[user_id] = set()
        self.user_connections[user_id].add(websocket)

        self.connection_meta[websocket] = {
            "campaign_id": campaign_id,
            "user_id": user_id,
            "connected_at": datetime.utcnow(),
        }

        # Log only the connection event with essential context
        logger.info(
            "WebSocket connected",
            extra={
                "event": "ws_connect",
                "user_id": user_id,
                "campaign_id": campaign_id,
                "total_connections": len(self.connection_meta),
            },
        )

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection"""
        if websocket in self.connection_meta:
            meta = self.connection_meta[websocket]
            campaign_id = meta.get("campaign_id")
            user_id = meta.get("user_id")
            duration_seconds = (
                datetime.utcnow() - meta["connected_at"]
            ).total_seconds()

            if campaign_id and campaign_id in self.campaign_connections:
                self.campaign_connections[campaign_id].discard(websocket)
                if not self.campaign_connections[campaign_id]:
                    del self.campaign_connections[campaign_id]

            if user_id and user_id in self.user_connections:
                self.user_connections[user_id].discard(websocket)
                if not self.user_connections[user_id]:
                    del self.user_connections[user_id]

            del self.connection_meta[websocket]

            # Log disconnection with duration for audit
            logger.info(
                "WebSocket disconnected",
                extra={
                    "event": "ws_disconnect",
                    "user_id": user_id,
                    "campaign_id": campaign_id,
                    "duration_seconds": round(duration_seconds, 2),
                    "remaining_connections": len(self.connection_meta),
                },
            )

    async def send_to_campaign(self, message: str, campaign_id: str):
        """Send a message to all connections for a specific campaign"""
        if campaign_id in self.campaign_connections:
            disconnected = set()
            send_count = 0
            fail_count = 0

            for connection in self.campaign_connections[campaign_id].copy():
                try:
                    await connection.send_text(message)
                    send_count += 1
                except Exception as e:
                    fail_count += 1
                    disconnected.add(connection)

            # Only log if there were failures
            if fail_count > 0:
                logger.warning(
                    "WebSocket broadcast had failures",
                    extra={
                        "event": "ws_broadcast_failure",
                        "campaign_id": campaign_id,
                        "successful": send_count,
                        "failed": fail_count,
                    },
                )

            for connection in disconnected:
                self.disconnect(connection)

    async def broadcast_to_campaign(self, data: dict, campaign_id: str):
        """Broadcast structured data to all connections for a campaign"""
        message = json.dumps(data)
        await self.send_to_campaign(message, campaign_id)


# Global connection manager instance
manager = ConnectionManager()


# Main WebSocket endpoint - this will be accessible at /api/ws
@router.websocket("")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(None)):
    """Main WebSocket endpoint for real-time updates"""
    from app.core.security import verify_token

    user_id = None
    campaign_id = "general"

    try:
        # Verify token
        if not token:
            logger.security_event(
                event="ws_no_token",
                severity="warning",
                properties={"reason": "Missing authentication token"},
            )
            await websocket.close(code=1008, reason="Missing token")
            return

        try:
            payload = verify_token(token)
            user_id = payload.get("user_id")
            if not user_id:
                logger.security_event(
                    event="ws_invalid_token",
                    severity="warning",
                    properties={"reason": "Token missing user_id"},
                )
                await websocket.close(code=1008, reason="Invalid token payload")
                return
        except Exception as e:
            logger.security_event(
                event="ws_auth_failed",
                severity="error",
                properties={
                    "reason": "Token verification failed",
                    "error_type": type(e).__name__,
                },
            )
            await websocket.close(code=1008, reason="Invalid token")
            return

        # Accept connection (this will log via manager.connect)
        await manager.connect(websocket, campaign_id, user_id)

        # Send initial connection message
        await websocket.send_json(
            {
                "type": "connection",
                "status": "connected",
                "user_id": user_id,
                "timestamp": datetime.utcnow().isoformat(),
                "message": "WebSocket connected successfully",
            }
        )

        # Keep connection alive and handle messages
        while True:
            try:
                # Wait for messages with timeout for keepalive
                data = await asyncio.wait_for(websocket.receive_text(), timeout=60.0)

                try:
                    message = json.loads(data)
                    message_type = message.get("type")

                    # Handle different message types (no logging for ping/pong - too noisy)
                    if message_type == "ping":
                        await websocket.send_json(
                            {"type": "pong", "timestamp": datetime.utcnow().isoformat()}
                        )
                    elif message_type == "subscribe_campaign":
                        new_campaign_id = message.get("campaign_id")
                        if new_campaign_id:
                            # Log campaign subscription changes
                            logger.info(
                                "Campaign subscription changed",
                                extra={
                                    "event": "ws_subscribe",
                                    "user_id": user_id,
                                    "old_campaign": campaign_id,
                                    "new_campaign": new_campaign_id,
                                },
                            )
                            # Update the campaign subscription
                            manager.disconnect(websocket)
                            campaign_id = new_campaign_id
                            await manager.connect(websocket, campaign_id, user_id)
                            await websocket.send_json(
                                {
                                    "type": "subscribed",
                                    "campaign_id": campaign_id,
                                    "timestamp": datetime.utcnow().isoformat(),
                                }
                            )
                    else:
                        # Echo unknown messages (no logging - handled by client)
                        await websocket.send_json(
                            {
                                "type": "echo",
                                "original": message,
                                "timestamp": datetime.utcnow().isoformat(),
                            }
                        )

                except json.JSONDecodeError:
                    await websocket.send_json(
                        {"type": "error", "message": "Invalid JSON format"}
                    )

            except asyncio.TimeoutError:
                # Send keepalive (no logging - this is expected every 60s)
                await websocket.send_json(
                    {"type": "keepalive", "timestamp": datetime.utcnow().isoformat()}
                )

    except WebSocketDisconnect:
        # Normal disconnection - no logging needed (handled by manager.disconnect)
        pass
    except Exception as e:
        # Unexpected errors should be logged
        logger.error(
            "WebSocket unexpected error",
            extra={
                "event": "ws_error",
                "user_id": user_id,
                "campaign_id": campaign_id,
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
            exc_info=True,
        )
    finally:
        manager.disconnect(websocket)


@router.websocket("/campaign/{campaign_id}")
async def websocket_campaign_endpoint(
    websocket: WebSocket, campaign_id: str, token: str = Query(None)
):
    """WebSocket endpoint for campaign-specific updates"""
    from app.core.security import verify_token

    user_id = None

    try:
        # Verify token
        if not token:
            logger.security_event(
                event="ws_campaign_no_token",
                severity="warning",
                properties={"campaign_id": campaign_id},
            )
            await websocket.close(code=1008, reason="Missing token")
            return

        try:
            payload = verify_token(token)
            user_id = payload.get("user_id")
        except Exception as e:
            logger.security_event(
                event="ws_campaign_auth_failed",
                severity="error",
                properties={
                    "campaign_id": campaign_id,
                    "error_type": type(e).__name__,
                },
            )
            await websocket.close(code=1008, reason="Invalid token")
            return

        # Connect to specific campaign (logs via manager.connect)
        await manager.connect(websocket, campaign_id, user_id)

        # Send welcome message
        await websocket.send_json(
            {
                "type": "connection",
                "status": "connected",
                "campaign_id": campaign_id,
                "user_id": user_id,
                "timestamp": datetime.utcnow().isoformat(),
                "message": f"Connected to campaign {campaign_id} updates",
            }
        )

        # Keep connection alive
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=60.0)

                try:
                    message = json.loads(data)
                    # Handle ping/pong (no logging)
                    if message.get("type") == "ping":
                        await websocket.send_json(
                            {"type": "pong", "timestamp": datetime.utcnow().isoformat()}
                        )
                except json.JSONDecodeError:
                    pass

            except asyncio.TimeoutError:
                # Send keepalive (no logging)
                await websocket.send_json(
                    {"type": "keepalive", "timestamp": datetime.utcnow().isoformat()}
                )

    except WebSocketDisconnect:
        # Normal disconnection (handled by manager.disconnect)
        pass
    except Exception as e:
        # Unexpected errors
        logger.error(
            "WebSocket campaign error",
            extra={
                "event": "ws_campaign_error",
                "user_id": user_id,
                "campaign_id": campaign_id,
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
            exc_info=True,
        )
    finally:
        manager.disconnect(websocket)


# Helper function to send campaign updates
async def send_campaign_update(campaign_id: str, update_data: dict):
    """Send update to all connections watching a campaign"""
    await manager.broadcast_to_campaign(
        {
            "type": "campaign_update",
            "campaign_id": campaign_id,
            "data": update_data,
            "timestamp": datetime.utcnow().isoformat(),
        },
        campaign_id,
    )
