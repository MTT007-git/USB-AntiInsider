"""
Main script for server
"""
from manage import *
from userapi import api as userapi
from api import api, start_tg
from web import web
import os

app.register_blueprint(userapi, url_prefix="/api/user")
app.register_blueprint(api, url_prefix="/api/client")
app.register_blueprint(web)

if __name__ == "__main__":
    if os.getenv("WERKZEUG_RUN_MAIN") == "true":
        start_tg()
    app.run(port=int(os.getenv("USB_PORT", "8080")), debug=True)
