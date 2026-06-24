from fastapi import WebSocket
from typing import Dict, List
import json

class ConnectionManager:
    def __init__(self):
        # We store connections by user role and user ID
        # Format: {"admin": {user_id: websocket}, "doctor": {user_id: websocket}, "patient": {user_id: websocket}, "display": [websocket]}
        self.active_connections: Dict[str, Dict[int, WebSocket]] = {
            "admin": {},
            "doctor": {},
            "patient": {}
        }
        self.display_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket, role: str, user_id: int = None):
        await websocket.accept()
        if role == "display":
            self.display_connections.append(websocket)
        elif role in self.active_connections:
            if user_id is not None:
                self.active_connections[role][user_id] = websocket

    def disconnect(self, websocket: WebSocket, role: str, user_id: int = None):
        if role == "display":
            if websocket in self.display_connections:
                self.display_connections.remove(websocket)
        elif role in self.active_connections:
            if user_id is not None and user_id in self.active_connections[role]:
                del self.active_connections[role][user_id]

    async def broadcast_to_admins(self, message: dict):
        text_data = json.dumps(message)
        for user_id, connection in self.active_connections["admin"].items():
            try:
                await connection.send_text(text_data)
            except Exception:
                pass

    async def send_to_doctor(self, doctor_id: int, message: dict):
        text_data = json.dumps(message)
        if doctor_id in self.active_connections["doctor"]:
            try:
                await self.active_connections["doctor"][doctor_id].send_text(text_data)
            except Exception:
                pass

    async def broadcast_to_doctors(self, message: dict):
        text_data = json.dumps(message)
        for doctor_id, connection in self.active_connections["doctor"].items():
            try:
                await connection.send_text(text_data)
            except Exception:
                pass

    async def send_to_patient(self, patient_id: int, message: dict):
        text_data = json.dumps(message)
        if patient_id in self.active_connections["patient"]:
            try:
                await self.active_connections["patient"][patient_id].send_text(text_data)
            except Exception:
                pass
                
    async def broadcast_to_display(self, message: dict):
        text_data = json.dumps(message)
        for connection in self.display_connections:
            try:
                await connection.send_text(text_data)
            except Exception:
                pass
                
    async def broadcast_all(self, message: dict):
        await self.broadcast_to_admins(message)
        await self.broadcast_to_doctors(message)
        await self.broadcast_to_display(message)
        # We don't broadcast global updates to individual patients for privacy/performance

manager = ConnectionManager()
