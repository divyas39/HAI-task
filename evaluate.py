"""Evaluate the detector on data/study.csv and dump its errors for hand-tagging.

Prints accuracy, per-class P/R/F1, confusion matrix, calibration by confidence bucket,
and accuracy by generator and star rating. Writes data/errors.csv with an empty
`error_pattern` column to fill in for the error distribution table.
"""
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

df = pd.read_csv("data/study.csv")
y, p = df.ground_truth, df.model_output
df["correct"] = y == p

print(f"Trials: {len(df)}  ({y.value_counts().to_dict()})")
print(f"Accuracy: {accuracy_score(y, p):.3f}\n")
print(classification_report(y, p, digits=3))
print("Confusion matrix (rows = truth, cols = prediction):")
print(pd.DataFrame(confusion_matrix(y, p, labels=["Human", "AI"]),
                   index=["Human", "AI"], columns=["Human", "AI"]), "\n")

df["conf_bucket"] = pd.cut(df.model_confidence, [49, 60, 70, 80, 90, 100])
print("Calibration (does confidence match accuracy?):")
print(df.groupby("conf_bucket", observed=True).correct.agg(["count", "mean"]), "\n")
print("Accuracy by source:")
print(df.groupby("source_model").correct.agg(["count", "mean"]), "\n")
print("Accuracy by stars:")
print(df.groupby("stars").correct.agg(["count", "mean"]))

errors = df[~df.correct].drop(columns=["correct", "conf_bucket"]).assign(error_pattern="")
errors.to_csv("data/errors.csv", index=False)
print(f"\n{len(errors)} errors written to data/errors.csv")

# Error distribution table from hand-assigned tags (data/error_tags.csv, one row per error).
try:
    tags = pd.read_csv("data/error_tags.csv")
except FileNotFoundError:
    tags = None
if tags is not None:
    assert set(tags.id) == set(errors.id), "error_tags.csv must tag exactly the current errors"
    table = tags.error_pattern.value_counts().to_frame("errors")
    table["% of errors"] = (100 * table.errors / len(tags)).round(1)
    print("\nError distribution:")
    print(table.to_string())
    n = tags.reason_misstates_text.sum()
    print(f"\nReason misstates the text (e.g. claims flawless grammar despite typos, "
          f"quotes phrases not present): {n}/{len(tags)} errors ({100 * n / len(tags):.0f}%)")
