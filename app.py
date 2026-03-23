from flask import Flask, request, Response
import os

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILE_PATH = os.path.join(BASE_DIR, "dados.txt")

# Criar arquivo se nao existir
if not os.path.exists(FILE_PATH):
    open(FILE_PATH, "w").close()


def increment_deaths_in_file():
    with open(FILE_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    found = False
    new_total = 1

    for i, line in enumerate(lines):
        if line.strip().upper().startswith("MORTES:"):
            raw_value = line.split(":", 1)[1].strip()
            try:
                current_total = int(raw_value)
            except ValueError:
                current_total = 0

            new_total = current_total + 1
            lines[i] = f"MORTES: {new_total}\n"
            found = True
            break

    if not found:
        lines.insert(0, f"MORTES: {new_total}\n")

    with open(FILE_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)

    return new_total


@app.route("/save", methods=["GET", "POST"])
def save():
    text = request.args.get("text") or request.form.get("text")

    if not text:
        return {"error": "Nenhum texto enviado"}, 400

    with open(FILE_PATH, "a", encoding="utf-8") as f:
        f.write(text + "\n")

    return {"status": "salvo", "text": text}


@app.route("/get", methods=["GET"])
@app.route("/read", methods=["GET"])
def read_text_file():
    with open(FILE_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    return Response(content, mimetype="text/plain")


@app.route("/clear", methods=["GET"])
def clear():
    open(FILE_PATH, "w").close()
    return {"status": "arquivo limpo"}


@app.route("/increment", methods=["GET", "POST"])
def increment():
    new_total = increment_deaths_in_file()
    return {"status": "incrementado", "mortes": new_total}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
