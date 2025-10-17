import os
import json
import asyncio
import datetime
import threading
import tkinter as tk
from tkinter import messagebox, ttk
import websockets
import re
import time

# --- Config Manager ---
class ConfigManager:
    def __init__(self, path):
        self.path = path

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Failed to load config: {e}")
        return {}

    def save(self, config):
        try:
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            print(f"Failed to save config: {e}")

# --- Logger with tag coloring ---
class Logger:
    def __init__(self, widget, log_file, tag_colors, tag_whitelist):
        self.widget = widget
        self.log_file = log_file
        self.tag_colors = tag_colors
        self.tag_color_map = {}
        self.tag_whitelist = tag_whitelist

    def log(self, message):
        self.widget.configure(state="normal")
        tags = re.findall(r"\[[^\]]+\]", message)
        for tag in tags:
            if tag not in self.tag_whitelist:
                continue
            if tag not in self.tag_color_map:
                self.tag_color_map[tag] = self.tag_colors[len(self.tag_color_map) % len(self.tag_colors)]
            try:
                if not self.widget.tag_cget(tag, "foreground"):
                    self.widget.tag_config(tag, foreground=self.tag_color_map[tag])
            except tk.TclError:
                self.widget.tag_config(tag, foreground=self.tag_color_map[tag])
        start_index = self.widget.index(tk.END)
        self.widget.insert(tk.END, message + "\n")
        for tag in tags:
            if tag not in self.tag_whitelist:
                continue
            tag_start = message.find(tag)
            tag_end = tag_start + len(tag)
            self.widget.tag_add(tag, f"{start_index}+{tag_start}c", f"{start_index}+{tag_end}c")
        self.widget.see(tk.END)
        self.widget.configure(state="disabled")
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(message + "\n")
        except Exception as e:
            print(f"Failed to write log: {e}")

# --- Player Manager ---
class PlayerManager:
    def __init__(self, treeview):
        self.tree = treeview

    def update(self, message):
        lines = message.splitlines()
        player_lines = [line for line in lines if re.match(r"^\s*\d+", line)]
        self.tree.delete(*self.tree.get_children())
        for line in player_lines:
            parts = re.split(r"\s{2,}|\t", line.strip())
            if len(parts) >= 6:
                name, ping, steamid, connected = parts[1], parts[2], parts[3], parts[4]
                self.tree.insert("", "end", values=(name, ping, steamid, connected))

    def filter(self, query):
        q = query.lower()
        for item in self.tree.get_children():
            values = self.tree.item(item)["values"]
            if any(q in str(v).lower() for v in values):
                self.tree.reattach(item, '', 'end')
            else:
                self.tree.detach(item)

    def sort(self, col, reverse):
        data = [(self.tree.set(k, col), k) for k in self.tree.get_children('')]
        data.sort(reverse=reverse)
        for index, (_, k) in enumerate(data):
            self.tree.move(k, '', index)

# --- Main GUI + WebSocket ---
class WebRCONApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Rust Admin Tool (R.A.T.)")
        self.geometry("900x600")
        self.minsize(200, 200)

        self.CONFIG_PATH = os.path.join(os.environ["USERPROFILE"], "Documents", "RAT_config.JSON")
        self.LOG_PATH = os.path.join(os.environ["USERPROFILE"], "Documents", "RAT_log.JSON")

        self.DEFAULT_IP = "SET_YOUR_SERVER_IP_HERE"
        self.DEFAULT_PORT = PORT_NUMBER_HERE
        self.DEFAULT_PASSWORD = "ADMIN_PASSWORD_HERE"
        self.TAG_COLORS = ["red", "blue", "green", "orange", "purple", "brown", "cyan", "magenta"]
        self.TAG_WHITELIST = {"[OK]", "[ERROR]", "[WARN]", "[INFO]", "[Chat]", "[Server]", "[Command]", "[Players]", "[Hostname]", "[Version]", "[Map]"}

        self.config_mgr = ConfigManager(self.CONFIG_PATH)
        self.loop = asyncio.new_event_loop()
        self.websocket = None
        self.connected = False
        self._connecting = False
        self._receiver_running = False
        self.identifier_counter = 1
        self.last_status_time = 0
        self.status_interval = 15

        threading.Thread(target=self._run_loop, daemon=True).start()
        self._init_ui()

    def _init_ui(self):
        config = self.config_mgr.load()
        ip = config.get("ip", self.DEFAULT_IP)
        port = config.get("port", self.DEFAULT_PORT)
        password = config.get("password", self.DEFAULT_PASSWORD)

        # Menu
        menubar = tk.Menu(self)
        server_menu = tk.Menu(menubar, tearoff=0)
        server_menu.add_command(label="Connect", command=self._connect)
        server_menu.add_command(label="Disconnect", command=self._disconnect)
        menubar.add_cascade(label="Server", menu=server_menu)
        self.config(menu=menubar)

        # Top connection bar
        top = tk.Frame(self)
        top.pack(fill=tk.X, padx=10, pady=5)
        tk.Label(top, text="IP:").pack(side=tk.LEFT)
        self.ip_entry = tk.Entry(top, width=15)
        self.ip_entry.insert(0, ip)
        self.ip_entry.pack(side=tk.LEFT, padx=2)
        tk.Label(top, text="Port:").pack(side=tk.LEFT)
        self.port_entry = tk.Entry(top, width=6)
        self.port_entry.insert(0, str(port))
        self.port_entry.pack(side=tk.LEFT, padx=2)
        tk.Label(top, text="Password:").pack(side=tk.LEFT)
        self.password_entry = tk.Entry(top, show="*", width=12)
        self.password_entry.insert(0, password)
        self.password_entry.pack(side=tk.LEFT, padx=2)

        # Console + players
        mid = tk.Frame(self)
        mid.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.tabs = ttk.Notebook(mid)
        self.console_tab = tk.Text(self.tabs, wrap=tk.WORD, state="disabled")
        self.tabs.add(self.console_tab, text="Console")
        player_tab = tk.Frame(self.tabs)
        search_frame = tk.Frame(player_tab)
        search_frame.pack(fill=tk.X, padx=5, pady=2)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.players.filter(self.search_var.get()))
        tk.Entry(search_frame, textvariable=self.search_var).pack(fill=tk.X, expand=True)
        self.tree = ttk.Treeview(player_tab, columns=("Name", "Ping", "SteamID", "Connected"), show="headings")
        for col in self.tree["columns"]:
            self.tree.heading(col, text=col, command=lambda c=col: self.players.sort(c, False))
            self.tree.column(col, anchor="center")
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tabs.add(player_tab, text="Players")
        self.tabs.pack(fill=tk.BOTH, expand=True)
        self.players = PlayerManager(self.tree)

        # Bottom bar
        bot = tk.Frame(self)
        bot.pack(fill=tk.X, padx=10, pady=5)
        tk.Label(bot, text="Command:").pack(side=tk.LEFT)
        self.command_entry = tk.Entry(bot)
        self.command_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.command_entry.bind("<Return>", self._send_command)
        tk.Button(bot, text="Send", command=self._send_command).pack(side=tk.LEFT)

        # Logger
        self.logger = Logger(self.console_tab, self.LOG_PATH, self.TAG_COLORS, self.TAG_WHITELIST)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _connect(self):
        if self.connected or self._connecting:
            self.logger.log("[WARN] Already connected or connecting.")
            return
        self._connecting = True
        ip = self.ip_entry.get()
        port = int(self.port_entry.get())
        password = self.password_entry.get()
        self.config_mgr.save({"ip": ip, "port": port, "password": password})

        def run():
            async def do_connect():
                try:
                    self.websocket = await websockets.connect(f"ws://{ip}:{port}/{password}", ping_interval=None)
                    self.connected = True
                    self.logger.log(f"[OK] Connected to {ip}:{port}")
                    self._start_receiver()
                    self._start_status_polling()
                    await self._send_json_command("status")
                except Exception as e:
                    self.logger.log(f"[ERROR] {e}")
                finally:
                    self._connecting = False
            asyncio.run_coroutine_threadsafe(do_connect(), self.loop)

        threading.Thread(target=run, daemon=True).start()

    def _disconnect(self):
        self._receiver_running = False
        if self.websocket:
            asyncio.run_coroutine_threadsafe(self.websocket.close(), self.loop)
        self.websocket = None
        self.connected = False
        self.logger.log("[WARN] Disconnected.")

    def _send_command(self, event=None):
        command = self.command_entry.get().strip().strip('"')
        if self.connected and command:
            self.logger.log(f"[Command] {command}")
            asyncio.run_coroutine_threadsafe(self._send_json_command(command), self.loop)
            self.command_entry.delete(0, tk.END)

    def _start_receiver(self):
        async def receive():
            self.logger.log("[INFO] Listening for server messages...")
            self._receiver_running = True
            try:
                while self._receiver_running and self.websocket:
                    data = await self.websocket.recv()
                    self._handle_message(data)
            except Exception as e:
                self.logger.log(f"[ERROR] {e}")
            self._receiver_running = False
        asyncio.run_coroutine_threadsafe(receive(), self.loop)

    def _start_status_polling(self):
        async def poll():
            while self.connected:
                now = time.time()
                if now - self.last_status_time >= self.status_interval:
                    await self._send_json_command("status")
                    self.last_status_time = now
                await asyncio.sleep(1)
        asyncio.run_coroutine_threadsafe(poll(), self.loop)

    def _handle_message(self, raw):
        timestamp = datetime.datetime.now().strftime("[%H:%M:%S] ")
        try:
            if isinstance(raw, str):
                msg = json.loads(raw)
                mtype = msg.get("Type", "")
                body = msg.get("Message", "")
                if mtype == "Chat":
                    chat = json.loads(body)
                    user = chat.get("Username", "Unknown")
                    text = chat.get("Message", "")
                    self.logger.log(f"{timestamp}[Chat][{user}] {text}")
                elif mtype == "Generic":
                    cleaned = body.replace("\r", "").strip()
                    self.logger.log(f"{timestamp}[Server] {cleaned}")
                    self.players.update(cleaned)
                else:
                    self.logger.log(f"{timestamp}[{mtype}] {body}")
            else:
                self.logger.log(f"{timestamp}[ERROR] Unexpected data: {raw}")
        except Exception as e:
            self.logger.log(f"[ERROR] Failed to parse message: {e}")

    async def _send_json_command(self, command):
        msg = {
            "Identifier": self.identifier_counter,
            "Message": command,
            "Name": "WebRcon",
            "Type": 2
        }
        self.identifier_counter += 1
        await self.websocket.send(json.dumps(msg))

    def _on_close(self):
        self._disconnect()
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.destroy()

if __name__ == "__main__":
    app = WebRCONApp()
    app.mainloop()