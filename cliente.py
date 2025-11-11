import socket
import threading
import json
import base64
import os
import tkinter as tk
from tkinter import simpledialog, filedialog, messagebox, scrolledtext
import tkinter.ttk as ttk  # Importar TTK
from datetime import datetime
import pyaudio  # <-- Para grabar audio
import wave     # <-- Para guardar el archivo .wav

SERVER_IP = "127.0.0.1"   # cambiar si el servidor está en otra máquina
SERVER_PORT = 12345
BUFFER_SIZE = 65535
# --- CORRECCIÓN 1: Límite de archivo realista para UDP ---
MAX_FILE_BYTES = 65 * 1024 
# --- Constantes para la grabación de audio ---
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
# --- CORRECCIÓN 2: Tasa de muestreo más baja para grabar más tiempo ---
RATE = 8000  # 8kHz (Calidad de teléfono, ~16KB/s)
TEMP_AUDIO_FILENAME = "temp_recording.wav"
# --- Fin Constantes ---

def now_iso():
    return datetime.utcnow().isoformat() + "Z"


class ClienteChatUDP:
    def __init__(self):
        self.username = simpledialog.askstring("Nombre de usuario", "Ingresa tu nombre de usuario:")
        if not self.username:
            return

        # socket UDP (sin conectar)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("", 0))
        self.server_addr = (SERVER_IP, SERVER_PORT)

        # --- Paleta de colores ---
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
            "me_text": "#a0e0ff"
        }
        
        # --- Definición de fuentes ---
        self.main_font = ("Arial", 15)
        self.header_font = ("Arial", 15, "bold")
        self.button_font = ("Arial", 12, "bold")
        self.status_font = ("Arial", 12)
        
        # --- Almacenes de estado ---
        self.room_histories = {}
        self.history_lock = threading.Lock()
        
        self.file_cache = {}
        self.file_lock = threading.Lock()
        
        self.public_rooms = [] 
        self.current_users_in_room = [] 
        
        # --- Atributos para grabación ---
        self.is_recording = False
        self.audio_frames = []
        self.audio_stream = None
        self.pyaudio_instance = pyaudio.PyAudio()
        
        # registrar usuario con servidor
        self.send_json({"action": "register", "username": self.username, "timestamp": now_iso()})

        # GUI
        self.sala_actual = None
        self.ventana = tk.Tk()
        self.ventana.title(f"Chat UDP - {self.username}")
        self.ventana.geometry("1400x1000") 
        self.crear_interfaz()

        # listener en hilo
        self.running = True
        t = threading.Thread(target=self.listener_loop, daemon=True)
        t.start()

        self.ventana.protocol("WM_DELETE_WINDOW", self.salir)
        self.ventana.mainloop()

    # ---
    # Sección de GUI (Sin cambios)
    # ---

    def crear_interfaz(self):
        self.ventana.config(bg=self.colores["ventana"])

        # --- Configuración de Estilo TTK ---
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            style.theme_use("default")
        style.configure("TButton", background=self.colores["boton"], foreground=self.colores["texto_boton"], font=self.button_font, relief="flat", padding=4)
        style.map("TButton", background=[("active", self.colores["privado"])])

        # --- Panel de Salas (IZQUIERDA) ---
        self.frame_salas = tk.Frame(self.ventana, width=200, bg=self.colores["panel"])
        self.frame_salas.pack(side=tk.LEFT, fill=tk.Y)
        tk.Label(self.frame_salas, text="Salas", font=self.header_font, bg=self.colores["panel"], fg=self.colores["texto"]).pack(pady=8)
        self.lista_salas_frame = tk.Frame(self.frame_salas, bg=self.colores["panel"])
        self.lista_salas_frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Button(self.frame_salas, text="+ Crear Sala", command=self.crear_sala).pack(pady=5)
        ttk.Button(self.frame_salas, text="Actualizar Salas", command=self.actualizar_salas_publicas).pack(pady=5)
        ttk.Button(self.frame_salas, text="Salir App", command=self.salir).pack(pady=5)

        # --- Panel de Archivos/Usuarios (DERECHA) ---
        self.frame_right = tk.Frame(self.ventana, width=250, bg=self.colores["panel"])
        self.frame_right.pack(side=tk.RIGHT, fill=tk.Y, padx=(5,0))
        
        # Sub-Panel de Archivos
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

        # Sub-Panel de Usuarios
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


        # --- Área de Mensajes (CENTRO) ---
        self.area_mensajes = scrolledtext.ScrolledText(self.ventana, state='disabled', wrap=tk.WORD, bg=self.colores["area_texto"], fg=self.colores["texto"], font=self.main_font)
        self.area_mensajes.pack(padx=8, pady=8, fill=tk.BOTH, expand=True)
        
        self.area_mensajes.tag_config("error", foreground=self.colores["error"])
        self.area_mensajes.tag_config("privado", foreground=self.colores["privado"])
        self.area_mensajes.tag_config("info", foreground=self.colores["info"])
        self.area_mensajes.tag_config("me", justify='right', foreground=self.colores["me_text"])
        self.area_mensajes.tag_config("other", justify='left')

        # --- Barra de Entrada (INFERIOR) ---
        barra = tk.Frame(self.ventana, bg=self.colores["ventana"])
        barra.pack(fill=tk.X, padx=8, pady=6)
        self.entry_mensaje = tk.Entry(barra, bg=self.colores["area_texto"], fg=self.colores["texto"], insertbackground=self.colores["texto"], font=self.main_font)
        self.entry_mensaje.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        ttk.Button(barra, text="Enviar", command=self.enviar_mensaje).pack(side=tk.LEFT, padx=4)
        
        ttk.Button(barra, text="🖼️ Sticker", command=self.enviar_sticker).pack(side=tk.LEFT, padx=4)
        self.btn_audio = ttk.Button(barra, text="🎙️ Grabar", command=self.toggle_audio_recording)
        self.btn_audio.pack(side=tk.LEFT, padx=4)

        # --- Label de Estado ---
        self.lbl_estado = tk.Label(self.ventana, text="No conectado a ninguna sala", font=self.status_font, fg=self.colores["texto_secundario"], bg=self.colores["ventana"])
        self.lbl_estado.pack(padx=8, pady=2)

    # ---
    # Sección de Red y Manejo de Mensajes (Sin cambios)
    # ---

    def send_json(self, obj):
        try:
            payload = json.dumps(obj).encode("utf-8")
            self.sock.sendto(payload, self.server_addr)
        except Exception as e:
            # --- CORRECCIÓN: Mostrar error si el mensaje es demasiado largo ---
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
            
            elif mt in ("sticker", "audio"):
                fn = payload.get("filename", f"{mt}_{int(datetime.utcnow().timestamp())}.dat")
                b64 = payload.get("data")
                file_key = f"[{room_key}] {frm} - {fn} ({datetime.now().strftime('%H:%M:%S')})"
                
                with self.file_lock:
                    self.file_cache[file_key] = (fn, b64)
                
                self.ventana.after(0, lambda: self.lista_files.insert(tk.END, file_key))
                text_to_store = f"[{room_key}] {frm} envió un {mt}: {fn}\n"
                tags_to_apply.append("info")

        elif action == "private":
            frm = msg.get("from")
            mt = msg.get("msg_type")
            payload = msg.get("payload")
            
            room_key = self.get_private_room_key(frm) 
            tags_to_apply = ["privado", "me" if frm == self.username else "other"]

            if mt in ("text", "emoji"):
                text_to_store = f"[PRIVADO] {frm}: {payload}\n"
            
            elif mt in ("sticker", "audio"):
                fn = payload.get("filename", f"priv_{int(datetime.utcnow().timestamp())}.dat")
                b64 = payload.get("data")
                file_key = f"[PRIV] {frm} - {fn} ({datetime.now().strftime('%H:%M:%S')})"
                
                with self.file_lock:
                    self.file_cache[file_key] = (fn, b64)
                
                self.ventana.after(0, lambda: self.lista_files.insert(tk.END, file_key))
                text_to_store = f"[PRIVADO] {frm} envió un {mt}: {fn}\n"
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

        # --- Lógica de Historial (Sin cambios) ---
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

    # ---
    # Sección de Acciones de GUI
    # ---

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

    # --- Funciones de manejo de sala (Sin cambios) ---

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
        self.area_mensajes.config(state='disabled')
        
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

    # ---
    # Sección de Envío
    # ---

    def enviar_mensaje(self):
        texto = self.entry_mensaje.get().strip()
        if not texto:
            return
        if not self.sala_actual:
            messagebox.showinfo("Info", "Únete a una sala primero.")
            return
            
        obj = {}
        if self.sala_actual.startswith("priv_"):
            # --- Enviar como MENSAJE PRIVADO ---
            try:
                user_pair = self.sala_actual.split('_', 1)[1]
                user1, user2 = user_pair.split('-')
                target = user2 if self.username == user1 else user1
                
                obj = {"action": "private", "username": self.username, "target": target,
                       "msg_type": "text", "payload": texto, "timestamp": now_iso()}
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo enviar el mensaje privado: {e}")
                return
            
            # --- Eco local para privados ---
            clean_text = f"[PRIVADO] {self.username}: {texto}"
            tags = ["privado", "me"]
            with self.history_lock:
                if self.sala_actual not in self.room_histories:
                    self.room_histories[self.sala_actual] = []
                self.room_histories[self.sala_actual].append( (clean_text, tags) )
            self.mostrar_mensaje(clean_text, tags)

        else:
            # --- Enviar como MENSAJE DE SALA ---
            obj = {"action": "message", "username": self.username, "room": self.sala_actual,
                   "msg_type": "text", "payload": texto, "timestamp": now_iso()}
        
        self.send_json(obj)
        self.entry_mensaje.delete(0, tk.END)

    # --- Funciones de grabación y envío ---
    
    def enviar_sticker(self):
        # Sticker solo abre el diálogo de archivo
        self._enviar_archivo_helper("sticker")

    def toggle_audio_recording(self):
        """Inicia o detiene la grabación de audio."""
        if self.is_recording:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        """Prepara e inicia el hilo de grabación."""
        if not self.sala_actual:
            messagebox.showinfo("Info", "Únete a una sala primero para grabar audio.")
            return
            
        self.is_recording = True
        self.btn_audio.config(text="STOP ◼️")
        self.audio_frames = [] 
        
        # Iniciar hilo de grabación
        t = threading.Thread(target=self._record_loop, daemon=True)
        t.start()
        
    def _record_loop(self):
        """Función que corre en un hilo separado para grabar audio."""
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
            # Limpieza del stream
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
                    # Avisar al hilo principal que el archivo está listo para el prompt
                    self.ventana.after(0, self.prompt_to_send_audio)
                except Exception as e:
                    print(f"Error al guardar .wav temporal: {e}")
                    self.ventana.after(0, lambda: messagebox.showerror("Error al Guardar", f"No se pudo guardar el archivo .wav temporal: {e}"))
            else:
                print("No se grabaron frames de audio.")

    def stop_recording(self):
        """Avisa al hilo de grabación que se detenga y cambia el botón."""
        self.is_recording = False 
        self.btn_audio.config(text="🎙️ Grabar")
        
    def prompt_to_send_audio(self):
        """Pregunta al usuario si quiere enviar el audio recién grabado."""
        if not os.path.exists(TEMP_AUDIO_FILENAME):
            print("El archivo de audio temporal no existe (no se grabó nada).")
            return

        try:
            # Preguntar al usuario
            answer = messagebox.askyesno(
                "Enviar Grabación",
                "Grabación de audio finalizada. ¿Deseas enviarla?"
            )

            if answer: # Si 'Yes'
                # Enviar el archivo
                self._enviar_archivo_helper("audio", filepath=TEMP_AUDIO_FILENAME)
            else: # Si 'No'
                print("Envío de audio cancelado por el usuario.")

        finally:
            # Borrar el archivo temporal sin importar la respuesta
            try:
                os.remove(TEMP_AUDIO_FILENAME)
            except Exception as e:
                print(f"No se pudo borrar el archivo temporal: {e}")
            
    # --- CORRECCIÓN 3: 'enviar_archivo_helper' ahora hace eco local SIEMPRE ---
    def _enviar_archivo_helper(self, msg_type, filepath=None):
        """Función auxiliar para enviar stickers o audio."""
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
            
            # Preparar el eco local
            clean_text = ""
            tags = []

            if self.sala_actual.startswith("priv_"):
                # --- Enviar como ARCHIVO PRIVADO ---
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
                # --- Enviar como ARCHIVO DE SALA ---
                obj = {"action": "message", "username": self.username, "room": self.sala_actual,
                       "msg_type": msg_type, "payload": payload, "timestamp": now_iso()}
                
                clean_text = f"[{self.sala_actual}] {self.username} envió un {msg_type}: {os.path.basename(path)}"
                tags = ["me", "info"]
            
            # --- Realizar el eco local (para salas públicas Y privadas) ---
            with self.history_lock:
                if self.sala_actual not in self.room_histories:
                    self.room_histories[self.sala_actual] = []
                self.room_histories[self.sala_actual].append( (clean_text, tags) )
            self.mostrar_mensaje(clean_text, tags)
            
            # Enviar el mensaje
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
        
        # --- Limpieza de PyAudio ---
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