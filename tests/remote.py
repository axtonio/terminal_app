from flask import Flask, jsonify, abort
import json
import os

app = Flask(__name__)


# Загружаем данные из data.json
def load_data():
    try:
        with open("data/data.json", "r") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}


# GET /key/<key_name>
@app.route("/key_ss/<key_name>", methods=["GET"])
def get_key(key_name):
    data = load_data()
    if key_name in data:
        return jsonify(data[key_name])
    else:
        abort(404, description=f"Key '{key_name}' not found")


if __name__ == "__main__":
    app.run(debug=True)
