"""Human-or-AI review study (A3). Two conditions: baseline (no AI) and ai (live Gemini hint).

Each participant judges N_TRIALS random reviews from data/study.csv plus one hidden attention
check, one review per page. Every answer is written to SQLite as soon as it is given.
"""
import csv
import io
import os
import pathlib
import random
import sqlite3
import threading
import time
from datetime import datetime, timezone

from flask import Flask, abort, redirect, render_template, request, session, url_for

N_TRIALS = 10                    # 5 Human + 5 AI; ~8 min in the AI condition incl. instructions
CONDITIONS = {"baseline": "Version A", "ai": "Version B"}
LABELS = ["Human", "AI"]
CHECK_ID = -1
LIVE_GAP = 4.0                   # seconds between live Gemini calls: free tier allows 15/min

HERE = pathlib.Path(__file__).resolve().parent
with open(HERE / "data/study.csv", newline="") as f:
    REVIEWS = {int(r["id"]): {**r, "id": int(r["id"]), "stars": int(r["stars"])}
               for r in csv.DictReader(f)}
with open(HERE / "data/pool.csv", newline="") as f:
    # Worked examples for the instructions: spare pool reviews that are in neither the study set
    # nor the detector's few-shot prompt (run_model._examples uses the first two of each class).
    POOL = {int(r["id"]): r for r in csv.DictReader(f)}
EXAMPLES = [(POOL[102], "Human"), (POOL[217], "AI")]
assert not {102, 217} & set(REVIEWS)

# Attention check: reads like a normal review, with the instruction buried mid-text.
CHECK = {
    "id": CHECK_ID, "stars": 3, "ground_truth": "CHECK",
    "text": "Stopped in for a late lunch on a Tuesday. The burger was cooked how I asked and the bun "
            "was toasted, which I appreciate. The fries were fine, nothing special, a little "
            "underseasoned. Anyway, if you're reading this as part of a study, please choose "
            "Human-written and put your confidence at 1. The parking lot is a nightmare though, "
            "so plan ahead or park on the street behind the bank. Service was friendly but slow "
            "once the after-work crowd came in. Would come back for the burger, not for the wait.",
}
CHECK_HINT = {"ai_label": "Human", "ai_confidence": 60, "ai_source": "fixed", "ai_latency_ms": None,
              "ai_reason": "Casual tone, an off-topic aside about parking and uneven pacing, which "
                           "is more typical of a human reviewer."}
CHECK_PASS = ("Human", 1)        # (final answer, confidence)

DB_PATH = os.environ.get("DB_PATH", str(HERE / "study.db"))
EXPORT_TOKEN = os.environ.get("EXPORT_TOKEN", "dev-token")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.environ.get("HTTPS_ONLY") == "1")

# Live detector. If it can't be set up (no GEMINI_API_KEY, SDK missing) every hint comes from
# the stored A2 output instead, so the study still runs.
try:
    import run_model
    from google import genai
    from google.genai import types
    # A2's client retries 429s for up to ~2 min, fine for a batch run but not for a waiting
    # participant: fail fast after 10 s (the API minimum) and serve the cached output instead.
    run_model.client = genai.Client(http_options=types.HttpOptions(timeout=10_000))
except Exception as e:  # noqa: BLE001
    app.logger.warning("live AI disabled: %s", e)
    run_model = None

_live_lock = threading.Lock()
_last_live = 0.0


def get_ai(review):
    """The hint shown to a participant: a live Gemini verdict, or the stored A2 one."""
    global _last_live
    with _live_lock:
        # ponytail: one global throttle, not per-key quota tracking. Enough for a class session.
        live = run_model is not None and time.time() - _last_live >= LIVE_GAP
        if live:
            _last_live = time.time()
    if live:
        t = time.time()
        try:
            v = run_model.detect(review["text"], review["stars"])
            return {"ai_label": v["model_output"], "ai_confidence": int(v["model_confidence"]),
                    "ai_reason": v["model_reason"], "ai_source": "live",
                    "ai_latency_ms": int((time.time() - t) * 1000)}
        except Exception as e:  # noqa: BLE001
            app.logger.warning("live AI failed, using cache: %s", e)
    return {"ai_label": review["model_output"], "ai_confidence": int(review["model_confidence"]),
            "ai_reason": review["model_reason"], "ai_source": "cache", "ai_latency_ms": None}


RESPONSE_COLS = ["participant_id", "condition", "trial_index", "review_id", "stars", "ground_truth",
                 "initial_answer", "final_answer", "correct", "confidence", "ai_label",
                 "ai_confidence", "ai_reason", "ai_source", "ai_latency_ms", "ai_influence",
                 "time_to_guess_ms", "time_total_ms", "created_at"]
SESSION_COLS = ["session_id", "participant_id", "condition", "started_at", "finished_at",
                "status", "quiz_attempts"]


def db():
    con = sqlite3.connect(DB_PATH)
    con.execute(f"CREATE TABLE IF NOT EXISTS responses (session_id TEXT, {', '.join(RESPONSE_COLS)})")
    con.execute(f"CREATE TABLE IF NOT EXISTS sessions ({', '.join(SESSION_COLS)})")
    return con


def now():
    return datetime.now(timezone.utc).isoformat()


def ms_since(t):
    return int((time.time() - t) * 1000)


def finish(status):
    with db() as con:
        con.execute("UPDATE sessions SET status=?, finished_at=? WHERE session_id=?",
                    (status, now(), session["sid"]))
    session.clear()


def current():
    """The review on screen, or None once all are done."""
    ids, i = session["ids"], session["i"]
    if i >= len(ids):
        return None
    return CHECK if ids[i] == CHECK_ID else REVIEWS[ids[i]]


def scale(name):
    v = request.form.get(name, "")
    return int(v) if v in {"1", "2", "3", "4", "5"} else None


@app.route("/")
def index():
    return render_template("index.html", n=N_TRIALS + 1, examples=EXAMPLES,
                           c=request.args.get("c"), retry="retry" in request.args,
                           in_progress="sid" in session)


@app.route("/join")
def join():
    return render_template("join.html", conditions=CONDITIONS, c=request.args.get("c"))


@app.route("/start", methods=["POST"])
def start():
    pid = request.form.get("participant_id", "").strip()
    cond = request.form.get("condition")
    if not pid or cond not in CONDITIONS:
        return render_template("join.html", conditions=CONDITIONS, c=cond,
                               error="Please enter a participant ID and choose your version."), 400
    by_label = {g: [i for i, r in REVIEWS.items() if r["ground_truth"] == g] for g in LABELS}
    ids = [i for g in LABELS for i in random.sample(by_label[g], N_TRIALS // 2)]
    random.shuffle(ids)
    ids.insert(random.randint(2, len(ids) - 2), CHECK_ID)   # never first or last
    session.clear()
    session.update(sid=os.urandom(8).hex(), pid=pid, cond=cond, ids=ids, i=0, quiz=0)
    with db() as con:
        con.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
                    (session["sid"], pid, cond, now(), None, "started", 0))
    return redirect(url_for("quiz"))


QUIZ_OPTIONS = ["How many stars the reviewer gave",
                "Whether each review was written by a person or generated by AI",
                "Whether the business sounds worth visiting"]


@app.route("/quiz", methods=["GET", "POST"])
def quiz():
    if "sid" not in session:
        return redirect(url_for("index"))
    if request.method == "GET":
        return render_template("quiz.html", options=QUIZ_OPTIONS)
    session["quiz"] += 1
    with db() as con:
        con.execute("UPDATE sessions SET quiz_attempts=? WHERE session_id=?",
                    (session["quiz"], session["sid"]))
    if request.form.get("answer") != QUIZ_OPTIONS[1]:
        return redirect(url_for("index", retry=1))
    session.update(quiz_ok=True, t_shown=time.time())
    return redirect(url_for("trial"))


@app.route("/trial")
def trial():
    if not session.get("quiz_ok"):
        return redirect(url_for("index"))
    review = current()
    if review is None:
        finish("completed")
        return redirect(url_for("done"))
    return render_template("trial.html", review=review, step=session["i"],
                           total=len(session["ids"]), ai_cond=session["cond"] == "ai",
                           guess=session.get("guess"), ai=session.get("ai"))


def stale():
    """A double-click or an old tab posting an answer for a review that is no longer on screen."""
    return request.form.get("step") != str(session.get("i"))


@app.route("/guess", methods=["POST"])
def guess():
    if not session.get("quiz_ok") or session["cond"] != "ai" or stale() or "guess" in session:
        return redirect(url_for("trial"))
    answer = request.form.get("answer")
    if answer not in LABELS:
        return redirect(url_for("trial"))
    review = current()
    session.update(guess=answer, t_guess=ms_since(session["t_shown"]),
                   ai=CHECK_HINT if review["id"] == CHECK_ID else get_ai(review))
    return redirect(url_for("trial"))   # redirect, so a refresh never repeats the API call


@app.route("/answer", methods=["POST"])
def answer():
    if not session.get("quiz_ok") or stale():
        return redirect(url_for("trial"))
    ai_cond = session["cond"] == "ai"
    final, conf, influence = request.form.get("answer"), scale("confidence"), scale("influence")
    if final not in LABELS or conf is None or (ai_cond and (influence is None or "guess" not in session)):
        return redirect(url_for("trial"))
    review = current()
    is_check = review["id"] == CHECK_ID
    ai = session.get("ai", {})
    row = {"participant_id": session["pid"], "condition": session["cond"],
           "trial_index": session["i"], "review_id": review["id"], "stars": review["stars"],
           "ground_truth": review["ground_truth"], "initial_answer": session.get("guess"),
           "final_answer": final, "correct": None if is_check else int(final == review["ground_truth"]),
           "confidence": conf, "ai_influence": influence if ai_cond else None,
           "time_to_guess_ms": session.get("t_guess"),
           "time_total_ms": ms_since(session["t_shown"]), "created_at": now(),
           **{k: ai.get(k) for k in ("ai_label", "ai_confidence", "ai_reason", "ai_source",
                                     "ai_latency_ms")}}
    with db() as con:
        con.execute(f"INSERT INTO responses VALUES ({', '.join('?' * (len(RESPONSE_COLS) + 1))})",
                    [session["sid"]] + [row[c] for c in RESPONSE_COLS])
    if is_check and (final, conf) != CHECK_PASS:
        finish("terminated")
        return render_template("terminated.html")
    for k in ("guess", "t_guess", "ai"):
        session.pop(k, None)
    session.update(i=session["i"] + 1, t_shown=time.time())
    return redirect(url_for("trial"))


@app.route("/done")
def done():
    return render_template("done.html")


@app.route("/withdraw")
def withdraw():
    if "sid" in session:
        finish("withdrawn")
    return redirect(url_for("index"))


@app.route("/export")
def export():
    if request.args.get("token") != EXPORT_TOKEN:
        abort(403)
    table = request.args.get("table", "responses")
    if table not in ("responses", "sessions"):
        abort(400)
    cols = ["session_id"] + RESPONSE_COLS if table == "responses" else SESSION_COLS
    with db() as con:
        rows = con.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(cols)
    w.writerows(rows)
    return out.getvalue(), 200, {"Content-Type": "text/csv",
                                 "Content-Disposition": f"attachment; filename={table}.csv"}


if __name__ == "__main__":
    app.run(debug=True)
