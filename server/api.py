"""
API for watched clients
"""
from flask import Blueprint, request, jsonify
from models import *
import tg
from threading import Thread
import time

api = Blueprint("api", __name__)


def get_client():
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return jsonify({"reason": "Missing Authorization header"}), 401
    if not auth_header.startswith("Bearer "):
        return jsonify({"reason": "Incorrect format of Authorization header"}), 401
    token = auth_header[7:]
    client = Client.query.filter_by(token=token).first()
    if not client:
        return jsonify({"reason": "Token expired"}), 401
    client.last_check = time.time()
    return client


def login(func):
    def wrapper(*args, **kwargs):
        client = get_client()
        if not isinstance(client, Client):
            return client
        return func(client, *args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper


@api.route("/send", methods=["POST"])
@login
def send(client):
    updates = request.json.get("updates")
    for command in updates:
        if command[0] is None and command[1] == "system" and command[2] == "info" and command[3] == "boot":
            cmd = Command(client_id=client.id, command="ignorelist", is_from_server=True,
                          time=time.time() + 1)
            db.session.add(cmd)
            db.session.commit()
            for i, argument in enumerate(IgnoreRule.query.filter_by(client_id=client.id).all()):
                argument = CommandArgument(command_id=cmd.id, position=i, argument=argument.rule)
                db.session.add(argument)
            db.session.commit()
        if command[0]:
            if command[-1]:
                user_id = command[0]
                command_obj = Command(client_id=client.id, tg_user_id=user_id,
                                      command=f"[{command[1]}]", category=command[2],
                                      is_from_server=False, is_sent=True, is_tg=command[-1], time=time.time())
            else:
                user_id = User.query.filter_by(username=command[0]).first().id
                command_obj = Command(client_id=client.id, user_id=user_id,
                                      command=f"[{command[1]}]", category=command[2],
                                      is_from_server=False, is_sent=True, is_tg=command[-1], time=time.time())
            if command[-1]:
                tg.command(client.id, user_id, rf"\[{command[1]}]", command[3:-1])
            command = command[:-1]
        else:
            command_obj = Command(client_id=client.id,
                                  command=f"[{command[1]}]", category=command[2],
                                  is_from_server=False, is_sent=True, time=time.time())
            tg.command(client.id, None, rf"\[{command[1]}]", command[3:])
        db.session.add(command_obj)
        db.session.commit()
        for i, argument in enumerate(command[3:]):
            argument_obj = CommandArgument(command_id=command_obj.id, position=i, argument=argument)
            db.session.add(argument_obj)
    db.session.commit()
    commands = []
    clear = False
    for command in Command.query.filter_by(is_sent=False).order_by(Command.time.asc()).all():
        arguments = []
        for argument in CommandArgument.query.filter_by(command_id=command.id).order_by(
                CommandArgument.position.asc()).all():
            arguments.append(argument.argument)
        if command.command == "clear":
            clear = True
        elif command.user or command.tg_user:
            if command.is_tg:
                commands.append((command.tg_user.id, command.command, *arguments, command.is_tg))
            else:
                commands.append((command.user.username, command.command, *arguments, command.is_tg))
        else:
            commands.append((None, command.command, *arguments, command.is_tg))
        command.is_sent = True
    if clear:
        CommandArgument.query.delete()
        Command.query.delete()
    db.session.commit()
    return jsonify({"commands": commands}), 200


def start_tg():
    Thread(target=tg.start_polling, daemon=True).start()
