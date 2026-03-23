from flask import Flask, request
import json
import os

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILE_PATH = os.path.join(BASE_DIR, "dados.json")
DEFAULT_DATA = {"mortes": 0}

# Criar arquivo se nao existir
if not os.path.exists(FILE_PATH):
    with open(FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_DATA, f, ensure_ascii=False, indent=2)


def load_data():
    with open(FILE_PATH, "r", encoding="utf-8") as f:
        content = f.read().strip()

    if not content:
        return dict(DEFAULT_DATA)

    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # Migra formato antigo: MORTES: X
    first_line = content.splitlines()[0] if content.splitlines() else ""
    if first_line.upper().startswith("MORTES:"):
        raw_value = first_line.split(":", 1)[1].strip()
        try:
            mortes = int(raw_value)
        except ValueError:
            mortes = 0
        return {"mortes": mortes}

    return dict(DEFAULT_DATA)


def save_data(data):
    with open(FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def parse_value(value):
    if isinstance(value, (int, float, bool)) or value is None:
        return value

    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if lowered == "null":
            return None

        try:
            return int(value)
        except ValueError:
            pass

        try:
            return float(value)
        except ValueError:
            pass

    return value


def increment_deaths_in_file():
    data = load_data()

    raw_current = data.get("mortes", 0)
    try:
        current_total = int(raw_current)
    except (TypeError, ValueError):
        current_total = 0

    new_total = current_total + 1
    data["mortes"] = new_total
    save_data(data)

    return new_total


def get_mortes_value(data):
    raw_value = data.get("mortes", 0)
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return 0


@app.route("/death/save", methods=["GET", "POST"])
def save():
    payload = request.get_json(silent=True) or {}
    key = request.args.get("key") or request.form.get("key") or payload.get("key")
    value = request.args.get("value") or request.form.get("value") or payload.get("value")

    if not key:
        return {"error": "Nenhuma chave enviada"}, 400

    data = load_data()
    data[str(key)] = parse_value(value)
    save_data(data)

    return str(get_mortes_value(data))



@app.route("/death/get", methods=["GET"])
@app.route("/death/read", methods=["GET"])
def read_text_file():
    data = load_data()
    return str(get_mortes_value(data))


@app.route("/death/read/obs", methods=["GET"])
def read_text_observation():
    data = load_data()
    return f"{get_mortes_value(data)} mortes"


@app.route("/death/clear", methods=["GET"])
def clear():
    save_data(dict(DEFAULT_DATA))
    return str(DEFAULT_DATA["mortes"])


@app.route("/death/increment", methods=["GET", "POST"])
def increment():
    new_total = increment_deaths_in_file()
    return str(new_total)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
