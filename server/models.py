"""
DB Models
"""
from manage import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False, unique=True)
    password_hash = db.Column(db.String(120), nullable=False)
    last_token_time = db.Column(db.Integer, nullable=False)


class TgMonitor(db.Model):
    tg_user_id = db.Column(db.Integer, db.ForeignKey("tg_user.id"), primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), primary_key=True)


class TgUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.Text, nullable=True)
    monitoring = db.relationship("Client", secondary="tg_monitor", backref=db.backref("monitoring"))


class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    token = db.Column(db.String(120), nullable=True)
    last_check = db.Column(db.Integer, nullable=False)


class Command(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False)
    client = db.relationship("Client", backref=db.backref("commands"))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    user = db.relationship("User", backref=db.backref("commands"))
    tg_user_id = db.Column(db.Integer, db.ForeignKey("tg_user.id"), nullable=True)
    tg_user = db.relationship("TgUser", backref=db.backref("commands"))
    command = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(100), nullable=False, default="primary")
    is_from_server = db.Column(db.Boolean, nullable=False)
    is_sent = db.Column(db.Boolean, nullable=False, default=False)
    is_tg = db.Column(db.Boolean, nullable=False, default=False)
    time = db.Column(db.Integer, nullable=False)


class CommandArgument(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    command_id = db.Column(db.Integer, db.ForeignKey("command.id"), nullable=False)
    command = db.relationship("Command", backref=db.backref("arguments"))
    position = db.Column(db.Integer, nullable=False)
    argument = db.Column(db.Text, nullable=False)


class IgnoreRule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False)
    client = db.relationship("Client", backref=db.backref("ignorerules"))
    rule = db.Column(db.String(100), nullable=False)
