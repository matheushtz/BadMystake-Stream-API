import importlib.util
import os
from pathlib import Path


_APP_PATH = Path(__file__).resolve().parent / "py" / "app.py"
_SPEC = importlib.util.spec_from_file_location("badmystake_stream_api", _APP_PATH)

if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar a aplicacao em {_APP_PATH}")

_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

app = _MODULE.app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
