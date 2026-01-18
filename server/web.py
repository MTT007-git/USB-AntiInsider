"""
Web interface
"""
from flask import Blueprint, render_template, flash, request, send_file
from methods import login
from models import *
from io import BytesIO
import base64

web = Blueprint("web", __name__)


@web.route("/login")
def login_page():
    return render_template("login.html")


@web.route("/register")
def register_page():
    return render_template("register.html")


@web.route("/")
@login
def index(user):
    return render_template("index.html")


@web.route("/clients")
@login
def clients(user):
    return render_template("clients.html")


@web.route("/clients/<int:client_id>")
@login
def client_view(user, client_id):
    client = Client.query.filter_by(id=client_id).first()
    if not client:
        flash("Client not found", "danger")
        return render_template("clients.html")
    page = request.args.get("page")
    return render_template("client.html", client=client, page=page)


@web.route("/clients/new")
@login
def newclient(user):
    return render_template("newclient.html")


@web.route("/clients/<int:client_id>/download/<int:command_id>")
@login
def download(user, client_id, command_id):
    client = Client.query.filter_by(id=client_id).first()
    if not client:
        flash("Client not found", "danger")
        return render_template("clients.html")
    command = Command.query.filter_by(id=command_id, client_id=client_id).first()
    if not command:
        flash("File not found", "danger")
        return render_template("clients.html")
    name = CommandArgument.query.filter_by(command_id=command.id, position=0).first()
    file = CommandArgument.query.filter_by(command_id=command.id, position=1).first()
    if not name or not file:
        flash("File not found", "danger")
        return render_template("clients.html")
    name = name.argument.replace("\\", "/").split("/")[-1]
    if name.endswith("`"):
        name = name[:-1]
    file = file.argument
    try:
        file = base64.b64decode(file)
    except Exception:
        flash("Could not decode file", "danger")
        return render_template("clients.html")
    return send_file(BytesIO(file), download_name=name, as_attachment=True)
