import os
import threading
from flask import Flask
from main import main  # import your bot's entry point

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

def run_bot():
    main()

if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
