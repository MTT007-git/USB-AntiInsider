"""
Main script for background use
Client
"""
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
import psutil
import os
import dotenv
import time
import re
import subprocess
import threading
import tempfile
import requests
import base64
import ctypes
import shlex
import json
import sys

if not ctypes.windll.shell32.IsUserAnAdmin():
    print("USB-Antiinsider needs administrator to lock and release USB drives\n"
          "A UAC (User Account Control) prompt will appear\n"
          "Click \"Yes\" to allow /lock and /release\n"
          "Click \"No\" to continue running the program at user level")
    time.sleep(2)
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 3)
    if result <= 32:
        if result == 5:
            print("Access denied, continuing without administrator - /lock and /release will not work")
        else:
            print(f"Elevation failed (error code {result}), continuing without administrator - "
                  "/lock and /release will not work")
    else:
        print("UAC prompt accepted, new process started")
        exit(0)

dotenv.load_dotenv(".env")

ignore_paths = []
is_monitoring = False
current_drives = set()
current_removable_drives = set()
pending_updates = [(None, "system", "info", "boot")]
handlers = {}


def handler(cmd):
    def decorator(func):
        handlers[cmd] = func
    return decorator


def send_update(data, do_ignore=False, text_ignore=""):
    if do_ignore and not check_ignore(text_ignore):
        return
    pending_updates.append(data)


def check_ignore(path):
    for i in ignore_paths:
        if re.fullmatch(i, path.replace("\\", "/")) is not None:
            return False
    return True


def get_all_drives():
    drives = []
    for part in psutil.disk_partitions(all=False):
        drives.append(part.device)
    return set(drives)


def get_removable_drives():
    drives = []
    for part in psutil.disk_partitions(all=False):
        if "removable" in part.opts.lower():
            drives.append(part.device)
    return set(drives)


def get_disk_number_from_letter(letter):
    ps_script = rf"""
        $d = Get-Partition -DriveLetter {letter} -ErrorAction SilentlyContinue
        if ($d) {{
            $disk = Get-Disk -Number $d.DiskNumber
            [PSCustomObject]@{{
                DriveLetter = '{letter}'
                DiskNumber  = $d.DiskNumber
                PartitionNumber = $d.PartitionNumber
                Model = $disk.FriendlyName
                SizeGB = [math]::Round($disk.Size/1GB, 1)
            }} | ConvertTo-Json
        }}
        """
    res = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_script],
        capture_output=True, text=True
    )

    if not res.stdout.strip():
        print(f"No disk found for {letter}:\\")
        print("Output:", res.stderr)
        return None

    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError:
        print("Failed to parse PowerShell output:", res.stdout)
        return None


@handler("lock")
def lock(usr, cmd, args, tg):
    disk = args[0]
    if disk == "C":
        send_update((usr, cmd, "danger", "Cannot lock disk C", tg))
        return
    if not ctypes.windll.shell32.IsUserAnAdmin():
        send_update((usr, cmd, "danger", "The program is not run as admin", tg))
        return
    send_update((usr, cmd, "info", f"Locking disk {disk}...", tg))
    disk_number = get_disk_number_from_letter(disk)
    if disk_number is None or "DiskNumber" not in disk_number:
        send_update((usr, cmd, "danger", f"The disk {disk} doesn't exist", tg))
        return
    script = f"select disk {disk_number["DiskNumber"]}\nattributes disk set readonly\nexit\n"
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt") as f:
        f.write(script)
        path = f.name
    subprocess.run(["diskpart", "/s", path], check=True)
    send_update((None, cmd, "success", f"Disk {disk} locked", tg))
    watch_drive(f"{disk}:\\")


@handler("release")
def release(usr, cmd, args, tg):
    disk = args[0]
    if disk == "C":
        send_update((usr, cmd, "danger", "Cannot release disk C", tg))
        return
    if not ctypes.windll.shell32.IsUserAnAdmin():
        send_update((usr, cmd, "danger", "The program is not run as admin", tg))
        return
    send_update((usr, cmd, "info", f"Releasing disk {disk}...", tg))
    disk_number = get_disk_number_from_letter(disk)
    if disk_number is None or "DiskNumber" not in disk_number:
        send_update((usr, cmd, "danger", f"The disk {disk} doesn't exist", tg))
        return
    script = f"select disk {disk_number["DiskNumber"]}\nattributes disk clear readonly\nexit\n"
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt") as f:
        f.write(script)
        path = f.name
    subprocess.run(["diskpart", "/s", path], check=True)
    send_update((None, cmd, "success", f"Disk {disk} released"))
    watch_drive(f"{disk}:\\")


@handler("lockfile")
def lockfile(usr, cmd, args, tg):
    path = args[0].replace("\\", "/")
    if path in ("C:", "C:/") or path.startswith("C:/Windows"):
        send_update((usr, cmd, "danger", "Cannot lock disk C", tg))
        return
    if not os.path.exists(path):
        send_update((usr, cmd, "danger", "Path doesn't exist", tg))
        return
    cmds = [
        f'icacls "{path}" /inheritance:r',
        f'icacls "{path}" /grant:r SYSTEM:(OI)(CI)F',
        f'icacls "{path}" /grant:r Administrators:(OI)(CI)F',
        f'icacls "{path}" /deny Users:(OI)(CI)(W,R,M,D,RX)'
    ]
    for cmd_ in cmds:
        subprocess.run(shlex.split(cmd_), check=True)
    send_update((None, cmd, "success", f"{'File' if os.path.isfile(path) else 'Folder'} `{path}` locked"))


@handler("releasefile")
def releasefile(usr, cmd, args, tg):
    path = args[0].replace("\\", "/")
    if path in ("C:", "C:/") or path.startswith("C:/Windows"):
        send_update((usr, cmd, "danger", "Cannot release disk C", tg))
        return
    if not os.path.exists(path):
        send_update((usr, cmd, "danger", "Path doesn't exist", tg))
        return
    cmds = [
        f'icacls "{path}" /remove:d Users',
        f'icacls "{path}" /inheritance:e'
    ]
    for cmd_ in cmds:
        subprocess.run(shlex.split(cmd_), check=True)
    send_update((None, cmd, "success", f"{'File' if os.path.isfile(path) else 'Folder'} `{path}` released"))


class USBHandler(FileSystemEventHandler):
    def on_created(self, event):
        send_update((None, "monitoring", "info", f"[+] File created:\n`{event.src_path.replace('\\', '/')}`"), True,
                    event.src_path.replace('\\', '/'))

    def on_deleted(self, event):
        send_update((None, "monitoring", "info", f"[-] File deleted:\n`{event.src_path.replace('\\', '/')}`"), True,
                    event.src_path.replace('\\', '/'))

    def on_modified(self, event):
        if os.path.isfile(event.src_path):
            send_update((None, "monitoring", "info", f"[~] File modified:\n`{event.src_path.replace('\\', '/')}`"),
                        True, event.src_path.replace('\\', '/'))

    def on_moved(self, event):
        send_update((None, "monitoring", "info", f"[>] File moved:\n`{event.src_path.replace('\\', '/')}`\n"
                                                 f"v\n`{event.dest_path.replace('\\', '/')}`"),
                    True, event.src_path.replace('\\', '/'))


def watch_drive(drive):
    usb_handler = USBHandler()
    observer = Observer()
    observer.schedule(usb_handler, drive, recursive=True)
    observer.start()
    send_update((None, "monitoring", "info", f"Monitoring {drive.replace('\\', '/')}"))
    try:
        while is_monitoring and drive in current_drives:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    observer.stop()
    observer.join()
    send_update((None, "monitoring", "info", f"Stopped monitoring {drive.replace('\\', '/')}"))


@handler("ignorelist")
def ignorelist_update(usr, cmd, args, tg):
    global ignore_paths
    ignore_paths = args
    if usr:
        send_update((usr, cmd, "success", "Done", tg))
    else:
        send_update((None, cmd, "success", "Done"))


@handler("listdir")
def listdir(usr, cmd, args, tg):
    path = args[0].replace("\\", "/").strip("/") + "/"
    if not os.path.exists(path):
        send_update((usr, cmd, "danger", "Path doesn't exist", tg))
        return
    if not os.path.isdir(path):
        send_update((usr, cmd, "danger", "Path is not a directory", tg))
        return
    try:
        send_update((usr, cmd, "info", f"Directory of `{path}`\n" +
                     "\n".join([f"> `{path + i}`" for i in os.listdir(path) if os.path.isdir(path + i)]) + "\n" +
                     "\n".join([f"   `{path + i}`" for i in os.listdir(path) if not os.path.isdir(path + i)]), tg))
    except Exception as e:
        if "Permission denied" in str(e) or "Access is denied" in str(e):
            send_update((usr, cmd, "danger", "Permission denied", tg))
        else:
            send_update((usr, cmd, "danger", "Unknown error"), tg)
            print(e)


@handler("download")
def download(usr, cmd, args, tg):
    path = args[0]
    if not os.path.exists(path):
        send_update((usr, cmd, "danger", "Path doesn't exist", tg))
        return
    if not os.path.isfile(path):
        send_update((usr, cmd, "danger", "Path is not a file", tg))
        return
    send_update((usr, cmd, "info", "Downloading...", tg))
    try:
        with open(path, "rb") as f:
            send_update((usr, cmd, "success", f"`{path}`", base64.b64encode(f.read()).decode(), tg))
    except Exception as e:
        if "Permission denied" in str(e) or "Access is denied" in str(e):
            send_update((usr, cmd, "danger", "Permission denied", tg))
        else:
            send_update((usr, cmd, "danger", "Unknown error", tg))
            print(e)


@handler("upload")
def upload(usr, cmd, args, tg):
    path = args[0].replace("\\", "/")
    if os.path.exists(path):
        send_update((usr, cmd, "danger", "A file with this name already exists", tg))
        return
    send_update((usr, cmd, "info", "Uploading...", tg))
    try:
        with open(path, "wb") as f:
            f.write(base64.b64decode(args[1]))
            send_update((usr, cmd, "success", f"Uploaded file at `{path}`", tg))
    except Exception as e:
        if "Permission denied" in str(e) or "Access is denied" in str(e):
            send_update((usr, cmd, "danger", "Permission denied", tg))
        else:
            send_update((usr, cmd, "danger", "Unknown error", tg))
            print(e)


@handler("start")
def start(usr, cmd, args, tg):
    send_update((None, cmd, "info", "Monitoring USB drives"))
    if is_monitoring:
        for d in current_drives:
            if d in current_removable_drives:
                send_update((None, cmd, "info", f"Removable drive found: {d.replace('\\', '/')}"))
            else:
                send_update((None, cmd, "info", f"Drive found: {d.replace('\\', '/')}"))
    else:
        threading.Thread(target=monitor, daemon=True).start()


def monitor():
    global current_drives, current_removable_drives, is_monitoring
    if is_monitoring:
        return
    is_monitoring = True
    print("Started monitoring")
    current_drives = get_all_drives()
    current_removable_drives = get_removable_drives()
    watched_threads = {}

    for d in current_drives:
        if d in current_removable_drives:
            send_update((None, "monitoring", "info", f"Removable drive found: {d.replace('\\', '/')}"))
        else:
            send_update((None, "monitoring", "info", f"Drive found: {d.replace('\\', '/')}"))
        t = threading.Thread(target=watch_drive, args=(d,), daemon=True)
        t.start()
        watched_threads[d] = t

    while is_monitoring:
        new_drives = get_all_drives()
        new_removable_drives = get_removable_drives()
        added = new_drives - current_drives
        removed = current_drives - new_drives

        for d in added:
            if d in new_removable_drives:
                send_update((None, "monitoring", "info", f"Removable drive inserted: {d.replace('\\', '/')}"))
            else:
                send_update((None, "monitoring", "info", f"Non-removable drive inserted: {d.replace('\\', '/')}"))
            t = threading.Thread(target=watch_drive, args=(d,), daemon=True)
            t.start()
            watched_threads[d] = t

        for d in removed:
            if d in current_removable_drives:
                send_update((None, "monitoring", "info", f"Removable drive removed: {d.replace('\\', '/')}"))
            else:
                send_update((None, "monitoring", "info", f"Non-removable drive removed: {d.replace('\\', '/')}"))
            watched_threads.pop(d, None)

        current_drives = new_drives
        current_removable_drives = new_removable_drives
        time.sleep(1)
    print("Stopped monitoring")


@handler("stop")
def stop(usr, cmd, args, tg):
    global is_monitoring
    if is_monitoring:
        send_update((usr, cmd, "success", "Stopped monitoring USB drives", tg))
        is_monitoring = False
    else:
        send_update((usr, cmd, "info", "Already not monitoring", tg))


while True:
    try:
        result = requests.post(os.getenv("USB_SERVER_ADDRESS"),
                               headers={"Authorization": f"Bearer {os.getenv('USB_TOKEN')}"},
                               json={"updates": pending_updates})
        if not result.ok:
            print(f"Error code {result.status_code}: {result.json()}")
            continue
        result = result.json()
    except Exception as ex:
        print(f"Error: {ex}")
        continue
    pending_updates.clear()
    for command in result["commands"]:
        if command[1] not in handlers:
            print(f"Unknown command \"{command[1]}\" with arguments {command[2:]} from user {command[0]}")
            continue
        print(command)
        handlers[command[1]](command[0], command[1], command[2:-1], command[-1])
    time.sleep(1)
