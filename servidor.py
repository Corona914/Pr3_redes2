
import socket
import threading
import json
import base64
from datetime import datetime

SERVER_HOST = "0.0.0.0"
SERVER_PORT = 12345
BUFFER_SIZE = 65535

lock = threading.Lock()
# rooms
rooms = {}
# users
users_addrs = {}


def now_iso():
    return datetime.utcnow().isoformat() + "Z"


def send_json(sock, data, addr):
    try:
        payload = json.dumps(data).encode("utf-8")
        sock.sendto(payload, addr)
    except Exception as e:
        print(f"[send_json] Error enviando a {addr}: {e}")


def broadcast_room_userlist(sock, room):
    with lock:
        members = rooms.get(room, {}).copy()
    msg = {"action": "userlist", "room": room, "users": list(members.keys()), "timestamp": now_iso()}
    for uname, addr in members.items():
        send_json(sock, msg, addr)


def handle_packet(data, addr, sock):
    try:
        msg = json.loads(data.decode("utf-8"))
    except Exception as e:
        print(f"[handle_packet] paquete inválido desde {addr}: {e}")
        return

    action = msg.get("action")
    username = msg.get("username")
    room = msg.get("room")
    timestamp = msg.get("timestamp", now_iso())

   
    if username:
        with lock:
            users_addrs[username] = addr

    if action == "create":
        if not room or not username:
            return
        with lock:
            if room in rooms:
                resp = {"action": "error", "message": f"Sala '{room}' ya existe", "timestamp": now_iso()}
                send_json(sock, resp, addr)
                return
            rooms[room] = {}
            rooms[room][username] = addr
        print(f"[{timestamp}] {username} creó y se unió a '{room}'")
        broadcast_room_userlist(sock, room)

    elif action == "join":
        if not room or not username:
            return
        with lock:
            rooms.setdefault(room, {})[username] = addr
        print(f"[{timestamp}] {username} se unió a '{room}' desde {addr}")
        broadcast_room_userlist(sock, room)

    elif action == "leave":
        if not room or not username:
            return
        with lock:
            if room in rooms and username in rooms[room]:
                del rooms[room][username]
        print(f"[{timestamp}] {username} salió de '{room}'")
        broadcast_room_userlist(sock, room)

    elif action == "list_rooms":
        with lock:
            listing = [{"room": r, "users": len(m)} for r, m in rooms.items()]
        resp = {"action": "rooms_list", "rooms": listing, "timestamp": now_iso()}
        send_json(sock, resp, addr)

    elif action == "list_request":
        if not room:
            return
        with lock:
            members = rooms.get(room, {}).copy()
        resp = {"action": "userlist", "room": room, "users": list(members.keys()), "timestamp": now_iso()}
        send_json(sock, resp, addr)

    elif action == "message":
    
        if not room or not username:
            return
        msg_type = msg.get("msg_type", "text")
        payload = msg.get("payload", "")
        with lock:
            members = rooms.get(room, {}).copy()
        forward = {
            "action": "message",
            "room": room,
            "from": username,
            "msg_type": msg_type,
            "payload": payload,
            "timestamp": timestamp
        }
        # reenviar a todos miembros de la sala
        for uname, member_addr in members.items():
            send_json(sock, forward, member_addr)

    elif action == "private":
        target = msg.get("target")
        if not target or not username:
            return
        with lock:
            addr_target = users_addrs.get(target)
        if addr_target:
            forward = {
                "action": "private",
                "from": username,
                "to": target,
                "msg_type": msg.get("msg_type", "text"),
                "payload": msg.get("payload", ""),
                "timestamp": timestamp
            }
            send_json(sock, forward, addr_target)
        else:
            resp = {"action": "error", "message": f"Usuario '{target}' no encontrado", "timestamp": now_iso()}
            send_json(sock, resp, addr)

    else:
        resp = {"action": "error", "message": f"Acción desconocida: {action}", "timestamp": now_iso()}
        send_json(sock, resp, addr)


def server_loop():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((SERVER_HOST, SERVER_PORT))
    print(f"Servidor UDP escuchando en {SERVER_HOST}:{SERVER_PORT}")

    try:
        while True:
            data, addr = sock.recvfrom(BUFFER_SIZE)
            # procesar cada datagrama en un hilo 
            t = threading.Thread(target=handle_packet, args=(data, addr, sock), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("Servidor finalizando (KeyboardInterrupt).")
    except Exception as e:
        print(f"Error en server_loop: {e}")
    finally:
        sock.close()


if __name__ == "__main__":
    server_loop()
