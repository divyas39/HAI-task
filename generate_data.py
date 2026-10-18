"""Build the study dataset: real Yelp reviews + AI-generated reviews.

Step 1 (no AI text yet): writes data/seeds.csv, the generation prompt for each AI review.
The AI reviews were written by Claude (claude-opus-5-5, in Claude Code) from those prompts
and saved to data/ai_reviews.jsonl. No API was used for generation.
Step 2 (ai_reviews.jsonl present): writes data/pool.csv (all texts incl. spares) and
data/study.csv (200 balanced trials).
"""
import os

import pandas as pd
from datasets import load_dataset

SEED = 594
PER_LABEL = 115  # 100 study trials + 15 spares per label
STUDY_PER_LABEL = 100
GENERATOR = "claude-opus-5-5"
AI_FILE = "data/ai_reviews.jsonl"

PROMPT = """Write a Yelp review as an ordinary customer would post it.
- Rating: {stars} out of 5 stars (match the tone to the rating).
- Length: about {words} words, a single block of text.
- Loosely inspired by this opening line from another review (do NOT copy it): "{hint}"
Output only the review text, no title or star count."""


def clean(text):
    return text.replace("\\n", " ").replace('\\"', '"').replace("  ", " ").strip()


def sample_human():
    ds = load_dataset("Yelp/yelp_review_full", split="test").to_pandas()
    ds["text"] = ds["text"].map(clean)
    ds["stars"] = ds["label"] + 1
    ds = ds[ds["text"].str.split().str.len().between(80, 150)]
    # Balanced over stars: 2 * PER_LABEL reviews; half stay human, half seed the AI prompts.
    n_per_star = 2 * PER_LABEL // 5
    picked = ds.groupby("stars").sample(n_per_star, random_state=SEED)
    return picked.sample(frac=1, random_state=SEED).reset_index(drop=True)


def main():
    reviews = sample_human()
    humans, seeds = reviews.iloc[:PER_LABEL], reviews.iloc[PER_LABEL:2 * PER_LABEL]
    os.makedirs("data", exist_ok=True)

    seeds = pd.DataFrame({
        "seed": range(len(seeds)), "stars": seeds.stars.values,
        "words": seeds.text.str.split().str.len().values,
        "hint": seeds.text.str.split(".").str[0].str[:200].values,
    })
    seeds["prompt"] = [PROMPT.format(stars=s.stars, words=s.words, hint=s.hint) for s in seeds.itertuples()]
    seeds.to_csv("data/seeds.csv", index=False)
    if not os.path.exists(AI_FILE):
        print(f"wrote data/seeds.csv; generate {AI_FILE} from it, then rerun")
        return

    ai = pd.read_json(AI_FILE, lines=True).merge(seeds[["seed", "stars"]], on="seed")
    assert len(ai) == len(seeds), "need one AI review per seed"
    ai = pd.DataFrame({"text": ai.text.map(clean), "stars": ai.stars,
                       "source_model": GENERATOR, "ground_truth": "AI"})
    human = pd.DataFrame({"text": humans.text.values, "stars": humans.stars.values,
                          "source_model": "human", "ground_truth": "Human"})
    pool = pd.concat([human, ai], ignore_index=True)
    pool.insert(0, "id", range(len(pool)))
    pool.to_csv("data/pool.csv", index=False)

    study = pd.concat([pool[pool.ground_truth == g].head(STUDY_PER_LABEL) for g in ("Human", "AI")])
    study = study.sample(frac=1, random_state=SEED)
    study.to_csv("data/study.csv", index=False)
    print(f"pool={len(pool)} study={len(study)}")
    print(study.groupby(["ground_truth", "stars"]).size().unstack())


if __name__ == "__main__":
    main()
