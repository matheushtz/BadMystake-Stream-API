from flask import Flask, request, Response
import os

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILE_PATH = os.path.join(BASE_DIR, "dados.txt")

# Criar arquivo se nao existir
if not os.path.exists(FILE_PATH):
    open(FILE_PATH, "w").close()


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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
