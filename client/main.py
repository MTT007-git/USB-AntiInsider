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
import shlex
import json
import sys
import platform
import stat

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"

if IS_WINDOWS:
    import ctypes

def is_admin():
    if IS_WINDOWS:
        return ctypes.windll.shell32.IsUserAnAdmin()
    else:
        return os.geteuid() == 0

if IS_WINDOWS and not is_admin():
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
elif IS_LINUX and not is_admin():
    print("Warning: Running without root privileges. Lock/unlock operations will fail.")

dotenv.load_dotenv(".env")

ignore_paths = []
alert_paths = []
filter_mode = "ignore"  # "ignore" or "alert"
is_monitoring = False
current_drives = set()
current_removable_drives = set()
pending_updates = [(None, "system", "info", "boot")]
handlers = {}
locked_files_metadata = {}  # Track original ownership: {path: (uid, gid, mode)}
last_server_contact = time.time()
server_offline_alerted = False


def handler(cmd):
    def decorator(func):
        handlers[cmd] = func
    return decorator


def send_update(data, do_ignore=False, text_ignore=""):
    if do_ignore:
        if filter_mode == "alert":
            # Whitelist mode: only send if matches alert rule
            if not check_alert(text_ignore):
                return
        else:
            # Blacklist mode: don't send if matches ignore rule
            if not check_ignore(text_ignore):
                return
    pending_updates.append(data)


def check_ignore(path):
    for i in ignore_paths:
        if re.fullmatch(i, path.replace("\\", "/")) is not None:
            return False
    return True


def check_alert(path):
    if not alert_paths:
        return True
    for i in alert_paths:
        if re.fullmatch(i, path.replace("\\", "/")) is not None:
            return True
    return False


def get_all_drives():
    drives = []
    for part in psutil.disk_partitions(all=False):
        if IS_WINDOWS:
            drives.append(part.device)
        else:
            drives.append(part.mountpoint)
    return set(drives)


def get_removable_drives():
    drives = []
    if IS_WINDOWS:
        for part in psutil.disk_partitions(all=False):
            if "removable" in part.opts.lower():
                drives.append(part.device)
    else:
        for part in psutil.disk_partitions(all=False):
            device = part.device.split('/')[-1].rstrip('0123456789')
            try:
                with open(f'/sys/block/{device}/removable', 'r') as f:
                    if f.read().strip() == '1':
                        drives.append(part.mountpoint)
            except:
                pass
    return set(drives)


@handler("lock")
def lock(usr, cmd, args, tg):
    disk = args[0]
    if not is_admin():
        send_update((usr, cmd, "danger", "The program is not run as admin/root", tg))
        return
    
    if IS_WINDOWS:
        if disk == "C":
            send_update((usr, cmd, "danger", "Cannot lock disk C", tg))
            return
        send_update((usr, cmd, "info", f"Locking disk {disk}...", tg))
        subprocess.run(["mountvol", f"{disk}:", "/D"], check=True)
        send_update((None, cmd, "success", f"Disk {disk} locked", tg))
    else:
        # Linux: find mount point and remount read-only
        for part in psutil.disk_partitions():
            if part.device == disk or part.mountpoint == disk:
                if part.mountpoint in ('/', '/boot', '/usr', '/var'):
                    send_update((usr, cmd, "danger", f"Cannot lock system partition {part.mountpoint}", tg))
                    return
                send_update((usr, cmd, "info", f"Locking {part.mountpoint}...", tg))
                subprocess.run(["mount", "-o", "remount,ro", part.mountpoint], check=True)
                send_update((None, cmd, "success", f"Disk {part.mountpoint} locked", tg))
                return
        send_update((usr, cmd, "danger", "Disk not found", tg))


@handler("release")
def release(usr, cmd, args, tg):
    disk = args[0]
    if not is_admin():
        send_update((usr, cmd, "danger", "The program is not run as admin/root", tg))
        return
    
    if IS_WINDOWS:
        if disk == "C":
            send_update((usr, cmd, "danger", "Cannot release disk C", tg))
            return
        send_update((usr, cmd, "info", f"Releasing disk {disk}...", tg))
        subprocess.run(["mountvol", f"{disk}:", "/L"], check=True)
        send_update((None, cmd, "success", f"Disk {disk} released"))
        threading.Thread(target=watch_drive, args=(f"{disk}:\\",), daemon=True).start()
    else:
        # Linux: find mount point and remount read-write
        for part in psutil.disk_partitions():
            if part.device == disk or part.mountpoint == disk:
                send_update((usr, cmd, "info", f"Releasing {part.mountpoint}...", tg))
                subprocess.run(["mount", "-o", "remount,rw", part.mountpoint], check=True)
                send_update((None, cmd, "success", f"Disk {part.mountpoint} released"))
                threading.Thread(target=watch_drive, args=(part.mountpoint,), daemon=True).start()
                return
        send_update((usr, cmd, "danger", "Disk not found", tg))


@handler("lockfile")
def lockfile(usr, cmd, args, tg):
    path = args[0].replace("\\", "/")
    
    if IS_WINDOWS:
        if path in ("C:", "C:/") or path.startswith("C:/Windows"):
            send_update((usr, cmd, "danger", "Cannot lock system paths", tg))
            return
    else:
        if path in ('/', '/boot', '/usr', '/var', '/etc') or path.startswith(('/boot/', '/usr/', '/var/', '/etc/')):
            send_update((usr, cmd, "danger", "Cannot lock system paths", tg))
            return
    
    if not os.path.exists(path):
        send_update((usr, cmd, "danger", "Path doesn't exist", tg))
        return
    
    if not is_admin():
        send_update((usr, cmd, "danger", "The program is not run as admin/root", tg))
        return
    
    try:
        if IS_WINDOWS:
            cmds = [
                f'icacls "{path}" /inheritance:r',
                f'icacls "{path}" /grant:r SYSTEM:(OI)(CI)F',
                f'icacls "{path}" /deny *S-1-1-0:(OI)(CI)(F)'
            ]
            for cmd_ in cmds:
                subprocess.run(shlex.split(cmd_), check=True)
        else:
            # Store original ownership and permissions
            file_stat = os.stat(path)
            locked_files_metadata[path] = (file_stat.st_uid, file_stat.st_gid, file_stat.st_mode)
            
            # Change ownership to root and remove all permissions
            subprocess.run(["chown", "root:root", path], check=True)
            subprocess.run(["chmod", "000", path], check=True)
            subprocess.run(["chattr", "+i", path], check=True)
        
        send_update((None, cmd, "success", f"{'File' if os.path.isfile(path) else 'Folder'} `{path}` locked", tg))
    except Exception as e:
        send_update((usr, cmd, "danger", f"Failed to lock: {str(e)}", tg))


@handler("releasefile")
def releasefile(usr, cmd, args, tg):
    path = args[0].replace("\\", "/")
    
    if IS_WINDOWS:
        if path in ("C:", "C:/") or path.startswith("C:/Windows"):
            send_update((usr, cmd, "danger", "Cannot release system paths", tg))
            return
    else:
        if path in ('/', '/boot', '/usr', '/var', '/etc') or path.startswith(('/boot/', '/usr/', '/var/', '/etc/')):
            send_update((usr, cmd, "danger", "Cannot release system paths", tg))
            return
    
    if not os.path.exists(path):
        send_update((usr, cmd, "danger", "Path doesn't exist", tg))
        return
    
    if not is_admin():
        send_update((usr, cmd, "danger", "The program is not run as admin/root", tg))
        return
    
    try:
        if IS_WINDOWS:
            cmds = [
                f'icacls "{path}" /remove:d *S-1-1-0',
                f'icacls "{path}" /inheritance:e'
            ]
            for cmd_ in cmds:
                subprocess.run(shlex.split(cmd_), check=True)
        else:
            # Remove immutable flag first
            subprocess.run(["chattr", "-i", path], check=True)
            
            # Restore original ownership and permissions if tracked
            if path in locked_files_metadata:
                uid, gid, mode = locked_files_metadata[path]
                subprocess.run(["chown", f"{uid}:{gid}", path], check=True)
                os.chmod(path, stat.S_IMODE(mode))
                del locked_files_metadata[path]
            else:
                # Default: restore reasonable permissions
                subprocess.run(["chmod", "644", path], check=True)
        
        send_update((None, cmd, "success", f"{'File' if os.path.isfile(path) else 'Folder'} `{path}` released", tg))
    except Exception as e:
        send_update((usr, cmd, "danger", f"Failed to release: {str(e)}", tg))


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
    if not os.path.exists(drive):
        send_update((None, "monitoring", "info", f"Skipping `{drive.replace('\\', '/')}` - path doesn't exist"))
        return
    
    usb_handler = USBHandler()
    observer = Observer()
    
    try:
        observer.schedule(usb_handler, drive, recursive=True)
        observer.start()
        send_update((None, "monitoring", "info", f"Monitoring `{drive.replace('\\', '/')}`"))
    except Exception as e:
        send_update((None, "monitoring", "info", f"Cannot monitor `{drive.replace('\\', '/')}: {str(e)}`"))
        return
    
    try:
        while is_monitoring and drive in current_drives:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    observer.stop()
    observer.join()
    send_update((None, "monitoring", "info", f"Stopped monitoring `{drive.replace('\\', '/')}`"))


@handler("ignorelist")
def ignorelist_update(usr, cmd, args, tg):
    global ignore_paths
    ignore_paths = args
    if usr:
        send_update((usr, cmd, "success", "Done", tg))
    else:
        send_update((None, cmd, "success", "Done"))


@handler("alertlist")
def alertlist_update(usr, cmd, args, tg):
    global alert_paths
    alert_paths = args
    if usr:
        send_update((usr, cmd, "success", "Done", tg))
    else:
        send_update((None, cmd, "success", "Done"))


@handler("setfilter")
def setfilter(usr, cmd, args, tg):
    global filter_mode
    if args and args[0] in ("ignore", "alert"):
        filter_mode = args[0]
        if usr:
            send_update((usr, cmd, "success", f"Filter mode set to {filter_mode}", tg))
        else:
            send_update((None, cmd, "success", f"Filter mode set to {filter_mode}"))
    else:
        if usr:
            send_update((usr, cmd, "danger", "Invalid filter mode. Use 'ignore' or 'alert'", tg))
        else:
            send_update((None, cmd, "danger", "Invalid filter mode"))


@handler("listdir")
@handler("ls")
def listdir(usr, cmd, args, tg):
    path = args[0].replace("\\", "/")
    if not path.endswith("/"):
        path += "/"
    if not os.path.exists(path):
        send_update((usr, cmd, "danger", "Path doesn't exist", tg))
        return
    if not os.path.isdir(path):
        send_update((usr, cmd, "danger", "Path is not a directory", tg))
        return
    try:
        send_update((usr, cmd, "info", f"Directory of `{path}`\n" +
                     "\n".join([f"> `{path + i.rstrip("/")}/`" for i in os.listdir(path) if os.path.isdir(path + i)]) + "\n" +
                     "\n".join([f"   `{path + i}`" for i in os.listdir(path) if not os.path.isdir(path + i)]), tg))
    except Exception as e:
        if "Permission denied" in str(e) or "Access is denied" in str(e):
            send_update((usr, cmd, "danger", "Permission denied", tg))
        else:
            send_update((usr, cmd, "danger", "Unknown error"), tg)
            print(e)


@handler("cat")
def cat(usr, cmd, args, tg):
    path = args[0].replace("\\", "/")
    if not os.path.exists(path):
        send_update((usr, cmd, "danger", "Path doesn't exist", tg))
        return
    if not os.path.isfile(path):
        send_update((usr, cmd, "danger", "Path is not a file", tg))
        return
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(10000)  # Limit to 10KB
            if len(content) == 10000:
                content += "\n... (truncated)"
            send_update((usr, cmd, "info", f"Contents of `{path}`:\n```\n{content}\n```", tg))
    except Exception as e:
        if "Permission denied" in str(e) or "Access is denied" in str(e):
            send_update((usr, cmd, "danger", "Permission denied", tg))
        else:
            send_update((usr, cmd, "danger", f"Error reading file: {str(e)}"), tg)
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
                send_update((None, cmd, "info", f"Removable drive found: `{d.replace('\\', '/')}`"))
            else:
                send_update((None, cmd, "info", f"Drive found: `{d.replace('\\', '/')}`"))
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

    # On Linux, add common user directories for monitoring
    if IS_LINUX:
        user_dirs = ['/home', '/tmp', '/opt', '/srv', '/media', '/mnt']
        for d in user_dirs:
            if os.path.exists(d) and d not in current_drives:
                current_drives.add(d)

    for d in current_drives:
        if d in current_removable_drives:
            send_update((None, "monitoring", "info", f"Removable drive found: `{d.replace('\\', '/')}`"))
        else:
            send_update((None, "monitoring", "info", f"Drive found: `{d.replace('\\', '/')}`"))
        t = threading.Thread(target=watch_drive, args=(d,), daemon=True)
        t.start()
        watched_threads[d] = t

    while is_monitoring:
        new_drives = get_all_drives()
        new_removable_drives = get_removable_drives()
        
        # Re-add user directories on Linux
        if IS_LINUX:
            for d in user_dirs:
                if os.path.exists(d):
                    new_drives.add(d)
        
        added = new_drives - current_drives
        removed = current_drives - new_drives

        for d in added:
            if d in new_removable_drives:
                send_update((None, "monitoring", "info", f"Removable drive inserted: `{d.replace('\\', '/')}`"))
            else:
                send_update((None, "monitoring", "info", f"Non-removable drive inserted: `{d.replace('\\', '/')}`"))
            t = threading.Thread(target=watch_drive, args=(d,), daemon=True)
            t.start()
            watched_threads[d] = t

        for d in removed:
            if d in current_removable_drives:
                send_update((None, "monitoring", "info", f"Removable drive removed: `{d.replace('\\', '/')}`"))
            else:
                send_update((None, "monitoring", "info", f"Non-removable drive removed: `{d.replace('\\', '/')}`"))
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
        time.sleep(1)
        continue
    pending_updates.clear()
    for command in result["commands"]:
        if command[1] not in handlers:
            print(f"Unknown command \"{command[1]}\" with arguments {command[2:]} from user {command[0]}")
            continue
        print(command)
        try:
            handlers[command[1]](command[0], command[1], command[2:-1], command[-1])
        except Exception as ex:
            print(f"Exeption: {ex}")
    time.sleep(1)
