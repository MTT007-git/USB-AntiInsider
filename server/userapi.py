"""
API for watched clients
"""
from flask import Blueprint, request, redirect, flash, make_response, render_template
from methods import login, add_command
from models import *
from manage import *
import base64
import time
import jwt
import os

api = Blueprint("userapi", __name__)


@api.route("/register", methods=["POST"])
def register():
    username = request.form.get("username")
    password = request.form.get("password")
    repeat_password = request.form.get("repeat_password")
    if not username or not password or not repeat_password:
        flash("All fields must be filled", "warning")
        return redirect("/register")
    if password != repeat_password:
        flash("Passwords do not match", "danger")
        return redirect("/register")
    if User.query.filter_by(username=username).first():
        flash("A user with this username already exists", "danger")
        return redirect("/register")
    if len(username) > 100:
        flash("Username too long", "warning")
        return redirect("/register")
    if len(password) > 100:
        flash("Password too long", "warning")
        return redirect("/register")
    password_hash = bcrypt.generate_password_hash(password).decode("utf-8")
    if len(password_hash) > 120:
        flash("Password too long", "warning")
        return redirect("/register")
    t = time.time()
    user = User(username=username, password_hash=password_hash, last_token_time=t)
    db.session.add(user)
    db.session.commit()
    response = make_response(redirect("/"))
    response.set_cookie(
        "token",
        jwt.encode({"id": user.id, "time": t}, app.config["SECRET_KEY"], algorithm="HS256"),
        httponly=True,
        samesite="strict",
        secure=False,
        expires=time.time() + int(os.getenv("USB_DEAUTH_TIME", "86400"))
    )
    return response


@api.route("/login", methods=["POST"])
def login_post():
    username = request.form.get("username")
    password = request.form.get("password")
    if not username or not password:
        flash("All fields must be filled", "warning")
        return redirect("/login")
    user = User.query.filter_by(username=username).first()
    if not user or not bcrypt.check_password_hash(user.password_hash, password):
        flash("Invalid credentials", "danger")
        return redirect("/login")
    t = user.last_token_time
    if t + int(os.getenv("USB_DEAUTH_TIME", "86400")) < time.time():
        t = time.time()
        user.last_token_time = t
        db.session.commit()
    response = make_response(redirect("/"))
    response.set_cookie(
        "token",
        jwt.encode({"id": user.id, "time": t}, app.config["SECRET_KEY"], algorithm="HS256"),
        httponly=True,
        samesite="strict",
        secure=False,
        expires=time.time() + int(os.getenv("USB_DEAUTH_TIME", "86400"))
    )
    return response


@api.route("/logout", methods=["POST"])
@login
def logout(user):
    response = make_response(redirect("/login"))
    response.delete_cookie("token")
    return response


@api.route("/clients/new", methods=["POST"])
@login
def newclient(user):
    name = request.form.get("name")
    if not name:
        flash("All fields must be filled", "warning")
        return redirect("/clients/new")
    if len(name) > 100:
        flash("Name too long", "warning")
        return redirect("/clients/new")
    if Client.query.filter_by(name=name).first():
        flash("A client with this name already exists", "danger")
        return redirect("/clients/new")
    client = Client(name=name, last_check=time.time())
    db.session.add(client)
    db.session.commit()
    client.token = jwt.encode({"id": client.id, "time_created": time.time()}, app.config["SECRET_KEY"], "HS256")
    db.session.commit()
    for rule in default_ignore:
        rule_obj = IgnoreRule(client_id=client.id, rule=rule)
        db.session.add(rule_obj)
    db.session.commit()
    return redirect(f"/clients/{client.id}")


@api.route("/clients/<int:client_id>/start", methods=["POST"])
@login
def start(user, client_id):
    client = Client.query.filter_by(id=client_id).first()
    if not client:
        flash("Client not found", "danger")
        return redirect(f"/clients/{client_id}")
    add_command(client_id, user.id, "start", ())
    flash(f"Started monitoring {client.name}", "success")
    return redirect(f"/clients/{client_id}")


@api.route("/clients/<int:client_id>/stop", methods=["POST"])
@login
def stop(user, client_id):
    client = Client.query.filter_by(id=client_id).first()
    if not client:
        flash("Client not found", "danger")
        return redirect(f"/clients/{client_id}")
    add_command(client_id, user.id, "stop", ())
    flash(f"Stopped monitoring {client.name}", "success")
    return redirect(f"/clients/{client_id}")


@api.route("/clients/<int:client_id>/delete", methods=["POST"])
@login
def delclient(user, client_id):
    client = Client.query.filter_by(id=client_id).first()
    if not client:
        flash("Client not found", "danger")
        return redirect("/clients")
    for command in client.commands:
        for argument in command.arguments:
            db.session.delete(argument)
        db.session.delete(command)
    for rule in client.ignorerules:
        db.session.delete(rule)
    db.session.delete(client)
    db.session.commit()
    return redirect("/clients")


@api.route("/clients/<int:client_id>/command", methods=["POST"])
@login
def clientcommand(user, client_id):
    client = Client.query.filter_by(id=client_id).first()
    if not client:
        flash("Client not found", "danger")
        return redirect(f"/clients/{client_id}")
    command = request.form.get("command")
    if not command:
        flash("Command empty", "danger")
        return redirect(f"/clients/{client_id}")
    arguments = command.split(" ", 1)[1:]
    command = command.split(" ", 1)[0]
    if command not in ("start", "stop", "lock", "release", "lockfile", "releasefile", "listdir", "download", "clear"):
        flash(f"Unknown command: \"{command}\"", "danger")
        return redirect(f"/clients/{client_id}")
    command = Command(client_id=client_id, user_id=user.id, command=command, is_from_server=True, time=time.time())
    db.session.add(command)
    db.session.commit()
    for i, argument in enumerate(arguments):
        argument = CommandArgument(command_id=command.id, position=i, argument=argument)
        db.session.add(argument)
    db.session.commit()
    return redirect(f"/clients/{client_id}")


@api.route("/clients/<int:client_id>/commandsHTML", methods=["POST"])
@login
def commands_html(user, client_id):
    client = Client.query.filter_by(id=client_id).first()
    if not client:
        flash("Client not found", "danger")
        return redirect(f"/clients/{client_id}")
    commands = Command.query.filter_by(client_id=client_id).order_by(Command.time.asc()).all()
    page = request.args.get("page")
    if not page or not page.isnumeric():
        page = int(len(commands) / 100) + 1
    else:
        page = int(page)
    return render_template("client_commands.html", client=client, commands=commands, page=page)


@api.route("/clients/<int:client_id>/addignore", methods=["POST"])
@login
def addignore(user, client_id):
    client = Client.query.filter_by(id=client_id).first()
    if not client:
        flash("Client not found", "danger")
        return redirect(f"/clients/{client_id}")
    rule_text = request.form.get("rule")
    if not rule_text:
        flash("Empty rule", "danger")
        return redirect(f"/clients/{client_id}")
    if IgnoreRule.query.filter_by(client_id=client_id, rule=rule_text).first():
        flash("Rule already exists", "warning")
        return redirect(f"/clients/{client_id}")
    rule = IgnoreRule(client_id=client_id, rule=rule_text)
    db.session.add(rule)
    db.session.commit()
    command = Command(client_id=client_id, user_id=user.id, command="ignorelist", is_from_server=True, time=time.time())
    db.session.add(command)
    db.session.commit()
    for i, argument in enumerate(IgnoreRule.query.filter_by(client_id=client_id).all()):
        argument = CommandArgument(command_id=command.id, position=i, argument=argument.rule)
        db.session.add(argument)
    db.session.commit()
    return redirect(f"/clients/{client_id}")


@api.route("/clients/<int:client_id>/delignore", methods=["POST"])
@login
def delignore(user, client_id):
    client = Client.query.filter_by(id=client_id).first()
    if not client:
        flash("Client not found", "danger")
        return redirect(f"/clients/{client_id}")
    rule_text = request.form.get("rule")
    if not rule_text:
        flash("Empty rule", "danger")
        return redirect(f"/clients/{client_id}")
    if not IgnoreRule.query.filter_by(client_id=client_id, rule=rule_text).first():
        flash("Rule doesn't exist", "danger")
        return redirect(f"/clients/{client_id}")
    IgnoreRule.query.filter_by(client_id=client_id, rule=rule_text).delete()
    db.session.commit()
    command = Command(client_id=client_id, user_id=user.id, command="ignorelist", is_from_server=True, time=time.time())
    db.session.add(command)
    db.session.commit()
    for i, argument in enumerate(IgnoreRule.query.filter_by(client_id=client_id).all()):
        argument = CommandArgument(command_id=command.id, position=i, argument=argument.rule)
        db.session.add(argument)
    db.session.commit()
    return redirect(f"/clients/{client_id}")


@api.route("/clients/<int:client_id>/upload", methods=["POST"])
@login
def upload(user, client_id):
    client = Client.query.filter_by(id=client_id).first()
    if not client:
        flash("Client not found", "danger")
        return redirect(f"/clients/{client_id}")
    file = request.files.get("file")
    name = request.form.get("name")
    if not file or not name:
        flash("File or path missing", "danger")
        return redirect(f"/clients/{client_id}")
    if name.replace("\\", "/").endswith("/"):
        name += file.filename
    add_command(client_id, user.id, "upload", (name, base64.b64encode(file.read()).decode()))
    flash(f"Uploaded file at {name}", "success")
    return redirect(f"/clients/{client_id}")


@api.route("/clients/<int:client_id>/download", methods=["POST"])
@login
def download(user, client_id):
    client = Client.query.filter_by(id=client_id).first()
    if not client:
        flash("Client not found", "danger")
        return redirect(f"/clients/{client_id}")
    name = request.form.get("name")
    if not name:
        flash("Path missing", "danger")
        return redirect(f"/clients/{client_id}")
    add_command(client_id, user.id, "download", (name,))
    flash(f"Downloading file from {name}", "success")
    return redirect(f"/clients/{client_id}")
