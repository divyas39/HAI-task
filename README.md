# HAI-task
HAI task to distinguish between AI-generated and human-generated reviews.

Each trial is a Yelp review of 80–150 words plus its star rating. The participant decides whether it was written by a **Human** or an **AI**. The AI assistant (Google Gemini, `gemini-3.5-flash-lite`, via the Gemini API) gives its own label, a confidence score (50–100) and a short reason.

## Setup
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in GEMINI_API_KEY (free at aistudio.google.com)
```
The detector model can be changed with `DETECTOR_MODEL` in `.env` (default `gemini-3.5-flash-lite`).
The AI reviews are written by Claude and judged by Gemini, so the detector never judges text from its own model family.

## Run
```bash
python generate_data.py   # data/seeds.csv, then data/pool.csv (230 texts) + data/study.csv (100 human, 100 AI)
python run_model.py       # adds model_output, model_confidence, model_reason to data/study.csv
python evaluate.py        # prints the metrics and writes data/errors.csv for error tagging
python run_model.py "some review text"   # try the detector on one review
```

## Dataset
- **Human reviews:** [Yelp/yelp_review_full](https://huggingface.co/datasets/Yelp/yelp_review_full) (test split), keeping reviews of 80–150 words. There are 46 per star rating, sampled with seed 594.
- **AI reviews:** 115 of the sampled reviews are used only as prompts and never appear in the study set. `data/seeds.csv` holds one prompt per seed: the same star rating and length, loosely based on that review's first sentence. Claude (`claude-opus-5-5`, inside Claude Code) wrote one review per prompt, without an API, and they are saved in `data/ai_reviews.jsonl`. Rerunning `generate_data.py` rebuilds the study set from that file. 18 of the 100 AI reviews in the study set fall outside 80–150 words, but the median length is 106 words for both the human and AI reviews.
- **`data/study.csv` columns:** `id, text, stars, source_model, ground_truth, model_output, model_confidence, model_reason`.

## Detector iterations (Step J)
| Version | Prompt | Accuracy | Notes |
|---|---|---|---|
| 1 | Zero-shot: label + confidence + reason | 53.0% | Labelled 190/200 "Human" with ≥80% confidence; treated conversational tone and specific details as human cues. Results: `data/study_iter1_zeroshot.csv`. |
| 2 (final) | Adds the base rate (about half are AI), AI/human cues, and 2 human + 2 AI labelled examples from the spare reviews (not in the study set) | 83.5% | Human recall 79%, AI recall 88%. Accuracy by confidence: 95–100 → 97% (61 trials), 90 → 86% (79), ≤85 → 67% (60). |

Both versions use `gemini-3.5-flash-lite` at temperature 0 with a low thinking level. `gemini-3.8-flash` was tried first, but its free tier allows only 20 requests per day. Flash-Lite's free tier allows 15 requests per minute, so `run_model.py` waits 5 s between calls. The full run takes about 17 minutes.

## Submission guide: dataset and replicating the evaluation

### Study dataset — `data/study.csv`
200 task trials (100 Human, 100 AI), one row per trial, ready to evaluate as-is:

| Column | Role | Description |
|---|---|---|
| `id` | key | Trial id (stable across all files in `data/`) |
| `text` | **input** | The review shown to the participant |
| `stars` | **input** | Star rating (1–5) shown with the review |
| `model_output` | **model output** (evaluated) | Detector's label, `Human` or `AI` |
| `model_confidence` | model output | Detector's confidence, 50–100 (used for the calibration table) |
| `model_reason` | model output | Detector's one- or two-sentence explanation (shown to participants; not scored automatically) |
| `ground_truth` | **evaluation label** | True author: `Human` (Yelp) or `AI` (Claude-written) |
| `source_model` | evaluation breakdown | `human` or `claude-opus-5-5` |

Supporting files: `data/error_tags.csv` (hand-assigned error pattern and a `reason_misstates_text` flag for each of the 33 errors), `data/model_outputs.jsonl` (raw detector responses), and `data/study_iter1_zeroshot.csv` (iteration 1 outputs).

### Replicating the reported results
No API key is needed; the model outputs are already in `data/study.csv`.
```bash
pip install -r requirements.txt
python evaluate.py
```
`evaluate.py` compares `model_output` against `ground_truth` with scikit-learn and prints:
- **Accuracy:** share of trials where `model_output == ground_truth` → **0.835**.
- **Precision / recall / F1 per class** (`classification_report`) → AI 0.807 / 0.880 / 0.842, Human 0.868 / 0.790 / 0.827.
- **Confusion matrix** (rows = truth) → Human: 79 correct, 21 called AI; AI: 88 correct, 12 called Human.
- **Calibration:** accuracy within confidence buckets (`pd.cut` at 60/70/80/90/100) → (80, 90]: 77.5% of 138; (90, 100]: 96.7% of 61.
- **Accuracy by source and by star rating** (group means of `correct`).
- **Error distribution table:** counts of `error_pattern` in `data/error_tags.csv` as a share of the 33 errors, plus how many reasons misstate the text (14/33). The script asserts that the tagged ids exactly match the current errors. The tags were assigned by hand after reading each error in `data/errors.csv`, which the script also writes.

Iteration 1's accuracy can be checked with:
```bash
python -c "import pandas as pd; d = pd.read_csv('data/study_iter1_zeroshot.csv'); print((d.ground_truth == d.model_output).mean())"   # 0.53
```

To regenerate the model outputs from scratch (needs `GEMINI_API_KEY`, ~17 min on the free tier): delete `data/model_outputs.jsonl`, then run `python run_model.py` and `python evaluate.py`. The detector runs at temperature 0, but hosted LLMs are not perfectly deterministic, so a rerun may differ by a few trials.

## Assignment 3: study interface
A Flask web app (`app.py`, `templates/`) runs the 200 study trials with participants under two conditions.
- **Version A (baseline):** no AI help.
- **Version B (AI-assisted):** after a first guess, the participant sees the Gemini detector from A2. It is called live; this is the synchronous option.

The flow follows Assignment 1:
1. Instructions page, with one real example of each class taken from spare pool reviews outside the study set.
2. Participant ID and version choice. Students pick the version they were given in class; the links `/join?c=baseline` and `/join?c=ai` pre-select it.
3. A one-question comprehension check.
4. Eleven review cards, one per page, with a progress bar.
5. A thank-you page.

```bash
pip install -r requirements.txt
python app.py          # http://127.0.0.1:5000
python test_app.py     # self-check, prints "ok" (no API key needed)
```

### Trials
- Each participant gets **10 reviews** sampled at random from `data/study.csv`: 5 human-written and 5 AI-written, in shuffled order. Participants therefore see different trials, and nobody can work out a different base rate from their own set.
- At about 30 s per review in Version A and 45 s in Version B (two steps), plus 1–2 min of instructions, the study takes under 10 minutes.

### AI assistance (Version B)
The participant locks in a first guess. The detector's opinion is then revealed:
- its label;
- its confidence, as a number and a bar;
- its one-line reason.

The participant then gives a final answer. Asking for a guess first records how often people switch to agree with the AI, which separates their own judgement from reliance on it.

`get_ai()` calls `run_model.detect()` with a 10 s timeout. It serves the stored A2 output for that review (`ai_source = cache`) when:
- the call fails;
- the call was made within 4 s of the previous live call (the free tier allows 15 requests/min);
- no `GEMINI_API_KEY` is set.

Every hint shown is logged with its source and latency.

### Extra measurements and why they matter
| Measure | Where | Why |
|---|---|---|
| Time per review (`time_total_ms`, plus `time_to_guess_ms` in B) | both | Efficiency: does the hint save time, or cost extra time spent weighing it? |
| Confidence 1–5 on the final answer | both | Calibration: does AI help make people more confident without making them more accurate (over-reliance)? |
| Influence of the hint, 1–5 | B only | Self-reported reliance, compared with the actual behaviour (how often `initial_answer != final_answer`, and whether switches follow the AI when it is wrong). |

The scales are 1–5 buttons instead of a slider, so a pre-set slider position can't bias the answer.

### Attention checks
1. **Comprehension question** before the reviews ("what will you be deciding?"). A wrong answer sends the participant back to the instructions to retry. The number of attempts is recorded in `sessions.quiz_attempts`.
2. **Hidden check review** at a random position, never first or last. It looks like any other review, but a sentence in the middle asks the reader to choose *Written by a person* with confidence *1*. Anything else ends the session (`status = terminated`) and the participant has to start over.
   - In Version B it shows a fixed hint that agrees with the instruction, so the hint never contradicts it.
   - It is stored with `review_id = -1` and `ground_truth = CHECK`.

### Data collected
`study.db` (SQLite) has two tables. Each answer is written as soon as it is given.
- **`responses`** has one row per review card:
  - `session_id, participant_id, condition, trial_index, review_id, stars, ground_truth`;
  - `initial_answer` (B only), `final_answer`, `correct`, `confidence`;
  - the hint shown: `ai_label, ai_confidence, ai_reason, ai_source` (`live` / `cache` / `fixed`), `ai_latency_ms`;
  - `ai_influence, time_to_guess_ms, time_total_ms, created_at`.
- **`sessions`** has one row per attempt: `session_id, participant_id, condition, started_at, finished_at, status` (`started` / `completed` / `terminated` / `withdrawn`) and `quiz_attempts`.

For analysis, keep sessions with `status = completed` and drop `review_id = -1`.

```bash
curl "<site>/export?token=$EXPORT_TOKEN" -o responses.csv
curl "<site>/export?token=$EXPORT_TOKEN&table=sessions" -o sessions.csv
```

### Deploy
See [DEPLOY.md](DEPLOY.md), which covers PythonAnywhere (free, permanent URL) and checking that live Gemini calls work there. `./run_study.sh` serves the study from a laptop over a temporary cloudflared link. The environment variables are the same as in A1: `SECRET_KEY`, `EXPORT_TOKEN`, `DB_PATH` and `HTTPS_ONLY`, plus `GEMINI_API_KEY`.
