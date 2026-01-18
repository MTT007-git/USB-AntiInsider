"""
Methods
"""
from flask import request, redirect, flash, make_response
from manage import *
from models import *
import time
import jwt
import os


def get_user():
    token = request.cookies.get("token")
    if not token:
        return redirect("/login")
    payload = jwt.decode(token, app.config["SECRET_KEY"], ["HS256"])
    user = User.query.filter_by(id=payload["id"]).first()
    if not user or payload["time"] != user.last_token_time or payload["time"] + int(
            os.getenv("USB_DEAUTH_TIME", 86400)) < time.time():
        flash("Token expired", "warning")
        response = make_response(redirect("/login"))
        response.delete_cookie("token")
        return response
    return user


def login(func):
    def wrapper(*args, **kwargs):
        user = get_user()
        if not isinstance(user, User):
            return user
        return func(user, *args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper


def add_command(client_id, user_id, command, arguments, is_tg=False):
    if is_tg:
        command = Command(client_id=client_id, tg_user_id=user_id, command=command, is_from_server=True, is_tg=is_tg,
                          time=time.time())
    else:
        command = Command(client_id=client_id, user_id=user_id, command=command, is_from_server=True, is_tg=is_tg,
                          time=time.time())
    db.session.add(command)
    db.session.commit()
    for i, argument in enumerate(arguments):
        argument = CommandArgument(command_id=command.id, position=i, argument=argument)
        db.session.add(argument)
    db.session.commit()


@app.context_processor
def context():
    def get_username():
        user = get_user()
        if not isinstance(user, User):
            return None
        return user.username
    return dict(get_username=get_username, Client=Client, ctime=time.ctime, len=len, int=int, min=min, enumerate=enumerate)
