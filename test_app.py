"""Self-check: python test_app.py  (no API key or network needed; the detector is faked)"""
import os
import subprocess
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
import app as A  # noqa: E402


class FakeDetector:
    fail = False

    def detect(self, text, stars):
        if self.fail:
            raise RuntimeError("429")
        return {"model_output": "AI", "model_confidence": 77, "model_reason": "live reason"}


A.run_model = FakeDetector()
A.LIVE_GAP = 0


def q(sql):
    with A.db() as con:
        return con.execute(sql).fetchall()


def begin(c, pid, cond):
    c.post("/start", data={"participant_id": pid, "condition": cond})
    c.post("/quiz", data={"answer": A.QUIZ_OPTIONS[1]})
    with c.session_transaction() as s:
        return s["ids"], s["sid"]


def step(c, i, check_ok=True, ai=False):
    with c.session_transaction() as s:
        is_check = s["ids"][i] == A.CHECK_ID
    if ai:
        c.post("/guess", data={"step": i, "answer": "AI"})
    ans, conf = ("Human", 1) if (is_check and check_ok) else ("AI", 4)
    form = {"step": i, "answer": ans, "confidence": conf}
    if ai:
        form["influence"] = 3
    return c.post("/answer", data=form)


A.app.config["TESTING"] = True
with A.app.test_client() as c:
    assert b"Start the study" in c.get("/").data
    assert b"Version B" in c.get("/join?c=ai").data

    # bad join is rejected and nothing starts
    assert c.post("/start", data={"participant_id": " ", "condition": "ai"}).status_code == 400
    assert c.post("/start", data={"participant_id": "x", "condition": "zzz"}).status_code == 400
    assert q("SELECT * FROM sessions") == []

    # wrong quiz answer sends you back to the instructions, the trials stay locked
    c.post("/start", data={"participant_id": "pq", "condition": "baseline"})
    r = c.post("/quiz", data={"answer": A.QUIZ_OPTIONS[0]})
    assert "retry=1" in r.headers["Location"]
    assert c.get("/trial").headers["Location"].endswith("/")
    assert b"try the question again" in c.get("/?retry=1").data
    c.post("/quiz", data={"answer": A.QUIZ_OPTIONS[1]})
    assert q("SELECT quiz_attempts FROM sessions WHERE participant_id='pq'") == [(2,)]

    # baseline: 10 balanced reviews + 1 check, the check never first or last
    ids, sid = begin(c, "p1", "baseline")
    assert len(ids) == A.N_TRIALS + 1 and ids.count(A.CHECK_ID) == 1
    assert ids[0] != A.CHECK_ID and ids[-1] != A.CHECK_ID
    real = [A.REVIEWS[i]["ground_truth"] for i in ids if i != A.CHECK_ID]
    assert real.count("Human") == real.count("AI") == A.N_TRIALS // 2
    assert b"influence" not in c.get("/trial").data          # no AI questions in baseline

    # incomplete or stale answers write nothing
    c.post("/answer", data={"step": 0, "answer": "AI"})                      # no confidence
    c.post("/answer", data={"step": 5, "answer": "AI", "confidence": 3})    # wrong step
    assert q(f"SELECT * FROM responses WHERE session_id='{sid}'") == []

    for i in range(len(ids)):
        r = step(c, i)
    assert c.get("/trial").headers["Location"].endswith("/done")
    rows = q(f"SELECT review_id, ai_label, correct, time_total_ms FROM responses WHERE session_id='{sid}'")
    assert sorted(r[0] for r in rows) == sorted(ids)
    assert all(r[1] is None for r in rows)                                 # no AI shown
    assert all(r[2] is None for r in rows if r[0] == A.CHECK_ID)
    assert all(r[3] >= 0 for r in rows)
    assert q(f"SELECT status FROM sessions WHERE session_id='{sid}'") == [("completed",)]

    # AI condition: live hint is logged; a failing call falls back to the stored A2 output
    ids, sid = begin(c, "p2", "ai")
    c.post("/answer", data={"step": 0, "answer": "AI", "confidence": 3, "influence": 3})
    assert q(f"SELECT * FROM responses WHERE session_id='{sid}'") == [], "final before guess"
    for i in range(len(ids)):
        A.run_model.fail = i % 2 == 1
        if i == 0:
            c.post("/guess", data={"step": 0, "answer": "AI"})
            assert b"live reason" in c.get("/trial").data
            c.post("/guess", data={"step": 0, "answer": "Human"})            # can't re-guess
            form = {"step": 0, "answer": "AI", "confidence": 4, "influence": 3}
            c.post("/answer", data=form)
        else:
            step(c, i, ai=True)
    A.run_model.fail = False
    rows = q(f"SELECT trial_index, review_id, initial_answer, ai_label, ai_source, ai_reason, "
             f"ai_influence, time_to_guess_ms FROM responses WHERE session_id='{sid}' ORDER BY trial_index")
    assert len(rows) == len(ids) and rows[0][2] == "AI"
    for idx, rid, init, label, src, reason, infl, tg in rows:
        if rid == A.CHECK_ID:
            assert src == "fixed" and label == "Human"
        elif idx % 2 == 0:
            assert src == "live" and reason == "live reason"
        else:
            assert src == "cache" and reason == A.REVIEWS[rid]["model_reason"]
        assert infl == 3 and tg is not None

    # failing the hidden check ends the session
    ids, sid = begin(c, "p3", "baseline")
    for i in range(ids.index(A.CHECK_ID) + 1):
        r = step(c, i, check_ok=False)
    assert b"This session has ended" in r.data
    assert q(f"SELECT status FROM sessions WHERE session_id='{sid}'") == [("terminated",)]
    assert c.get("/trial").headers["Location"].endswith("/")

    # participants get independently sampled sets
    assert len({tuple(begin(c, f"s{n}", "baseline")[0]) for n in range(8)}) > 1

    # withdrawing marks the session
    _, sid = begin(c, "pw", "ai")
    c.get("/withdraw")
    assert q(f"SELECT status FROM sessions WHERE session_id='{sid}'") == [("withdrawn",)]

    # export is token-gated
    assert c.get("/export").status_code == 403
    assert c.get(f"/export?token={A.EXPORT_TOKEN}&table=bogus").status_code == 400
    csv = c.get(f"/export?token={A.EXPORT_TOKEN}").data.decode()
    assert csv.count("\n") == len(q("SELECT * FROM responses")) + 1
    assert "ai_source" in csv.splitlines()[0]
    assert "terminated" in c.get(f"/export?token={A.EXPORT_TOKEN}&table=sessions").data.decode()

# A WSGI server imports the app from a different working directory.
here = os.path.dirname(os.path.abspath(__file__))
probe = subprocess.run(
    [sys.executable, "-c", f"import sys; sys.path.insert(0, {here!r}); import app;"
     " assert len(app.REVIEWS) == 200; assert app.DB_PATH.startswith('/')"],
    cwd="/", capture_output=True, text=True)
assert probe.returncode == 0, f"app is not importable from another cwd:\n{probe.stderr}"
print("ok")
