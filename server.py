from flask import Flask, jsonify, request, send_from_directory
from advisor import advise, clean_choices

app = Flask(__name__, static_folder="static", static_url_path="")

STATE = {
    "running": False,
    "prompt": "",
    "choices": [],
    "pick": "",
    "reason": "",
    "error": "",
}


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.post("/api/advise")
def api_advise():
    data = request.get_json(force=True, silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    choices = data.get("choices") or []
    if isinstance(choices, str):
        choices = [c.strip() for c in choices.split("\n") if c.strip()]
    if not choices and prompt:
        lines = [l.strip() for l in prompt.splitlines() if l.strip()]
        if len(lines) >= 3:
            prompt = lines[0]
            choices = lines[1:]
    cleaned = clean_choices(choices)
    pick, reason = advise(prompt, cleaned)
    return jsonify(
        {
            "prompt": prompt,
            "choices": cleaned,
            "pick": pick,
            "reason": reason,
        }
    )


@app.get("/api/status")
def api_status():
    choices = clean_choices(STATE.get("choices") or [])
    pick = STATE.get("pick") or ""
    reason = STATE.get("reason") or ""
    if pick and not clean_choices([pick]):
        pick, reason = advise(STATE.get("prompt") or "", choices)
        STATE["pick"] = pick
        STATE["reason"] = reason
        STATE["choices"] = choices
    return jsonify(
        {
            "running": STATE.get("running"),
            "prompt": STATE.get("prompt"),
            "choices": choices,
            "pick": STATE.get("pick") or "",
            "reason": STATE.get("reason") or "",
            "error": STATE.get("error") or "",
        }
    )


@app.post("/api/browser/start")
def browser_start():
    if STATE["running"]:
        return jsonify({"ok": True, "message": "deja lance"})
    from browser_watcher import start_watcher

    STATE["pick"] = ""
    STATE["choices"] = []
    STATE["prompt"] = ""
    STATE["reason"] = ""
    STATE["error"] = ""
    start_watcher(STATE)
    return jsonify({"ok": True, "message": "navigateur en cours d'ouverture"})


@app.post("/api/browser/stop")
def browser_stop():
    from browser_watcher import stop_watcher

    stop_watcher(STATE)
    return jsonify({"ok": True})


if __name__ == "__main__":
    print("Destiny Eleven Coach -> http://127.0.0.1:5055")
    app.run(host="127.0.0.1", port=5055, debug=False, threaded=True)
