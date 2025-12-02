import socket
import threading
import json
import base64
import os
import tkinter as tk
from tkinter import simpledialog, filedialog, messagebox, scrolledtext
import tkinter.ttk as ttk
from datetime import datetime
import pyaudio
import wave

SERVER_IP = "127.0.0.1"
SERVER_PORT = 12345
BUFFER_SIZE = 65535
MAX_FILE_BYTES = 65 * 1024

CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 8000
TEMP_AUDIO_FILENAME = "temp_recording.wav"

# Diccionario de stickers ASCII
STICKERS = {
    "oso": r'''
╱|、
(˚ˎ 。7  
 |、˜〵          
 じしˍ,)ノ
''',
    "gato": r'''
 /\_/\
( o.o )
 > ^ <
''',
    "perro": r'''
  / \__
 (    @\____
 /         O
/   (_____/
/_____/   U
''',
    "conejo": r'''
 (\_/)
 (.:.)
(")(")
''',
    "corazon": r'''
 ♥ ♥ 
♥ ♥ ♥
 ♥ ♥ 
  ♥
''',
    "pulgar": r'''
  👍
''',
    "carita": r'''
 ( ͡° ͜ʖ ͡°)
'''
}

def now_iso():
    return datetime.utcnow().isoformat() + "Z"


class ClienteChatUDP:
    def __init__(self):
        self.username = simpledialog.askstring("Nombre de usuario", "Ingresa tu nombre de usuario:")
        if not self.username:
            return

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("", 0))
        self.server_addr = (SERVER_IP, SERVER_PORT)

        self.colores = {
            "ventana": "#2c2f33",
            "panel": "#23272a",
            "area_texto": "#3b3f45",
            "texto": "#ffffff",
            "texto_secundario": "#b0b0b0",
            "boton": "#5865f2",
            "texto_boton": "#ffffff",
            "error": "#f04747",
            "privado": "#5865f2",
            "info": "#4caf50",
            "me_text": "#a0e0ff",
            "sticker": "#ffcc00",
            "archivo": "#ff9966"
        }
        
        self.main_font = ("Arial", 15)
        self.header_font = ("Arial", 15, "bold")
        self.button_font = ("Arial", 12, "bold")
        self.status_font = ("Arial", 12)
        self.sticker_font = ("Courier New", 10)
        
        self.room_histories = {}
        self.history_lock = threading.Lock()
        
        self.file_cache = {}
        self.file_lock = threading.Lock()
        
        self.public_rooms = [] 
        self.current_users_in_room = [] 
        
        self.is_recording = False
        self.audio_frames = []
        self.audio_stream = None
        self.pyaudio_instance = pyaudio.PyAudio()
        
        self.send_json({"action": "register", "username": self.username, "timestamp": now_iso()})

        self.sala_actual = None
        self.ventana = tk.Tk()
        self.ventana.title(f"Chat UDP - {self.username}")
        self.ventana.geometry("1400x1000")
        self.crear_interfaz()

        self.running = True
        t = threading.Thread(target=self.listener_loop, daemon=True)
        t.start()

        self.ventana.protocol("WM_DELETE_WINDOW", self.salir)
        self.ventana.mainloop()

    def crear_interfaz(self):
        self.ventana.config(bg=self.colores["ventana"])

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            style.theme_use("default")
        style.configure("TButton", background=self.colores["boton"], foreground=self.colores["texto_boton"], font=self.button_font, relief="flat", padding=4)
        style.map("TButton", background=[("active", self.colores["privado"])])

        self.frame_salas = tk.Frame(self.ventana, width=200, bg=self.colores["panel"])
        self.frame_salas.pack(side=tk.LEFT, fill=tk.Y)
        tk.Label(self.frame_salas, text="Salas", font=self.header_font, bg=self.colores["panel"], fg=self.colores["texto"]).pack(pady=8)
        self.lista_salas_frame = tk.Frame(self.frame_salas, bg=self.colores["panel"])
        self.lista_salas_frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Button(self.frame_salas, text="+ Crear Sala", command=self.crear_sala).pack(pady=5)
        ttk.Button(self.frame_salas, text="Actualizar Salas", command=self.actualizar_salas_publicas).pack(pady=5)
        ttk.Button(self.frame_salas, text="Salir App", command=self.salir).pack(pady=5)

        self.frame_right = tk.Frame(self.ventana, width=250, bg=self.colores["panel"])
        self.frame_right.pack(side=tk.RIGHT, fill=tk.Y, padx=(5,0))
        
        frame_files_container = tk.Frame(self.frame_right, bg=self.colores["panel"], height=400)
        frame_files_container.pack(fill=tk.X, pady=5)
        tk.Label(frame_files_container, text="Archivos en Sala", font=self.header_font, bg=self.colores["panel"], fg=self.colores["texto"]).pack(pady=8)
        frame_list_files = tk.Frame(frame_files_container, bg=self.colores["panel"])
        frame_list_files.pack(fill=tk.BOTH, expand=True, pady=5)
        file_scrollbar = tk.Scrollbar(frame_list_files, orient=tk.VERTICAL)
        self.lista_files = tk.Listbox(frame_list_files, bg=self.colores["area_texto"], fg=self.colores["texto"], yscrollcommand=file_scrollbar.set, selectmode=tk.SINGLE, height=15, font=self.main_font)
        file_scrollbar.config(command=self.lista_files.yview)
        file_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.lista_files.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ttk.Button(frame_files_container, text="Descargar Seleccionado", command=self.descargar_archivo_seleccionado).pack(pady=10)

        frame_users_container = tk.Frame(self.frame_right, bg=self.colores["panel"])
        frame_users_container.pack(fill=tk.BOTH, expand=True, pady=5)
        tk.Label(frame_users_container, text="Usuarios en Sala", font=self.header_font, bg=self.colores["panel"], fg=self.colores["texto"]).pack(pady=8)
        frame_list_users = tk.Frame(frame_users_container, bg=self.colores["panel"])
        frame_list_users.pack(fill=tk.BOTH, expand=True, pady=5)
        user_scrollbar = tk.Scrollbar(frame_list_users, orient=tk.VERTICAL)
        self.lista_users = tk.Listbox(frame_list_users, bg=self.colores["area_texto"], fg=self.colores["texto"], yscrollcommand=user_scrollbar.set, selectmode=tk.SINGLE, font=self.main_font)
        user_scrollbar.config(command=self.lista_users.yview)
        user_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.lista_users.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ttk.Button(frame_users_container, text="Iniciar Chat Privado", command=self.iniciar_chat_privado).pack(pady=10)

        self.area_mensajes = scrolledtext.ScrolledText(self.ventana, state='disabled', wrap=tk.WORD, bg=self.colores["area_texto"], fg=self.colores["texto"], font=self.main_font)
        self.area_mensajes.pack(padx=8, pady=8, fill=tk.BOTH, expand=True)
        
        self.area_mensajes.tag_config("error", foreground=self.colores["error"])
        self.area_mensajes.tag_config("privado", foreground=self.colores["privado"])
        self.area_mensajes.tag_config("info", foreground=self.colores["info"])
        self.area_mensajes.tag_config("me", justify='right', foreground=self.colores["me_text"])
        self.area_mensajes.tag_config("other", justify='left')
        self.area_mensajes.tag_config("sticker", font=self.sticker_font, foreground=self.colores["sticker"])
        self.area_mensajes.tag_config("archivo", foreground=self.colores["archivo"])

        barra = tk.Frame(self.ventana, bg=self.colores["ventana"])
        barra.pack(fill=tk.X, padx=8, pady=6)
        self.entry_mensaje = tk.Entry(barra, bg=self.colores["area_texto"], fg=self.colores["texto"], insertbackground=self.colores["texto"], font=self.main_font)
        self.entry_mensaje.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        ttk.Button(barra, text="Enviar", command=self.enviar_mensaje).pack(side=tk.LEFT, padx=4)
        
        ttk.Button(barra, text="🖼️ Sticker", command=self.mostrar_menu_stickers).pack(side=tk.LEFT, padx=4)
        ttk.Button(barra, text="📎 Archivo", command=self.enviar_archivo).pack(side=tk.LEFT, padx=4)
        self.btn_audio = ttk.Button(barra, text="🎙️ Grabar", command=self.toggle_audio_recording)
        self.btn_audio.pack(side=tk.LEFT, padx=4)

        self.lbl_estado = tk.Label(self.ventana, text="No conectado a ninguna sala", font=self.status_font, fg=self.colores["texto_secundario"], bg=self.colores["ventana"])
        self.lbl_estado.pack(padx=8, pady=2)

    def mostrar_menu_stickers(self):
        if not self.sala_actual:
            messagebox.showinfo("Info", "Únete a una sala primero.")
            return
            
        menu_stickers = tk.Toplevel(self.ventana)
        menu_stickers.title("Seleccionar Sticker")
        menu_stickers.geometry("320x450") # Un poco más grande para mejor visibilidad
        menu_stickers.config(bg=self.colores["panel"])
        menu_stickers.transient(self.ventana)
        menu_stickers.grab_set()
        
        tk.Label(menu_stickers, text="Selecciona un sticker:", 
                 font=self.header_font, bg=self.colores["panel"], fg=self.colores["texto"]).pack(pady=10)
        
        # Frame contenedor principal
        container_frame = tk.Frame(menu_stickers, bg=self.colores["panel"])
        container_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Canvas y Scrollbar
        canvas = tk.Canvas(container_frame, bg=self.colores["panel"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(container_frame, orient="vertical", command=canvas.yview)
        
        # Frame interno que se moverá (scrollable)
        scrollable_frame = tk.Frame(canvas, bg=self.colores["panel"])

        # Función para actualizar el scrollregion
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        # Crear la ventana dentro del canvas
        window_id = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

        # Ajustar el ancho del frame interno al cambiar el tamaño del canvas
        def _configure_canvas(event):
            canvas.itemconfig(window_id, width=event.width)
        
        canvas.bind("<Configure>", _configure_canvas)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Empaquetado (Scrollbar a la derecha, Canvas llena el resto)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # --- LÓGICA DEL MOUSE WHEEL (RUEDA DEL RATÓN) ---
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")

        # Bindings para activar scroll solo cuando el mouse está sobre el menú
        def _bind_mouse(event):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
            canvas.bind_all("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
            canvas.bind_all("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))

        def _unbind_mouse(event):
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        # Activar scroll cuando entras al canvas, desactivar cuando sales
        menu_stickers.bind("<Enter>", _bind_mouse)
        menu_stickers.bind("<Leave>", _unbind_mouse)
        
        # Asegurar limpieza al cerrar la ventana
        def on_close():
            _unbind_mouse(None)
            menu_stickers.destroy()
        menu_stickers.protocol("WM_DELETE_WINDOW", on_close)

        for nombre, sticker in STICKERS.items():
            frame_sticker = tk.Frame(scrollable_frame, bg=self.colores["panel"], bd=1, relief="flat")
            frame_sticker.pack(fill=tk.X, pady=5, padx=5)
            
            # Título del sticker
            tk.Label(frame_sticker, text=nombre.capitalize(), 
                     font=("Arial", 11, "bold"), bg=self.colores["panel"], fg=self.colores["privado"]).pack(anchor="w")
            
            # El arte ASCII
            lbl_sticker = tk.Label(frame_sticker, text=sticker, 
                                  font=self.sticker_font, bg="#2f3136", 
                                  fg=self.colores["sticker"], justify="left", padx=10, pady=5)
            lbl_sticker.pack(anchor="center", fill="x", pady=2)
            
            # Botón enviar
            ttk.Button(frame_sticker, text="Enviar", 
                       command=lambda s=sticker, n=nombre, m=menu_stickers: self.enviar_sticker(s, n, m)).pack(fill="x", pady=2)
            
            # Separador visual
            ttk.Separator(scrollable_frame, orient="horizontal").pack(fill="x", pady=5)
            
    def enviar_sticker(self, sticker_ascii, nombre_sticker, ventana_menu):
        """Envía un sticker ASCII al chat"""
        ventana_menu.destroy()
        
        obj = {}
        if self.sala_actual.startswith("priv_"):
            try:
                user_pair = self.sala_actual.split('_', 1)[1]
                user1, user2 = user_pair.split('-')
                target = user2 if self.username == user1 else user1
                
                obj = {"action": "private", "username": self.username, "target": target,
                       "msg_type": "sticker", "payload": {"nombre": nombre_sticker, "sticker": sticker_ascii}, "timestamp": now_iso()}
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo enviar el sticker privado: {e}")
                return
            
            clean_text = f"[PRIVADO] {self.username} envió un sticker: {nombre_sticker}\n{sticker_ascii}"
            tags = ["privado", "me", "sticker"]
            with self.history_lock:
                if self.sala_actual not in self.room_histories:
                    self.room_histories[self.sala_actual] = []
                self.room_histories[self.sala_actual].append((clean_text, tags))
            self.mostrar_mensaje(clean_text, tags)

        else:
            obj = {"action": "message", "username": self.username, "room": self.sala_actual,
                   "msg_type": "sticker", "payload": {"nombre": nombre_sticker, "sticker": sticker_ascii}, "timestamp": now_iso()}
            
            clean_text = f"[{self.sala_actual}] {self.username} envió un sticker: {nombre_sticker}\n{sticker_ascii}"
            tags = ["me", "sticker"]
            with self.history_lock:
                if self.sala_actual not in self.room_histories:
                    self.room_histories[self.sala_actual] = []
                self.room_histories[self.sala_actual].append((clean_text, tags))
            self.mostrar_mensaje(clean_text, tags)
        
        self.send_json(obj)

    def enviar_archivo(self):
        """Envía un archivo regular al chat"""
        if not self.sala_actual:
            messagebox.showinfo("Info", "Únete a una sala primero.")
            return
            
        path = filedialog.askopenfilename(title="Seleccionar archivo")
        if not path:
            return
            
        try:
            size = os.path.getsize(path)
            if size > MAX_FILE_BYTES:
                messagebox.showerror("Error", f"Archivo demasiado grande ({size} bytes). Límite: {MAX_FILE_BYTES} bytes.")
                return
                
            with open(path, "rb") as f:
                raw = f.read()
            b64 = base64.b64encode(raw).decode("utf-8")
            payload = {"filename": os.path.basename(path), "data": b64}
            obj = {}
            
            clean_text = ""
            tags = ["archivo"]

            if self.sala_actual.startswith("priv_"):
                try:
                    user_pair = self.sala_actual.split('_', 1)[1]
                    user1, user2 = user_pair.split('-')
                    target = user2 if self.username == user1 else user1

                    obj = {"action": "private", "username": self.username, "target": target,
                           "msg_type": "file", "payload": payload, "timestamp": now_iso()}
                    
                    clean_text = f"[PRIVADO] {self.username} envió un archivo: {os.path.basename(path)}"
                    tags.extend(["privado", "me"])

                except Exception as e:
                    messagebox.showerror("Error", f"No se pudo enviar el archivo privado: {e}")
                    return
                
            else:
                obj = {"action": "message", "username": self.username, "room": self.sala_actual,
                       "msg_type": "file", "payload": payload, "timestamp": now_iso()}
                
                clean_text = f"[{self.sala_actual}] {self.username} envió un archivo: {os.path.basename(path)}"
                tags.append("me")
            
            # Eco local
            with self.history_lock:
                if self.sala_actual not in self.room_histories:
                    self.room_histories[self.sala_actual] = []
                self.room_histories[self.sala_actual].append((clean_text, tags))
            self.mostrar_mensaje(clean_text, tags)
            
            # Añadir a la lista de archivos disponibles
            file_key = f"[{'PRIV' if self.sala_actual.startswith('priv_') else self.sala_actual}] {self.username} - {os.path.basename(path)} ({datetime.now().strftime('%H:%M:%S')})"
            with self.file_lock:
                self.file_cache[file_key] = (os.path.basename(path), b64)
            self.ventana.after(0, lambda: self.lista_files.insert(tk.END, file_key))
            
            self.send_json(obj)
            
        except Exception as e:
            messagebox.showerror("Error al enviar archivo", f"Error: {e}")

    def send_json(self, obj):
        try:
            payload = json.dumps(obj).encode("utf-8")
            self.sock.sendto(payload, self.server_addr)
        except Exception as e:
            if "Message too long" in str(e):
                self.ventana.after(0, lambda: messagebox.showerror("Error de Envío", "El mensaje (archivo) es demasiado grande para enviar. Límite: 45 KB."))
            else:
                print(f"Error enviando JSON: {e}")

    def listener_loop(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(BUFFER_SIZE)
                msg = json.loads(data.decode("utf-8"))
                threading.Thread(target=self.handle_incoming, args=(msg,), daemon=True).start()
            except Exception:
                continue

    def handle_incoming(self, msg):
        action = msg.get("action")
        room_key = msg.get("room") 
        text_to_store = ""
        tags_to_apply = [] 

        if action == "userlist":
            room_key = msg.get("room")
            users = msg.get("users", [])
            text_to_store = f"[LISTA] {room_key}: {', '.join(users)}\n"
            tags_to_apply = ["info", "other"]
            
            self.current_users_in_room = users
            self.ventana.after(0, self.rebuild_user_list_gui)
        
        elif action == "rooms_list":
            rooms = msg.get("rooms", [])
            self.public_rooms = [r['room'] for r in rooms] 
            self.ventana.after(0, self.rebuild_room_list_gui) 
            return
        
        elif action == "message":
            room_key = msg.get("room")
            frm = msg.get("from")
            mt = msg.get("msg_type")
            payload = msg.get("payload")
            
            tags_to_apply.append("me" if frm == self.username else "other")
            
            if mt in ("text", "emoji"):
                text_to_store = f"[{room_key}] {frm}: {payload}\n"
            
            elif mt == "sticker":
                nombre = payload.get("nombre", "Sticker")
                sticker_ascii = payload.get("sticker", "")
                text_to_store = f"[{room_key}] {frm} envió un sticker: {nombre}\n{sticker_ascii}"
                tags_to_apply.append("sticker")
            
            elif mt in ("file", "audio"):
                fn = payload.get("filename", f"{mt}_{int(datetime.utcnow().timestamp())}.dat")
                b64 = payload.get("data")
                file_key = f"[{room_key}] {frm} - {fn} ({datetime.now().strftime('%H:%M:%S')})"
                
                with self.file_lock:
                    self.file_cache[file_key] = (fn, b64)
                
                self.ventana.after(0, lambda: self.lista_files.insert(tk.END, file_key))
                
                if mt == "file":
                    text_to_store = f"[{room_key}] {frm} envió un archivo: {fn}\n"
                    tags_to_apply.append("archivo")
                else:  # audio
                    text_to_store = f"[{room_key}] {frm} envió un audio: {fn}\n"
                    tags_to_apply.append("info")

        elif action == "private":
            frm = msg.get("from")
            mt = msg.get("msg_type")
            payload = msg.get("payload")
            
            room_key = self.get_private_room_key(frm) 
            tags_to_apply = ["privado", "me" if frm == self.username else "other"]

            if mt in ("text", "emoji"):
                text_to_store = f"[PRIVADO] {frm}: {payload}\n"
            
            elif mt == "sticker":
                nombre = payload.get("nombre", "Sticker")
                sticker_ascii = payload.get("sticker", "")
                text_to_store = f"[PRIVADO] {frm} envió un sticker: {nombre}\n{sticker_ascii}"
                tags_to_apply.append("sticker")
            
            elif mt in ("file", "audio"):
                fn = payload.get("filename", f"priv_{int(datetime.utcnow().timestamp())}.dat")
                b64 = payload.get("data")
                file_key = f"[PRIV] {frm} - {fn} ({datetime.now().strftime('%H:%M:%S')})"
                
                with self.file_lock:
                    self.file_cache[file_key] = (fn, b64)
                
                self.ventana.after(0, lambda: self.lista_files.insert(tk.END, file_key))
                
                if mt == "file":
                    text_to_store = f"[PRIVADO] {frm} envió un archivo: {fn}\n"
                    tags_to_apply.append("archivo")
                else:  # audio
                    text_to_store = f"[PRIVADO] {frm} envió un audio: {fn}\n"
                    tags_to_apply.append("info")
            
            self.ventana.after(0, self.rebuild_room_list_gui)
        
        elif action == "error":
            room_key = "info" 
            text_to_store = f"[ERROR] {msg.get('message')}\n"
            tags_to_apply = ["error", "other"]
        
        elif msg.get("action") != "rooms_list":
            room_key = "info"
            text_to_store = f"[INFO] {msg}\n"
            tags_to_apply = ["info", "other"]

        if not room_key:
             if self.sala_actual:
                 room_key = self.sala_actual
             else:
                 room_key = "general" 

        if text_to_store:
            clean_text = text_to_store.strip() 
            with self.history_lock:
                if room_key not in self.room_histories:
                    self.room_histories[room_key] = []
                self.room_histories[room_key].append( (clean_text, tags_to_apply) )
            
            if room_key == self.sala_actual:
                self.ventana.after(0, lambda: self.mostrar_mensaje(clean_text, tags_to_apply))

    def mostrar_mensaje(self, mensaje, tags=None): 
        self.area_mensajes.config(state='normal')
        self.area_mensajes.insert(tk.END, mensaje + "\n", tags or [])
        self.area_mensajes.yview(tk.END)
        self.area_mensajes.config(state='disabled')

    def rebuild_user_list_gui(self):
        self.lista_users.delete(0, tk.END)
        if not self.sala_actual or self.sala_actual.startswith("priv_"):
             self.lista_users.insert(tk.END, "(No en sala pública)")
             return

        for user in sorted(self.current_users_in_room):
            display = f"⭐ {user}" if user == self.username else user
            self.lista_users.insert(tk.END, display)
    
    def rebuild_room_list_gui(self):
        for w in self.lista_salas_frame.winfo_children():
            w.destroy()
        
        for sala in self.public_rooms:
            self.create_room_list_entry(sala, sala, is_private=False)
        
        private_rooms = set()
        with self.history_lock:
            for key in self.room_histories.keys():
                if key.startswith("priv_"):
                    try:
                        user_pair = key.split('_', 1)[1]
                        user1, user2 = user_pair.split('-')
                        other_user = user2 if self.username == user1 else user1
                        display_name = f"🔒 {other_user}"
                        private_rooms.add((display_name, key)) 
                    except ValueError:
                        continue
        
        for display_name, internal_key in sorted(list(private_rooms)):
            self.create_room_list_entry(display_name, internal_key, is_private=True)

    def create_room_list_entry(self, display_name, internal_key, is_private=False):
        frame = tk.Frame(self.lista_salas_frame, bg=self.colores["panel"])
        frame.pack(fill=tk.X, padx=4, pady=2)
        
        tk.Label(frame, text=display_name, font=self.main_font, bg=self.colores["panel"], fg=self.colores["texto"]).pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        ttk.Button(frame, text="Abrir", command=lambda s=internal_key: self.unirse_sala(s)).pack(side=tk.LEFT, padx=2)
        
        if not is_private:
            ttk.Button(frame, text="Dejar", command=lambda s=internal_key: self.salir_sala(s)).pack(side=tk.LEFT, padx=2)
            ttk.Button(frame, text="Borrar", command=lambda s=internal_key: self.borrar_sala(s)).pack(side=tk.LEFT, padx=2)

    def iniciar_chat_privado(self):
        try:
            selected_indices = self.lista_users.curselection()
            if not selected_indices:
                messagebox.showinfo("Sin selección", "Selecciona un usuario de la lista.")
                return
            
            selected_display = self.lista_users.get(selected_indices[0])
            if selected_display.startswith("⭐ "):
                selected_display = selected_display[2:]
            
            if selected_display == self.username:
                messagebox.showinfo("Error", "No puedes iniciar un chat contigo mismo.")
                return
            
            room_key = self.get_private_room_key(selected_display)
            self.unirse_sala(room_key)
            self.rebuild_room_list_gui() 

        except Exception as e:
            messagebox.showerror("Error", f"No se pudo iniciar el chat: {e}")

    def get_private_room_key(self, other_user):
        users = sorted([self.username, other_user])
        return f"priv_{users[0]}-{users[1]}"

    def descargar_archivo_seleccionado(self):
        try:
            selected_indices = self.lista_files.curselection()
            if not selected_indices:
                messagebox.showinfo("Sin selección", "Por favor, selecciona un archivo de la lista para descargar.")
                return
            
            selected_key = self.lista_files.get(selected_indices[0])
        except Exception as e:
            messagebox.showerror("Error de GUI", f"No se pudo obtener la selección de la lista: {e}")
            return

        with self.file_lock:
            file_data = self.file_cache.get(selected_key)
        
        if not file_data:
            messagebox.showerror("Error de Caché", "El archivo no se encontró en la memoria caché.")
            return
            
        original_filename, b64_data = file_data

        path = filedialog.asksaveasfilename(
            title="Guardar archivo",
            initialdir=os.path.expanduser("~/Downloads"),
            initialfile=original_filename
        )
        
        if not path:
            return
            
        try:
            raw_data = base64.b64decode(b64_data)
            with open(path, "wb") as f:
                f.write(raw_data)
            self.mostrar_mensaje(f"[INFO] Archivo '{original_filename}' guardado en {os.path.basename(path)}", ["info", "other"])
            
            self.lista_files.delete(selected_indices[0])
            with self.file_lock:
                if selected_key in self.file_cache:
                    del self.file_cache[selected_key]

        except base64.B64DecodeError:
            messagebox.showerror("Error de Descarga", "Los datos del archivo estaban corruptos (Error de Base64).")
        except IOError as e:
            messagebox.showerror("Error de Guardado", f"No se pudo escribir el archivo en el disco. ¿Permisos?\n{e}")
        except Exception as e:
            messagebox.showerror("Error Inesperado", f"Ocurrió un error al guardar: {e}")

    def crear_sala(self):
        nombre = simpledialog.askstring("Crear Sala", "Nombre de la sala:")
        if not nombre or nombre.startswith("priv_"):
            messagebox.showerror("Nombre inválido", "El nombre de la sala no puede estar vacío o empezar con 'priv_'.")
            return
        
        self.send_json({"action": "create", "username": self.username, "room": nombre, "timestamp": now_iso()})
        self.unirse_sala(nombre) 
        
        self.area_mensajes.config(state='normal')
        self.area_mensajes.delete(1.0, tk.END)
        with self.history_lock:
            history_list = self.room_histories.get(nombre, []) 
        
        for message, tags in history_list:
            self.area_mensajes.insert(tk.END, message + "\n", tags) 
        
        self.area_mensajes.yview(tk.END)
        self.area_mensajes.config(state='disabled')

    def actualizar_salas_publicas(self):
        self.send_json({"action": "list_rooms", "username": self.username, "timestamp": now_iso()})

    def unirse_sala(self, sala_key):
        if self.sala_actual == sala_key:
            return
            
        if not sala_key.startswith("priv_"):
            self.send_json({"action": "join", "username": self.username, "room": sala_key, "timestamp": now_iso()})
        
        self.sala_actual = sala_key
        self.lbl_estado.config(text=f"Conectado a: {sala_key}")

        self.area_mensajes.config(state='normal')
        self.area_mensajes.delete(1.0, tk.END)
        with self.history_lock:
            history_list = self.room_histories.get(sala_key, []) 
        
        for message, tags in history_list:
            self.area_mensajes.insert(tk.END, message + "\n", tags) 
        
        self.area_mensajes.yview(tk.END)
        self.area_mensajes.config(state='disabled')
        
        self.rebuild_user_list_gui()

    def salir_sala(self, sala_key):
        if sala_key.startswith("priv_") or self.sala_actual != sala_key:
            return
            
        self.send_json({"action": "leave", "username": self.username, "room": self.sala_actual, "timestamp": now_iso()})
        self.sala_actual = None
        self.lbl_estado.config(text="No conectado a ninguna sala")
        
        self.area_mensajes.config(state='normal')
        self.area_mensajes.delete(1.0, tk.END)
        self.area_mensajes.config(state='disabled')  # CORREGIDO: comilla simple
        
        self.current_users_in_room = []
        self.rebuild_user_list_gui()

    def borrar_sala(self, sala):
        if sala.startswith("priv_"):
            return
        if messagebox.askyesno("Confirmar", f"Borrar sala '{sala}'?"):
            self.send_json({"action": "delete", "username": self.username, "room": sala, "timestamp": now_iso()})
            with self.history_lock:
                if sala in self.room_histories:
                    del self.room_histories[sala]
            self.actualizar_salas_publicas()

    def enviar_mensaje(self):
        texto = self.entry_mensaje.get().strip()
        if not texto:
            return
        if not self.sala_actual:
            messagebox.showinfo("Info", "Únete a una sala primero.")
            return
            
        obj = {}
        if self.sala_actual.startswith("priv_"):
            try:
                user_pair = self.sala_actual.split('_', 1)[1]
                user1, user2 = user_pair.split('-')
                target = user2 if self.username == user1 else user1
                
                obj = {"action": "private", "username": self.username, "target": target,
                       "msg_type": "text", "payload": texto, "timestamp": now_iso()}
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo enviar el mensaje privado: {e}")
                return
            
            clean_text = f"[PRIVADO] {self.username}: {texto}"
            tags = ["privado", "me"]
            with self.history_lock:
                if self.sala_actual not in self.room_histories:
                    self.room_histories[self.sala_actual] = []
                self.room_histories[self.sala_actual].append((clean_text, tags))
            self.mostrar_mensaje(clean_text, tags)

        else:
            obj = {"action": "message", "username": self.username, "room": self.sala_actual,
                   "msg_type": "text", "payload": texto, "timestamp": now_iso()}
        
        self.send_json(obj)
        self.entry_mensaje.delete(0, tk.END)

    def toggle_audio_recording(self):
        if self.is_recording:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        if not self.sala_actual:
            messagebox.showinfo("Info", "Únete a una sala primero para grabar audio.")
            return
            
        self.is_recording = True
        self.btn_audio.config(text="STOP ◼️")
        self.audio_frames = []
        
        t = threading.Thread(target=self._record_loop, daemon=True)
        t.start()
        
    def _record_loop(self):
        try:
            self.audio_stream = self.pyaudio_instance.open(format=FORMAT,
                                                           channels=CHANNELS,
                                                           rate=RATE,
                                                           input=True,
                                                           frames_per_buffer=CHUNK)
            while self.is_recording:
                data = self.audio_stream.read(CHUNK)
                self.audio_frames.append(data)
                
        except Exception as e:
            print(f"Error en el hilo de grabación: {e}")
            self.ventana.after(0, lambda: messagebox.showerror("Error de Micrófono", f"No se pudo iniciar la grabación. ¿Micrófono conectado?\n{e}"))
            self.ventana.after(0, lambda: self.btn_audio.config(text="🎙️ Grabar"))
            self.is_recording = False
            
        finally:
            if self.audio_stream:
                self.audio_stream.stop_stream()
                self.audio_stream.close()
            self.audio_stream = None
            
            if self.audio_frames:
                try:
                    wf = wave.open(TEMP_AUDIO_FILENAME, 'wb')
                    wf.setnchannels(CHANNELS)
                    wf.setsampwidth(self.pyaudio_instance.get_sample_size(FORMAT))
                    wf.setframerate(RATE)
                    wf.writeframes(b''.join(self.audio_frames))
                    wf.close()
                    self.ventana.after(0, self.prompt_to_send_audio)
                except Exception as e:
                    print(f"Error al guardar .wav temporal: {e}")
                    self.ventana.after(0, lambda: messagebox.showerror("Error al Guardar", f"No se pudo guardar el archivo .wav temporal: {e}"))
            else:
                print("No se grabaron frames de audio.")

    def stop_recording(self):
        self.is_recording = False 
        self.btn_audio.config(text="🎙️ Grabar")
        
    def prompt_to_send_audio(self):
        if not os.path.exists(TEMP_AUDIO_FILENAME):
            print("El archivo de audio temporal no existe (no se grabó nada).")
            return

        try:
            answer = messagebox.askyesno(
                "Enviar Grabación",
                "Grabación de audio finalizada. ¿Deseas enviarla?"
            )

            if answer:
                self._enviar_archivo_helper("audio", filepath=TEMP_AUDIO_FILENAME)
            else:
                print("Envío de audio cancelado por el usuario.")

        finally:
            try:
                os.remove(TEMP_AUDIO_FILENAME)
            except Exception as e:
                print(f"No se pudo borrar el archivo temporal: {e}")
            
    def _enviar_archivo_helper(self, msg_type, filepath=None):
        path = filepath
        
        if not path:
            path = filedialog.askopenfilename(title=f"Seleccionar {msg_type}")
        
        if not path:
            return
            
        try:
            size = os.path.getsize(path)
            if size > MAX_FILE_BYTES:
                messagebox.showerror("Error", f"Archivo demasiado grande ({size} bytes). Límite: {MAX_FILE_BYTES} bytes.")
                return
            with open(path, "rb") as f:
                raw = f.read()
            b64 = base64.b64encode(raw).decode("utf-8")
            payload = {"filename": os.path.basename(path), "data": b64}
            obj = {}
            
            clean_text = ""
            tags = []

            if self.sala_actual.startswith("priv_"):
                try:
                    user_pair = self.sala_actual.split('_', 1)[1]
                    user1, user2 = user_pair.split('-')
                    target = user2 if self.username == user1 else user1

                    obj = {"action": "private", "username": self.username, "target": target,
                           "msg_type": msg_type, "payload": payload, "timestamp": now_iso()}
                    
                    clean_text = f"[PRIVADO] {self.username} envió un {msg_type}: {os.path.basename(path)}"
                    tags = ["privado", "me", "info"]

                except Exception as e:
                    messagebox.showerror("Error", f"No se pudo enviar el {msg_type} privado: {e}")
                    return
                
            else:
                obj = {"action": "message", "username": self.username, "room": self.sala_actual,
                       "msg_type": msg_type, "payload": payload, "timestamp": now_iso()}
                
                clean_text = f"[{self.sala_actual}] {self.username} envió un {msg_type}: {os.path.basename(path)}"
                tags = ["me", "info"]
            
            with self.history_lock:
                if self.sala_actual not in self.room_histories:
                    self.room_histories[self.sala_actual] = []
                self.room_histories[self.sala_actual].append((clean_text, tags))
            self.mostrar_mensaje(clean_text, tags)
            
            self.send_json(obj)
            
        except Exception as e:
            messagebox.showerror(f"Error al enviar {msg_type}", f"Error: {e}")

    def salir(self):
        try:
            if self.sala_actual and not self.sala_actual.startswith("priv_"):
                self.send_json({"action": "leave", "username": self.username, "room": self.sala_actual, "timestamp": now_iso()})
            self.send_json({"action": "unregister", "username": self.username, "timestamp": now_iso()})
        except:
            pass
        self.running = False
        
        try:
            self.pyaudio_instance.terminate()
        except Exception as e:
            print(f"Error al terminar PyAudio: {e}")
            
        try:
            self.sock.close()
        except:
            pass
        self.ventana.destroy()


if __name__ == "__main__":
    ClienteChatUDP()