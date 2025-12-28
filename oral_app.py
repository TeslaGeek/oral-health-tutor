import os

from flask import Flask, redirect, url_for
from dotenv import load_dotenv

# Ensure env vars are loaded before importing modules that require them
load_dotenv()

from website.oral import oral_bp


def create_app():
    # Serve static assets from the existing website/static folder to reuse styling.
    app = Flask(
        __name__,
        static_folder="website/static",
        template_folder="website/templates",
    )
    secret = os.getenv("FLASK_SECRET_KEY") or os.getenv("SECRET_KEY")
    if not secret:
        # Fallback for local dev; set FLASK_SECRET_KEY in .env for stability.
        secret = os.urandom(32)
    app.config["SECRET_KEY"] = secret
    app.register_blueprint(oral_bp, url_prefix="/oral")
    app.jinja_env.globals.setdefault("csrf_token", lambda: "")

    @app.route("/")
    def index():
        return redirect(url_for("oral.welcome"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
