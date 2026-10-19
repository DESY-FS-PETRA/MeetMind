from __future__ import annotations

import asyncio
from contextlib import suppress

from fastapi import WebSocket, WebSocketDisconnect


# One transcript socket per browser client_id. Opening a new socket with the
# same client_id replaces the stale socket instead of broadcasting twice to
# the same page.
_clients: dict[str, WebSocket] = {}
_clients_lock = asyncio.Lock()


async def transcript_socket(websocket: WebSocket) -> None:
    client_id = websocket.query_params.get("client_id") or str(id(websocket))

    print(f"TRANSCRIPT SOCKET REQUEST client_id={client_id}")
    await websocket.accept()

    async with _clients_lock:
        previous = _clients.get(client_id)
        _clients[client_id] = websocket

    if previous is not None and previous is not websocket:
        print(f"Replacing stale transcript socket client_id={client_id}")
        with suppress(Exception):
            await previous.close(code=4001, reason="Replaced by a newer connection")

    print("Frontend connected. Clients:", len(_clients))

    try:
        # The browser does not need to send transcript messages. Waiting here
        # keeps the connection alive and detects a clean disconnect.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        print(f"Frontend disconnected client_id={client_id}")
    except Exception as exc:
        print(f"Transcript socket error client_id={client_id}: {exc}")
    finally:
        async with _clients_lock:
            if _clients.get(client_id) is websocket:
                _clients.pop(client_id, None)

        print("Transcript clients remaining:", len(_clients))


async def broadcast_transcript(data: dict) -> None:
    async with _clients_lock:
        current_clients = list(_clients.items())

    print("BROADCAST:", data)
    print("Number of clients:", len(current_clients))

    disconnected: list[tuple[str, WebSocket]] = []

    for client_id, client in current_clients:
        try:
            await client.send_json(data)
            print(f"SENT TO CLIENT {client_id}")
        except Exception as exc:
            print(f"SEND ERROR client_id={client_id}: {exc}")
            disconnected.append((client_id, client))

    if disconnected:
        async with _clients_lock:
            for client_id, client in disconnected:
                if _clients.get(client_id) is client:
                    _clients.pop(client_id, None)
