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
