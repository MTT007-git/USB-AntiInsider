"""
Telegram interface
"""
import io

from methods import add_command
from models import *
from manage import app
import telebot
import os
import base64

LOG = True

is_running: bool = False
authorized: set[int] = {int(os.getenv("USB_CHATID"))}
authorize = (int(os.getenv("USB_AUTH")) == 1)

TOKEN = os.getenv("USB_TOKEN")
bot = telebot.TeleBot(TOKEN)


def check_mention(msg):
    if msg.text is not None:
        return "@" not in msg.text.split(" ", 1)[0] or msg.text.split(" ", 1)[0].split("@", 1)[1] == bot.user.username
    else:
        return ("@" not in msg.caption.split(" ", 1)[0] or msg.caption.split(" ", 1)[0].split("@", 1)[1] ==
                bot.user.username)


def send_all(cid, text, **kwargs):
    try:
        for monitor in TgMonitor.query.filter_by(client_id=cid).all():
            bot.send_message(monitor.tg_user_id, text, **kwargs)
    except RuntimeError:
        pass


def client(func):
    def wrapper(msg):
        if not check_mention(msg):
            return
        if msg.chat.id not in authorized:
            bot.send_message(msg.chat.id, "Not authorized")
            return
        args = msg.text.split(" ")
        if len(args) <= 1:
            bot.send_message(msg.chat.id, "Client ID required")
            return
        cid = args[1]
        with app.app_context():
            if not TgUser.query.filter_by(id=msg.chat.id).first():
                tg_user = TgUser(id=msg.chat.id, username=msg.from_user.username)
                db.session.add(tg_user)
                db.session.commit()
            if not cid.isnumeric() or not Client.query.filter_by(id=int(cid)).first():
                bot.send_message(msg.chat.id, "Invalid client ID")
                return
            func(msg, cid)

    wrapper.__name__ = func.__name__
    return wrapper


@bot.message_handler(commands=["lock"])
@client
def lock(msg, cid):
    if len(msg.text.split(" ", 2)) <= 2:
        bot.send_message(msg.chat.id, f"Syntax:\n`/lock {cid} D`", parse_mode="Markdown")
        return
    disk = msg.text.split(" ", 2)[2][0]
    add_command(cid, msg.chat.id, "lock", (disk,), True)


@bot.message_handler(commands=["release"])
@client
def release(msg, cid):
    if len(msg.text.split(" ", 2)) <= 2:
        bot.send_message(msg.chat.id, f"Syntax:\n`/release {cid} D`", parse_mode="Markdown")
        return
    disk = msg.text.split(" ", 2)[2][0]
    add_command(cid, msg.chat.id, "release", (disk,), True)


@bot.message_handler(commands=["lockfile"])
@client
def lockfile(msg, cid):
    if len(msg.text.split(" ", 2)) <= 2:
        bot.send_message(msg.chat.id, f"Syntax:\n`/lockfile {cid} D:\\Folder`\nor\n`/lockfile {cid} D:\\file.txt`",
                         parse_mode="Markdown")
        return
    path = msg.text.split(" ", 2)[2].replace("\\", "/")
    add_command(cid, msg.chat.id, "lockfile", (path,), True)


@bot.message_handler(commands=["releasefile"])
@client
def releasefile(msg, cid):
    if len(msg.text.split(" ", 2)) <= 2:
        bot.send_message(msg.chat.id, f"Syntax:\n`/releasefile {cid} D:\\Folder`\nor\n`/releasefile {cid} "
                                      f"D:\\file.txt`", parse_mode="Markdown")
        return
    path = msg.text.split(" ", 2)[2].replace("\\", "/")
    add_command(cid, msg.chat.id, "releasefile", (path,), True)


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
                    f"Authorize {msg.chat.first_name}"
                    f"{f' {msg.chat.last_name}' if msg.chat.last_name is not None else ''}":
                        {"callback_data": f"auth_{msg.chat.id}"},
                    f"Deauthorize {msg.chat.first_name}"
                    f"{f' {msg.chat.last_name}' if msg.chat.last_name is not None else ''
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
                    bot.send_message(i, f"New chat waiting to be authorized:\n"
                                        f"{f'[{msg.chat.title}]({invite_link})' if invite_link is not None
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
                bot.send_message(i, f"New chat waiting to be authorized:\n"
                                    f"{f'[{msg.chat.title}]({invite_link})' if invite_link is not None
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
@client
def ignorelist(msg, cid):
    bot.send_message(msg.chat.id, "\n".join([f"{idx + 1}. `{i.rule}`" for idx, i in
                                             enumerate(Client.query.filter_by(id=cid).first().ignorerules)]),
                     parse_mode="Markdown")


@bot.message_handler(commands=["ignoreadd"])
@client
def ignoreadd(msg, cid):
    if len(msg.text.split(" ", 2)) <= 2:
        bot.send_message(msg.chat.id, f"Syntax:\n`/ignoreadd {cid} pattern`", parse_mode="Markdown")
        return
    pattern = msg.text.split(" ", 2)[2]
    if IgnoreRule.query.filter_by(client_id=cid, rule=pattern).first():
        bot.send_message(msg.chat.id, "Regex already in ignore list")
        return
    rule = IgnoreRule(client_id=cid, rule=pattern)
    db.session.add(rule)
    db.session.commit()
    add_command(cid, msg.chat.id, "ignorelist", (r.rule for r in IgnoreRule.query.filter_by(client_id=cid).all()), True)
    bot.send_message(msg.chat.id, f"Added ignore regex:\n`{pattern}`", parse_mode="Markdown")


@bot.message_handler(commands=["ignoredel"])
@client
def ignoredel(msg, cid):
    if len(msg.text.split(" ", 2)) <= 2:
        bot.send_message(msg.chat.id, f"Syntax:\n`/ignoresub {cid} pattern`", parse_mode="Markdown")
        return
    pattern = msg.text.split(" ", 2)[2]
    rule = IgnoreRule.query.filter_by(client_id=cid, rule=pattern).first()
    if not rule:
        bot.send_message(msg.chat.id, "Regex not in ignore list")
        return
    db.session.delete(rule)
    db.session.commit()
    add_command(cid, msg.chat.id, "ignorelist", (r.rule for r in IgnoreRule.query.filter_by(client_id=cid).all()), True)
    bot.send_message(msg.chat.id, f"Removed ignore regex:\n`{pattern}`", parse_mode="Markdown")


@bot.message_handler(commands=["listdir"])
@client
def listdir(msg, cid):
    if len(msg.text.split(" ", 2)) <= 2:
        bot.send_message(msg.chat.id, f"Syntax:\n`/listdir {cid} D:/`", parse_mode="Markdown")
        return
    path = msg.text.split(" ", 2)[2].replace("\\", "/").strip("/") + "/"
    add_command(cid, msg.chat.id, "listdir", (path,), True)


@bot.message_handler(commands=["download"])
@client
def download(msg, cid):
    if len(msg.text.split(" ", 2)) <= 2:
        bot.send_message(msg.chat.id, f"Syntax:\n`/download {cid} D:/file.txt`", parse_mode="Markdown")
        return
    path = msg.text.split(" ", 2)[2].replace("\\", "/")
    add_command(cid, msg.chat.id, "download", (path,), True)


@bot.message_handler(func=lambda msg: msg.caption is not None and msg.caption.startswith("/upload"),
                     content_types=["document"])
@client
def upload(msg, cid):
    if len(msg.caption.split(" ", 2)) <= 2:
        bot.send_message(msg.chat.id, f"Syntax:\n`/upload {cid} D:/file.txt` with a file", parse_mode="Markdown")
        return
    path = msg.caption.split(" ", 2)[2].replace("\\", "/")
    if path.endswith("/"):
        path += msg.document.file_name
    downloaded = bot.download_file(bot.get_file(msg.document.file_id).file_path)
    add_command(cid, msg.chat.id, "upload", (path, base64.b64encode(downloaded)), True)


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
@client
def upload_nofile(msg, cid):
    bot.send_message(msg.chat.id, f"Syntax:\n`/upload {cid} D:/file.txt` with a file", parse_mode="Markdown")


@bot.message_handler(commands=["start"])
@client
def start(msg, cid):
    if not TgMonitor.query.filter_by(tg_user_id=msg.chat.id, client_id=cid).first():
        monitor = TgMonitor(tg_user_id=msg.chat.id, client_id=cid)
        db.session.add(monitor)
        db.session.commit()
    add_command(cid, msg.chat.id, "start", (), True)


@bot.message_handler(commands=["monitorstart"])
@client
def monitorstart(msg, cid):
    if not TgMonitor.query.filter_by(tg_user_id=msg.chat.id, client_id=cid).first():
        monitor = TgMonitor(tg_user_id=msg.chat.id, client_id=cid)
        db.session.add(monitor)
        db.session.commit()
    bot.send_message(msg.chat.id, "Started monitoring")


@bot.message_handler(commands=["monitorstop"])
@client
def monitorstop(msg, cid):
    monitor = TgMonitor.query.filter_by(tg_user_id=msg.chat.id, client_id=cid).first()
    if monitor:
        db.session.delete(monitor)
        db.session.commit()
    bot.send_message(msg.chat.id, "Stopped monitoring")


@bot.message_handler(commands=["stop"])
@client
def stop(msg, cid):
    monitor = TgMonitor.query.filter_by(tg_user_id=msg.chat.id, client_id=cid).first()
    if monitor:
        db.session.delete(monitor)
        db.session.commit()
    add_command(cid, msg.chat.id, "stop", (), True)


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
                                  "  /ignoredel `regex` - Remove ignored regex pattern `regex`\n"
                                  "  /listdir `folder_path` - List the contents of directory `folder_path`\n"
                                  "  /download `file_path` - Download file `file_path`\n"
                                  "  /upload `file_path` with a file - Upload file at `file_path`\n"
                                  "  /auth - List all authorized chats or authorize the current chat\n"
                                  "  /auth `key` - Authorize the current chat if `key` is correct\n"
                                  "  /deauth - Deauthorize everyone\n"
                                  "  /help - List all commands", parse_mode="Markdown")


def command(cid, uid, cmd, args):
    if cmd == r"\[download]" and len(args) == 2:
        file = io.BytesIO()
        file.write(base64.b64decode(args[1]))
        file.seek(0)
        bot.send_document(uid, telebot.types.InputFile(file, file_name=args[0][1:-1]),
                          caption=f"<{cid}> {cmd} {args[0]}", parse_mode="Markdown")
    elif uid:
        bot.send_message(uid, f"<{cid}> {cmd} {' '.join(args)}", parse_mode="Markdown")
    else:
        send_all(cid, f"<{cid}> {cmd} {' '.join(args)}", parse_mode="Markdown")


def start_polling():
    global is_running
    if is_running:
        return
    is_running = True
    if LOG:
        print("Started polling")
    last_err = None
    while True:
        try:
            bot.polling()
        except Exception as ex:
            if ex != last_err and LOG:
                print(f"Exception: {str(ex).replace(TOKEN, "<token>")}; restarting")
                last_err = ex
