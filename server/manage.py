"""
Manages dbs, flask and more
"""
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_bcrypt import Bcrypt
from sqlalchemy import MetaData
import dotenv
import os

dotenv.load_dotenv(".env")

convention = {
    "ix": 'ix_%(column_0_label)s',
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///usb_antiinsider.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.getenv("USB_SECRET_KEY")
metadata = MetaData(naming_convention=convention)
db = SQLAlchemy(app, metadata=metadata)
migrate = Migrate(app, db)
bcrypt = Bcrypt(app)

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
