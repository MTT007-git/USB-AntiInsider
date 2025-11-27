"""
Main script for background use
"""
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
import psutil
import telebot
import os.path
import dotenv
import time
import re
import subprocess
import threading
import tempfile
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

default_ignore = [r"C:/Windows/.*",
                  r"C:/\$Recycle\.Bin/.*",
                  r".:/System Volume Information/.*",
                  r"C:/Users/.*/AppData/.*",
                  r"C:/Users/.*/Desktop/.*\.lnk",
                  r"C:/Users/.*/.*/desktop\.ini",
                  r"C:/Users/.*/desktop\.ini",
                  r"C:/Users/desktop\.ini",
                  r"C:/Users/.*/ntuser\.dat\.LOG\d",
                  r"C:/ProgramData/.*",
                  r"C:/Program Files/.*",
                  r"C:/Program Files \(x86\)/.*"]

ignore = {int(os.getenv("USB_CHATID")): default_ignore}

if os.path.exists("ignore.json"):
    try:
        with open("ignore.json", "r", encoding="utf-8") as file:
            ignore = {int(pair[0]): pair[1] for pair in json.loads(file.read().strip()).items()}
    except Exception as ex:
        print(f"Exception while importing ignore.json: {ex}")

ignore_paths = {pair[0]: [re.compile(ign) for ign in pair[1]] for pair in ignore.items()}

monitoring: set[int] = set()
is_monitoring = False
authorized: set[int] = {int(os.getenv("USB_CHATID"))}
authorize = (int(os.getenv("USB_AUTH")) == 1)
current_drives = set()
current_removable_drives = set()


def save_ignore():
    with open("ignore.json", "w", encoding="utf-8") as f:
        f.write(f"{json.dumps(ignore)}\n")


def check_ignore(path, chatid):
    for i in ignore_paths[chatid]:
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


bot = telebot.TeleBot(os.getenv("USB_TOKEN"))


def check_mention(msg):
    if msg.text is not None:
        return "@" not in msg.text.split(" ", 1)[0] or msg.text.split(" ", 1)[0].split("@", 1)[1] == bot.user.username
    else:
        return ("@" not in msg.caption.split(" ", 1)[0] or msg.caption.split(" ", 1)[0].split("@", 1)[1] ==
                bot.user.username)


def send_all(text, do_ignore=False, text_ignore="", **kwargs):
    try:
        for i in monitoring:
            if not do_ignore or check_ignore(text_ignore, i):
                bot.send_message(i, text, **kwargs)
    except RuntimeError:
        pass


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


@bot.message_handler(commands=["lock"])
def lock(msg):
    if not check_mention(msg):
        return
    if msg.chat.id not in authorized:
        bot.send_message(msg.chat.id, "Not authorized")
        return
    if len(msg.text.split(" ", 1)) <= 1:
        bot.send_message(msg.chat.id, "Syntax:\n`/lock D`", parse_mode="Markdown")
        return
    disk = msg.text.split(" ", 1)[1][0]
    if disk == "C":
        bot.send_message(msg.chat.id, "Cannot lock disk C")
        return
    if not ctypes.windll.shell32.IsUserAnAdmin():
        bot.send_message(msg.chat.id, "The program is not run as admin")
        return
    bot.send_message(msg.chat.id, f"Locking disk {disk}...")
    disk_number = get_disk_number_from_letter(disk)
    if disk_number is None or "DiskNumber" not in disk_number:
        bot.send_message(msg.chat.id, f"The disk {disk} doesn't exist")
        return
    script = f"select disk {disk_number["DiskNumber"]}\nattributes disk set readonly\nexit\n"
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt") as f:
        f.write(script)
        path = f.name
    subprocess.run(["diskpart", "/s", path], check=True)
    send_all(f"Disk {disk} locked")
    if msg.chat.id not in monitoring:
        bot.send_message(msg.chat.id, f"Disk {disk} locked")
    watch_drive(f"{disk}:\\")


@bot.message_handler(commands=["release"])
def release(msg):
    if not check_mention(msg):
        return
    if msg.chat.id not in authorized:
        bot.send_message(msg.chat.id, "Not authorized")
        return
    if len(msg.text.split(" ", 1)) <= 1:
        bot.send_message(msg.chat.id, "Syntax:\n`/release D`", parse_mode="Markdown")
        return
    disk = msg.text.split(" ", 1)[1][0]
    if disk == "C":
        bot.send_message(msg.chat.id, "Cannot release disk C")
        return
    if not ctypes.windll.shell32.IsUserAnAdmin():
        bot.send_message(msg.chat.id, "The program is not run as admin")
        return
    bot.send_message(msg.chat.id, f"Releasing disk {disk}...")
    disk_number = get_disk_number_from_letter(disk)
    if disk_number is None or "DiskNumber" not in disk_number:
        bot.send_message(msg.chat.id, f"The disk {disk} doesn't exist")
        return
    script = f"select disk {disk_number["DiskNumber"]}\nattributes disk clear readonly\nexit\n"
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt") as f:
        f.write(script)
        path = f.name
    subprocess.run(["diskpart", "/s", path], check=True)
    send_all(f"Disk {disk} released")
    if msg.chat.id not in monitoring:
        bot.send_message(msg.chat.id, f"Disk {disk} released")
    watch_drive(f"{disk}:\\")


@bot.message_handler(commands=["lockfile"])
def lockfile(msg):
    if not check_mention(msg):
        return
    if msg.chat.id not in authorized:
        bot.send_message(msg.chat.id, "Not authorized")
        return
    if len(msg.text.split(" ", 1)) <= 1:
        bot.send_message(msg.chat.id, "Syntax:\n`/lockfile D:\\Folder`\nor\n`/lockfile D:\\file.txt`",
                         parse_mode="Markdown")
        return
    path = msg.text.split(" ", 1)[1].replace("\\", "/")
    if path in ("C:", "C:/") or path.startswith("C:/Windows"):
        bot.send_message(msg.chat.id, "Cannot lock disk C")
        return
    if not os.path.exists(path):
        bot.send_message(msg.chat.id, "Path doesn't exist")
        return
    cmds = [
        f'icacls "{path}" /inheritance:r',
        f'icacls "{path}" /grant:r SYSTEM:(OI)(CI)F',
        f'icacls "{path}" /grant:r Administrators:(OI)(CI)F',
        f'icacls "{path}" /deny Users:(OI)(CI)(W,R,M,D,RX)'
    ]
    for cmd in cmds:
        subprocess.run(shlex.split(cmd), check=True)
    bot.send_message(msg.chat.id, f"{'File' if os.path.isfile(path) else 'Folder'} `{path}` locked",
                     parse_mode="Markdown")


@bot.message_handler(commands=["releasefile"])
def releasefile(msg):
    if not check_mention(msg):
        return
    if msg.chat.id not in authorized:
        bot.send_message(msg.chat.id, "Not authorized")
        return
    if len(msg.text.split(" ", 1)) <= 1:
        bot.send_message(msg.chat.id, "Syntax:\n`/releasefile D:\\Folder`\nor\n`/releasefile D:\\file.txt`",
                         parse_mode="Markdown")
        return
    path = msg.text.split(" ", 1)[1].replace("\\", "/")
    if path in ("C:", "C:/") or path.startswith("C:/Windows"):
        bot.send_message(msg.chat.id, "Cannot release disk C")
        return
    if not os.path.exists(path):
        bot.send_message(msg.chat.id, "Path doesn't exist")
        return
    cmds = [
        f'icacls "{path}" /remove:d Users',
        f'icacls "{path}" /inheritance:e'
    ]
    for cmd in cmds:
        subprocess.run(shlex.split(cmd), check=True)
    bot.send_message(msg.chat.id, f"{'File' if os.path.isfile(path) else 'Folder'} `{path}` released",
                     parse_mode="Markdown")


class USBHandler(FileSystemEventHandler):
    def on_created(self, event):
        send_all(f"\\[+] File created:\n`{event.src_path}`", True, event.src_path, parse_mode="Markdown")

    def on_deleted(self, event):
        send_all(f"\\[-] File deleted:\n`{event.src_path}`", True, event.src_path, parse_mode="Markdown")

    def on_modified(self, event):
        if os.path.isfile(event.src_path):
            send_all(f"\\[~] File modified:\n`{event.src_path}`", True, event.src_path, parse_mode="Markdown")

    def on_moved(self, event):
        send_all(f"\\[>] File moved:\n`{event.src_path}`\nv\n`{event.dest_path}`", True, event.src_path,
                 parse_mode="Markdown")


def watch_drive(drive):
    handler = USBHandler()
    observer = Observer()
    observer.schedule(handler, drive, recursive=True)
    observer.start()
    send_all(f"Monitoring {drive}")
    try:
        while len(monitoring) > 0 and drive in current_drives:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    observer.stop()
    observer.join()
    send_all(f"Stopped monitoring {drive}")


@bot.message_handler(commands=["auth"])
def auth(msg):
    if not check_mention(msg):
        return
    if not authorize:
        bot.send_message(msg.chat.id, "Authorization is not enabled")
        try:
            bot.delete_message(msg.chat.id, msg.message_id)
        except telebot.apihelper.ApiTelegramException:
            pass
        return
    if len(msg.text.split(" ", 1)) <= 1:
        if msg.chat.id in authorized:
            ans = f"{len(authorized)} chat{'s' if len(authorized) != 1 else ''} authorized:"
            for i in authorized:
                ans += "\n"
                chat = bot.get_chat(i)
                if chat.type == "private":
                    ans += (f"[{chat.first_name}{f' {chat.last_name}' if chat.last_name is not None else ''}]"
                            f"(tg://user?id={chat.id})")
                else:
                    invite_link = chat.invite_link
                    if invite_link is None:
                        try:
                            invite_link = bot.create_chat_invite_link(i).invite_link
                        except telebot.apihelper.ApiTelegramException:
                            pass
                    if invite_link is not None:
                        ans += f"[{chat.title}]({invite_link})"
                    else:
                        ans += f"{chat.title}"
                    ans += f" ({bot.get_chat_member_count(i)} users)"
                if i == msg.chat.id:
                    ans += " - This chat"
            bot.send_message(msg.chat.id, ans, parse_mode="Markdown")
            return
        if msg.from_user.id == int(os.getenv("USB_CHATID")):
            if msg.chat.type == "private":
                markup = telebot.util.quick_markup({
                    f"Authorize {msg.chat.first_name}{f' {msg.chat.last_name}' if msg.chat.last_name is not None else ''}":
                        {"callback_data": f"auth_{msg.chat.id}"},
                    f"Deauthorize {msg.chat.first_name}{f' {msg.chat.last_name}' if msg.chat.last_name is not None else ''
                    }": {"callback_data": f"deauth_{msg.chat.id}"}
                })
            else:
                markup = telebot.util.quick_markup({
                    f"Authorize {msg.chat.title}": {"callback_data": f"auth_{msg.chat.id}"},
                    f"Deauthorize {msg.chat.title}": {"callback_data": f"deauth_{msg.chat.id}"}
                })
            for i in authorized:
                if msg.chat.type == "private":
                    bot.send_message(i, f"New user waiting to be authorized:\n[{msg.from_user.first_name}"
                                        f" {msg.from_user.last_name if msg.from_user.last_name is not None else ''}]"
                                        f"(tg://user?id={msg.from_user.id})", parse_mode="Markdown",
                                     reply_markup=markup)
                else:
                    invite_link = msg.chat.invite_link
                    if invite_link is None:
                        try:
                            invite_link = bot.create_chat_invite_link(msg.chat.id).invite_link
                        except telebot.apihelper.ApiTelegramException:
                            pass
                    bot.send_message(i, f"New chat waiting to be authorized:\n{
                                        f'[{msg.chat.title}]({invite_link})' if invite_link is not None
                                            else f'{msg.chat.title}'} ({bot.get_chat_member_count(msg.chat.id)} users)",
                                     parse_mode="Markdown", reply_markup=markup)
            bot.send_message(msg.chat.id, "Waiting for authorized users to accept...")
            return
        bot.send_message(msg.chat.id, "Syntax:\n`/auth KEY`", parse_mode="Markdown")
        try:
            bot.delete_message(msg.chat.id, msg.message_id)
        except telebot.apihelper.ApiTelegramException:
            pass
        return
    if msg.chat.id in authorized:
        bot.send_message(msg.chat.id, "Already authorized")
        try:
            bot.delete_message(msg.chat.id, msg.message_id)
        except telebot.apihelper.ApiTelegramException:
            pass
        return
    key = msg.text.split(" ", 1)[1]
    if key == os.getenv("USB_KEY"):
        if msg.chat.type == "private":
            markup = telebot.util.quick_markup({
                f"Authorize {msg.chat.first_name}{f' {msg.chat.last_name}' if msg.chat.last_name is not None else ''}":
                    {"callback_data": f"auth_{msg.chat.id}"},
                f"Deauthorize {msg.chat.first_name}{f' {msg.chat.last_name}' if msg.chat.last_name is not None else ''
                }": {"callback_data": f"deauth_{msg.chat.id}"}
            })
        else:
            markup = telebot.util.quick_markup({
                f"Authorize {msg.chat.title}": {"callback_data": f"auth_{msg.chat.id}"},
                f"Deauthorize {msg.chat.title}": {"callback_data": f"deauth_{msg.chat.id}"}
            })
        for i in authorized:
            if msg.chat.type == "private":
                bot.send_message(i, f"New user waiting to be authorized:\n[{msg.from_user.first_name}"
                                    f" {msg.from_user.last_name if msg.from_user.last_name is not None else ''}]"
                                    f"(tg://user?id={msg.from_user.id})", parse_mode="Markdown",
                                 reply_markup=markup)
            else:
                invite_link = msg.chat.invite_link
                if invite_link is None:
                    try:
                        invite_link = bot.create_chat_invite_link(msg.chat.id).invite_link
                    except telebot.apihelper.ApiTelegramException:
                        pass
                bot.send_message(i, f"New chat waiting to be authorized:\n{
                f'[{msg.chat.title}]({invite_link})' if invite_link is not None
                else f'{msg.chat.title}'} ({bot.get_chat_member_count(msg.chat.id)} users)",
                                 parse_mode="Markdown", reply_markup=markup)
        bot.send_message(msg.chat.id, "Waiting for authorized users to accept...")
    else:
        bot.send_message(msg.chat.id, "Incorrect key")
    try:
        bot.delete_message(msg.chat.id, msg.message_id)
    except telebot.apihelper.ApiTelegramException:
        pass


@bot.callback_query_handler(lambda call: len(call.data) >= 5 and call.data[:5] == "auth_")
def auth_chat(call):
    if call.message.chat.id not in authorized:
        bot.answer_callback_query(call.id, "Not authorized")
        return
    if not authorize:
        bot.answer_callback_query(call.id, "Authorization is not enabled")
        return
    chatid = int(call.data[5:])
    if chatid in authorized:
        bot.answer_callback_query(call.id, "Already authorized")
        return
    if chatid not in ignore:
        ignore[chatid] = default_ignore
        ignore_paths[chatid] = [re.compile(ign) for ign in default_ignore]
        save_ignore()
    authorized.add(chatid)
    bot.send_message(chatid, "Chat authorized")
    bot.answer_callback_query(call.id, "Done")


@bot.callback_query_handler(lambda call: len(call.data) >= 7 and call.data[:7] == "deauth_")
def deauth_chat(call):
    if call.message.chat.id not in authorized:
        bot.answer_callback_query(call.id, "Not authorized")
        return
    if not authorize:
        bot.answer_callback_query(call.id, "Authorization is not enabled")
        return
    chatid = int(call.data[7:])
    if chatid not in authorized:
        bot.answer_callback_query(call.id, "Already deauthorized")
        return
    if chatid == int(os.getenv("USB_CHATID")):
        bot.answer_callback_query(call.id, "Cannot deauthorize original chat")
        return
    authorized.remove(chatid)
    bot.send_message(chatid, "Chat deauthorized")
    bot.answer_callback_query(call.id, "Done")


@bot.message_handler(commands=["deauth"])
def deauth(msg):
    if not check_mention(msg):
        return
    if msg.chat.id not in authorized:
        bot.send_message(msg.chat.id, "Not authorized")
        return
    markupdict = {}
    for i in authorized:
        if i == int(os.getenv("USB_CHATID")):
            continue
        chat = bot.get_chat(i)
        if chat.type == "private":
            markupdict[(f"Deauthorize {chat.first_name}{f' {chat.last_name}' if chat.last_name is not None else ''}"
                        f"{' - This chat' if i == msg.chat.id else ''}")] = {"callback_data": f"deauth_{i}"}
        else:
            markupdict[(f"Deauthorize {chat.title} ({bot.get_chat_member_count(i)} users)"
                        f"{' - This chat' if i == msg.chat.id else ''}")] = {"callback_data": f"deauth_{i}"}
    markup = telebot.util.quick_markup(markupdict, 1)
    bot.send_message(msg.chat.id, "Choose a chat to deauthorize", reply_markup=markup)


@bot.message_handler(commands=["ignorelist"])
def ignorelist(msg):
    if not check_mention(msg):
        return
    if msg.chat.id not in authorized:
        bot.send_message(msg.chat.id, "Not authorized")
        return
    bot.send_message(msg.chat.id, "\n".join([f"{idx + 1}. `{i}`" for idx, i in enumerate(ignore[msg.chat.id])]),
                     parse_mode="Markdown")


@bot.message_handler(commands=["ignoreadd"])
def ignoreadd(msg):
    if not check_mention(msg):
        return
    if msg.chat.id not in authorized:
        bot.send_message(msg.chat.id, "Not authorized")
        return
    if len(msg.text.split(" ", 1)) <= 1:
        bot.send_message(msg.chat.id, "Syntax:\n`/ignoreadd pattern`", parse_mode="Markdown")
        return
    pattern = msg.text.split(" ", 1)[1]
    if pattern in ignore[msg.chat.id]:
        bot.send_message(msg.chat.id, "Regex already in ignore list")
        return
    ignore[msg.chat.id].append(pattern)
    ignore_paths[msg.chat.id].append(re.compile(pattern))
    save_ignore()
    bot.send_message(msg.chat.id, f"Added ignore regex:\n`{pattern}`", parse_mode="Markdown")


@bot.message_handler(commands=["ignoresub"])
def ignoresub(msg):
    if not check_mention(msg):
        return
    if msg.chat.id not in authorized:
        bot.send_message(msg.chat.id, "Not authorized")
        return
    if len(msg.text.split(" ", 1)) < 1:
        bot.send_message(msg.chat.id, "Syntax:\n`/ignoresub pattern`", parse_mode="Markdown")
        return
    pattern = msg.text.split(" ", 1)[1]
    if pattern not in ignore[msg.chat.id]:
        bot.send_message(msg.chat.id, "Regex not in ignore list")
        return
    idx = ignore[msg.chat.id].index(pattern)
    ignore[msg.chat.id].remove(pattern)
    ignore_paths[msg.chat.id].pop(idx)
    save_ignore()
    bot.send_message(msg.chat.id, f"Removed ignore regex:\n`{pattern}`", parse_mode="Markdown")


@bot.message_handler(commands=["ignoreedit"])
def ignoreedit(msg):
    if not check_mention(msg):
        return
    if msg.chat.id not in authorized:
        bot.send_message(msg.chat.id, "Not authorized")
        return
    if len(msg.text.split(" ", 1)) <= 1:
        bot.send_message(msg.chat.id, "Syntax:\n`/ignoreedit 1 pattern`", parse_mode="Markdown")
        return
    try:
        int(msg.text.split(" ", 2)[1])
    except ValueError:
        bot.send_message(msg.chat.id, "Syntax:\n`/ignoreedit 1 pattern`", parse_mode="Markdown")
    idx = int(msg.text.split(" ", 2)[1]) - 1
    pattern = msg.text.split(" ", 2)[2]
    if idx >= len(ignore[msg.chat.id]) or idx < 0:
        bot.send_message(msg.chat.id, "Index not in ignore list")
        return
    if pattern in ignore[msg.chat.id]:
        bot.send_message(msg.chat.id, "Regex already in ignore list")
        return
    init = ignore[msg.chat.id][idx]
    ignore[msg.chat.id][idx] = pattern
    ignore_paths[msg.chat.id][idx] = re.compile(pattern)
    save_ignore()
    bot.send_message(msg.chat.id, f"Edited ignore regex:\n`{init}`\nv\n`{pattern}`", parse_mode="Markdown")


@bot.message_handler(commands=["listdir"])
def listdir(msg):
    if not check_mention(msg):
        return
    if msg.chat.id not in authorized:
        bot.send_message(msg.chat.id, "Not authorized")
        return
    if len(msg.text.split(" ", 1)) <= 1:
        bot.send_message(msg.chat.id, "Syntax:\n`/listdir D:/`", parse_mode="Markdown")
        return
    path = msg.text.split(" ", 1)[1].replace("\\", "/").strip("/") + "/"
    if not os.path.exists(path):
        bot.send_message(msg.chat.id, "Path doesn't exist")
        return
    if not os.path.isdir(path):
        bot.send_message(msg.chat.id, "Path is not a directory")
        return
    try:
        bot.send_message(msg.chat.id, f"Directory of `{path}`\n" +
                         "\n".join([f"> `{path + i}`" for i in os.listdir(path) if os.path.isdir(path + i)]) + "\n" +
                         "\n".join([f"   `{path + i}`" for i in os.listdir(path) if not os.path.isdir(path + i)]),
                         parse_mode="Markdown")
    except Exception as e:
        if "Permission denied" in str(e) or "Access is denied" in str(e):
            bot.send_message(msg.chat.id, "Permission denied")
        else:
            bot.send_message(msg.chat.id, "Unknown error")
            print(e)


@bot.message_handler(commands=["download"])
def download(msg):
    if not check_mention(msg):
        return
    if msg.chat.id not in authorized:
        bot.send_message(msg.chat.id, "Not authorized")
        return
    if len(msg.text.split(" ", 1)) <= 1:
        bot.send_message(msg.chat.id, "Syntax:\n`/download D:/file.txt`", parse_mode="Markdown")
        return
    path = msg.text.split(" ", 1)[1]
    if not os.path.exists(path):
        bot.send_message(msg.chat.id, "Path doesn't exist")
        return
    if not os.path.isfile(path):
        bot.send_message(msg.chat.id, "Path is not a file")
        return
    bot.send_message(msg.chat.id, "Downloading...")
    try:
        bot.send_document(msg.chat.id, telebot.types.InputFile(path), caption=f"`{path}`", parse_mode="Markdown")
    except Exception as e:
        if "Permission denied" in str(e) or "Access is denied" in str(e):
            bot.send_message(msg.chat.id, "Permission denied")
        else:
            bot.send_message(msg.chat.id, "Unknown error")
            print(e)


@bot.message_handler(func=lambda msg: msg.caption is not None and msg.caption.startswith("/upload"),
                     content_types=["document"])
def upload(msg):
    if not check_mention(msg):
        return
    if msg.chat.id not in authorized:
        bot.send_message(msg.chat.id, "Not authorized")
        return
    if len(msg.caption.split(" ", 1)) <= 1:
        bot.send_message(msg.chat.id, "Syntax:\n`/upload D:/file.txt` with a file", parse_mode="Markdown")
        return
    path = msg.caption.split(" ", 1)[1].replace("\\", "/")
    if path.endswith("/"):
        path += msg.document.file_name
    if os.path.exists(path):
        bot.send_message(msg.chat.id, "A file with this name already exists")
        return
    bot.send_message(msg.chat.id, "Uploading...")
    try:
        downloaded = bot.download_file(bot.get_file(msg.document.file_id).file_path)
        with open(path, "wb") as f:
            f.write(downloaded)
            bot.send_message(msg.chat.id, f"Uploaded file at `{path}`", parse_mode="Markdown")
    except Exception as e:
        if "Permission denied" in str(e) or "Access is denied" in str(e):
            bot.send_message(msg.chat.id, "Permission denied")
        else:
            bot.send_message(msg.chat.id, "Unknown error")
            print(e)


@bot.message_handler(func=lambda msg: msg.caption is not None and msg.caption.startswith("/upload"),
                     content_types=["audio"])
def upload_audio(msg):
    msg.document = msg.audio
    upload(msg)


@bot.message_handler(func=lambda msg: msg.caption is not None and msg.caption.startswith("/upload"),
                     content_types=["animation"])
def upload_animation(msg):
    msg.document = msg.animation
    upload(msg)


@bot.message_handler(func=lambda msg: msg.caption is not None and msg.caption.startswith("/upload"),
                     content_types=["photo"])
def upload_photo(msg):
    msg.document = msg.photo[-1]
    upload(msg)


@bot.message_handler(func=lambda msg: msg.caption is not None and msg.caption.startswith("/upload"),
                     content_types=["video"])
def upload_video(msg):
    msg.document = msg.video
    upload(msg)


@bot.message_handler(commands=["upload"])
def upload_nofile(msg):
    if not check_mention(msg):
        return
    if msg.chat.id not in authorized:
        bot.send_message(msg.chat.id, "Not authorized")
        return
    bot.send_message(msg.chat.id, "Syntax:\n`/upload D:/file.txt` with a file", parse_mode="Markdown")


@bot.message_handler(commands=["start"])
def start(msg):
    if not check_mention(msg):
        return
    if msg.chat.id not in authorized:
        bot.send_message(msg.chat.id, "Not authorized")
        return
    if msg.chat.id in monitoring:
        bot.send_message(msg.chat.id, "Already monitoring")
        return
    bot.send_message(msg.chat.id, "Monitoring USB drives")
    monitoring.add(msg.chat.id)
    if is_monitoring:
        for d in current_drives:
            if d in current_removable_drives:
                bot.send_message(msg.chat.id, f"Removable drive found: {d}")
            else:
                bot.send_message(msg.chat.id, f"Drive found: {d}")
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
            send_all(f"Removable drive found: {d}")
        else:
            send_all(f"Drive found: {d}")
        t = threading.Thread(target=watch_drive, args=(d,), daemon=True)
        t.start()
        watched_threads[d] = t

    while len(monitoring) > 0:
        new_drives = get_all_drives()
        new_removable_drives = get_removable_drives()
        added = new_drives - current_drives
        removed = current_drives - new_drives

        for d in added:
            if d in new_removable_drives:
                send_all(f"Removable drive inserted: {d}")
            else:
                send_all(f"Non-removable drive inserted: {d}")  # How?
            t = threading.Thread(target=watch_drive, args=(d,), daemon=True)
            t.start()
            watched_threads[d] = t

        for d in removed:
            if d in current_removable_drives:
                send_all(f"Removable drive removed: {d}")
            else:
                send_all(f"Non-removable drive removed: {d}")  # How?
            watched_threads.pop(d, None)

        current_drives = new_drives
        current_removable_drives = new_removable_drives
        time.sleep(1)
    is_monitoring = False
    print("Stopped monitoring")


@bot.message_handler(commands=["stop"])
def stop(msg):
    if not check_mention(msg):
        return
    if msg.chat.id not in authorized:
        bot.send_message(msg.chat.id, "Not authorized")
        return
    if msg.chat.id in monitoring:
        bot.send_message(msg.chat.id, "Stopped monitoring USB drives")
        monitoring.remove(msg.chat.id)
    else:
        bot.send_message(msg.chat.id, "Already not monitoring")


@bot.message_handler(commands=["shut"])
def shut(msg):
    if not check_mention(msg):
        return
    global running
    if msg.chat.id not in authorized:
        bot.send_message(msg.chat.id, "Not authorized")
        return
    for i in authorized:
        bot.send_message(i, "Program shutdown")
    print("Program shutdown")
    monitoring.clear()
    running = False
    bot.stop_bot()


@bot.message_handler(commands=["reset"])
def reset(msg):
    if not check_mention(msg):
        return
    if msg.chat.id not in authorized:
        bot.send_message(msg.chat.id, "Not authorized")
        return
    send_all("Monitoring reset")
    if msg.chat.id not in monitoring:
        bot.send_message(msg.chat.id, "Monitoring reset")
    monitoring.clear()


@bot.message_handler(commands=["help"])
def help_(msg):
    if not check_mention(msg):
        return
    if msg.chat.id not in authorized:
        bot.send_message(msg.chat.id, "Not authorized")
        return
    bot.send_message(msg.chat.id, "Help:\n"
                                  "  /start - Start monitoring\n"
                                  "  /stop - Stop monitoring\n"
                                  "  /lock `letter` - Make drive `letter` read-only\n"
                                  "  /release `letter` - Make drive `letter` non-read-only\n"
                                  "  /lockfile `path` - Make a file/folder read-only\n"
                                  "  /releasefile `path` - Make a file/folder non-read-only\n"
                                  "  /ignorelist - List all ignored regex patterns\n"
                                  "  /ignoreadd `regex` - Add regex pattern `regex` to ignore\n"
                                  "  /ignoresub `regex` - Remove ignored regex pattern `regex`\n"
                                  "  /ignoreedit `index` `regex` - Edit ignored regex pattern at `index` to `regex`\n"
                                  "  /listdir `folder_path` - List the contents of directory `folder_path`\n"
                                  "  /download `file_path` - Download file `file_path`\n"
                                  "  /upload `file_path` with a file - Upload file at `file_path`\n"
                                  "  /auth - List all authorized chats or authorize the current chat\n"
                                  "  /auth `key` - Authorize the current chat if `key` is correct\n"
                                  "  /deauth - Deauthorize everyone\n"
                                  "  /reset - Reset monitoring\n"
                                  "  /shut - Force program shutdown\n"
                                  "  /help - List all commands", parse_mode="Markdown")


print("Started polling")
last_err = None
running = True
while running:
    try:
        bot.polling()
    except Exception as ex:
        if running and ex != last_err:
            print(f"Exception: {ex}; restarting")
            last_err = ex
print("Stopped polling")
