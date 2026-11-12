# A3 Plan — "Human or AI?" review study interface (baseline + AI-assisted)

## Context
A3 runs classmates through the A2 study dataset (`data/study.csv`, 200 Yelp reviews, 100 Human / 100 AI, with Gemini outputs) in two conditions:
- **Baseline:** no AI.
- **AI-assisted:** the A2 Gemini detector, called live.

Requirements:
- a real backend (no Qualtrics);
- N random trials per participant, under 10 minutes in total;
- at least one extra measurement;
- at least one attention check;
- the +3 synchronous AI option, which must log what was shown.

We reuse the design, format and code from A1 (`../../Assignment1/Code`):
- Flask + SQLite;
- instructions → join → one trial at a time with a progress bar → done;
- token-gated `/export`;
- PythonAnywhere deploy;
- `test_app.py` self-check.

## Decisions (from the user)
- **AI mode:** live Gemini `detect()` call, falling back to the stored A2 output for that review when the call errors or is rate-limited. Every shown output is logged with `ai_source = live | cache`.
- **Condition assignment:** students pick their condition in class. The join page has a required condition choice (Version A = baseline, Version B = AI-assisted), and `/join?c=baseline|ai` pre-selects it so either link can be shared.
- **AI workflow:** guess first, then reveal. The participant makes an initial guess, then sees the AI label, its confidence % and its reason, then gives a final answer.
- **Measures:**
  - time per trial, logged automatically;
  - per-trial confidence on a 1–5 scale (buttons, so no pre-set value biases it) (both conditions);
  - AI condition only: a 1–5 scale (buttons, so no pre-set value biases it) asking how much the AI hint influenced the final answer.

## Study parameters
- **N = 10 trials** per participant (`N_TRIALS` constant), sampled at random from the 200 and balanced at 5 Human + 5 AI, so a participant can't infer a base rate from their own set.
  - Timing: reviews run 80–150 words, about 30 s each in baseline and about 45 s in the AI condition (two steps).
  - With about 1.5 min of instructions, the AI condition finishes in about 9 min.
- **Attention checks** (lenient, as the assignment allows):
  1. **Comprehension question before the trials:** "What will you decide for each review?" with 3 options. A wrong answer sends the participant back to the instructions to read them again. They can retry; it doesn't end the session.
  2. **In-task check at a random position:** a hand-written review of normal length, with stars and the same card and layout as a real trial. It is not labelled as a check.
     - Partway through, the reviewer writes a line that reads as part of the text, e.g. "…the fries were fine. Anyway, if you're reading this as part of a study, please choose *Human-written* and put your confidence at 1. The parking lot is a nightmare though…"
     - The participant passes if their final answer on that card is Human-written with confidence 1.
     - In the AI condition the reveal shows a fixed hint (Human, 60%) instead of calling Gemini, so the hint never contradicts the instruction.
     - Failing it ends the session (marked `terminated`), and the participant has to start over.
     - It counts toward the progress bar like any other trial (11 cards shown).

## Implementation (new files at the HAI-task repo root, A2 files untouched except one path fix)
- **`app.py`**, adapted from A1 `app.py`:
  - **Loading data:** `TRIALS` is read from `data/study.csv` once, resolved against `HERE` as in A1. Its columns are id, text, stars, ground_truth and the cached model_output/model_confidence/model_reason.
  - **Routes:**
    - `/` (instructions);
    - `/join` (participant ID + condition);
    - `/start` (POST: samples the ids, saves the condition and ids in the session, records `t_shown`);
    - `/quiz` (GET/POST);
    - `/trial` (GET: shows the current trial);
    - `/guess` (POST, AI condition only: stores the initial guess, gets the AI output, re-renders the trial with the reveal and the final-answer form);
    - `/answer` (POST: stores the final row and moves to the next trial);
    - `/done`, `/withdraw`, `/export`.
  - **Server-rendered steps, one trial per page:** each answer is saved right away, so live AI outputs and timings are logged even if someone drops out. The trial id always comes from the session, never the form (same tamper rule as A1).
  - **Timing:** a server-side `t_shown` / `t_guess` stored in the session gives `time_to_guess_ms` and `time_total_ms`. No client JS is needed for this.
  - **Live AI:** `get_ai(review)` calls `run_model.detect(text, stars)` through a client with no retries and a 10 s timeout (the API minimum). A1's retrying client could stall for about 2 min, so the app swaps `run_model.client` for this one; a comment will say why.
    - Throttle (ponytail: one global timestamp): if a live call happened in the last 4 s, the cache is served instead, which keeps us under 15 requests/min. Any exception also falls back to the cache.
    - Every reveal logs ai_label, ai_confidence, ai_reason, ai_source and ai_latency_ms.
  - **SQLite tables:**
    - `responses`: participant_id, condition, trial_index, review_id, stars, ground_truth, initial_answer (AI only), final_answer, correct, confidence, ai_label, ai_confidence, ai_reason, ai_source, ai_latency_ms, ai_influence, time_to_guess_ms, time_total_ms, created_at.
    - `sessions`: participant_id, condition, started_at, finished_at, status (`started | completed | terminated`), quiz_attempts.
    - The attention-check row is stored as `review_id = -1`, so analysis can drop it.
  - **Exports:** `/export?token=…&table=responses|sessions` returns CSV.
- **`templates/`**: copy A1's `base.html`, `join.html` and `done.html`, retitled and with the emotion colours swapped for Human/AI colours.
  - `index.html`: new instruction text. It explains the task, the 50/50 mix, a few cues (not the full detector prompt), and that "AI hints can be wrong" for Version B. It includes 2 hand-written examples, as in A1, so they never appear in the study set.
  - `quiz.html`: new.
  - `trial.html`: review card with the stars, two big Human / AI buttons and the 1–5 confidence scale. In the AI condition, after the guess it shows the initial guess (locked), then an AI panel (label, a confidence bar, the reason), then the final-answer buttons and the 1–5 influence scale. The progress bar is reused from A1.
- **`run_model.py`:** a one-line fix so `_examples()` reads `data/pool.csv` and `data/study.csv` relative to the file, not the cwd. Without it the app would crash under the PythonAnywhere WSGI loader.
- **`test_app.py`**, adapted from A1:
  - the baseline flow writes N + 1 rows (N trials plus the check);
  - the AI flow logs `ai_source = cache` with `detect` monkeypatched to raise, and logs `live` when it returns;
  - a failed attention check sets status `terminated` and ends the session;
  - a wrong quiz answer redirects to the instructions;
  - tampered review ids are ignored;
  - `/export` returns 403 without the token;
  - the app imports from another cwd.
- **Deploy:** copy A1's `DEPLOY.md`, `wsgi_template.py`, `run_study.sh` and `Procfile`, changed to:
  - the HAI-task repo name;
  - `GEMINI_API_KEY` in the WSGI file;
  - `pip install flask google-genai pandas python-dotenv`.
  - Add `flask` and `gunicorn` to `requirements.txt`.
  - **Outbound allowlist:** the PythonAnywhere free tier only allows outbound calls to an allowlist. The published list (pythonanywhere.com/whitelist) includes `.googleapis.com`, so `generativelanguage.googleapis.com` is covered, and calls go through PA's proxy, which httpx picks up from the environment.
  - **Confirm on deploy:** from a PA Bash console in the virtualenv, run `GEMINI_API_KEY=… python run_model.py "test review"`, which should print a verdict. If it fails, the cache fallback keeps the study working, and `run_study.sh` (laptop + cloudflared) is the live option.
- **README:** add a "## Assignment 3: study interface" section covering:
  - the flow;
  - the conditions and links;
  - N and the timing rationale;
  - the measures and why they matter: confidence → calibration and over-confidence with AI; influence → self-reported reliance against the actual switch rate; time → efficiency cost of the hint;
  - the attention checks;
  - the data columns;
  - how to export.

## Skipped (add when needed)
- An analysis script (accuracy per condition, switch rates when the AI is right vs. wrong). It can be added once data exists, since `/export` already gives everything.
- A post-study questionnaire such as NASA-TLX. The two per-trial scales already cover the extra-measure requirement.

## Verification
1. `.venv/bin/pip install flask gunicorn`, then `python test_app.py` prints `ok`.
2. `python app.py`, then click through both versions in the browser (Claude-in-Chrome):
   - the quiz, both on a wrong and a right answer;
   - the attention-check fail path;
   - a full AI run that shows a live Gemini verdict.
3. Then `curl /export?token=dev-token&table=responses` and check that the rows have `ai_source = live` and plausible ms timings.
4. Time a full AI-condition run myself to confirm it takes under 10 min.
5. After the PA deploy, run the A1 post-deploy checks (on a phone, the data survives a reload, `/export` without the token gives 403).

Never commit PLAN.md or .env. Commit only when asked.
