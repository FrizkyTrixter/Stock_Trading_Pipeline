"""Chronological XGBoost evaluation, immutable artifacts, and explicit promotion."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    brier_score_loss,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from xgboost import XGBClassifier

from .features import EMBARGO_SESSIONS, chronological_split_dates
from .ids import new_id
from .security import sha256_json
from .types import FeatureSnapshot, ModelEvaluation, ModelMetadata, ModelSignal


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def metrics(
    y_true: pd.Series, probability: np.ndarray[Any, np.dtype[np.floating[Any]]]
) -> dict[str, float | int | None]:
    prediction = (probability >= 0.5).astype(int)
    return {
        "rows": int(len(y_true)),
        "roc_auc": float(roc_auc_score(y_true, probability)) if y_true.nunique() == 2 else None,
        "accuracy": float(accuracy_score(y_true, prediction)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, prediction)),
        "precision": float(precision_score(y_true, prediction, zero_division=0)),
        "recall": float(recall_score(y_true, prediction, zero_division=0)),
        "f1": float(f1_score(y_true, prediction, zero_division=0)),
        "brier_score": float(brier_score_loss(y_true, probability)),
        "majority_baseline_accuracy": float(max(y_true.mean(), 1 - y_true.mean())),
    }


@dataclass(frozen=True)
class TrainingResult:
    metadata: ModelMetadata
    evaluation: ModelEvaluation


class ModelRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def metadata_path(self, model_id: str) -> Path:
        return self.root / f"{model_id}.metadata.json"

    def save_metadata(self, metadata: ModelMetadata) -> None:
        self.metadata_path(metadata.model_id).write_text(
            metadata.model_dump_json(indent=2), encoding="utf-8"
        )

    def load_metadata(self, model_id: str) -> ModelMetadata:
        return ModelMetadata.model_validate_json(
            self.metadata_path(model_id).read_text(encoding="utf-8")
        )

    def approve(self, model_id: str, approved_by: str) -> ModelMetadata:
        current = self.load_metadata(model_id)
        updated = current.model_copy(
            update={
                "approval_state": "approved",
                "status": "approved",
                "provenance": current.provenance + (f"approved_by:{approved_by}",),
            }
        )
        self.save_metadata(updated)
        return updated

    def load_approved_model(self, model_id: str) -> tuple[XGBClassifier, ModelMetadata]:
        metadata = self.load_metadata(model_id)
        if metadata.approval_state != "approved":
            raise PermissionError("Model is not approved")
        artifact = Path(metadata.artifact_path)
        if file_sha256(artifact) != metadata.artifact_hash:
            raise RuntimeError("Model artifact integrity check failed")
        return joblib.load(artifact), metadata


def train_xgboost(
    panel: pd.DataFrame,
    feature_names: list[str],
    registry: ModelRegistry,
    train_days: int = 200,
    validation_days: int = 50,
    random_seed: int = 42,
    n_estimators: int = 100,
) -> TrainingResult:
    trainable = panel.dropna(subset=feature_names + ["Target"]).copy()
    dates = [pd.Timestamp(value) for value in sorted(trainable["Date"].unique())]
    train_dates, validation_dates = chronological_split_dates(
        dates, train_days, validation_days, EMBARGO_SESSIONS
    )
    training = trainable[trainable["Date"].isin(train_dates)]
    validation = trainable[trainable["Date"].isin(validation_dates)]
    parameters: dict[str, Any] = {
        "n_estimators": n_estimators,
        "max_depth": 4,
        "learning_rate": 0.03,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        "tree_method": "hist",
        "device": "cpu",
        "random_state": random_seed,
    }
    model = XGBClassifier(**parameters)
    model.fit(training[feature_names], training["Target"].astype(int))
    probability = model.predict_proba(validation[feature_names])[:, 1]
    measured = metrics(validation["Target"].astype(int), probability)
    model_id = new_id("model")
    artifact = registry.root / f"{model_id}.joblib"
    joblib.dump(model, artifact)
    dataset_hash = sha256_json(
        {
            "dates": [str(value) for value in dates],
            "rows": len(trainable),
            "tickers": sorted(trainable["Ticker"].unique().tolist()),
        }
    )
    feature_hash = sha256_json(feature_names)
    metadata = ModelMetadata(
        model_id=model_id,
        training_run_id=new_id("train"),
        dataset_hash=dataset_hash,
        feature_manifest_hash=feature_hash,
        training_period=(str(train_dates[0].date()), str(train_dates[-1].date())),
        validation_periods=((str(validation_dates[0].date()), str(validation_dates[-1].date())),),
        hyperparameters=parameters,
        metrics=measured,
        artifact_path=str(artifact),
        artifact_hash=file_sha256(artifact),
        status="evaluated",
        known_limitations=(
            "survivorship bias is not fully eliminated",
            "transaction costs are not part of classification metrics",
        ),
    )
    registry.save_metadata(metadata)
    eligible = bool(measured["roc_auc"] is not None and measured["roc_auc"] >= 0.5)
    evaluation = ModelEvaluation(
        model_id=model_id,
        metrics=measured,
        baseline_metrics={"majority_accuracy": measured["majority_baseline_accuracy"]},
        promotion_eligible=eligible,
        reasons=() if eligible else ("ROC AUC did not meet the conservative 0.50 floor",),
        status="evaluated",
    )
    return TrainingResult(metadata, evaluation)


def generate_signals(
    model: XGBClassifier,
    metadata: ModelMetadata,
    snapshots: tuple[FeatureSnapshot, ...],
    required_features: tuple[str, ...],
) -> tuple[ModelSignal, ...]:
    if metadata.approval_state != "approved":
        raise PermissionError("Signal generation requires an approved model")
    if metadata.feature_manifest_hash != sha256_json(list(required_features)):
        raise ValueError("Feature schema differs from approved model")
    frame = pd.DataFrame(
        [snapshot.features for snapshot in snapshots], index=[s.ticker for s in snapshots]
    )
    missing = [name for name in required_features if name not in frame.columns]
    if missing:
        raise ValueError(f"Missing required features: {missing}")
    probability = model.predict_proba(frame[list(required_features)])[:, 1]
    order = np.argsort(-probability)
    ranks = {int(index): rank + 1 for rank, index in enumerate(order)}
    now = datetime.now(UTC)
    output = []
    for index, snapshot in enumerate(snapshots):
        output.append(
            ModelSignal(
                ticker=snapshot.ticker,
                model_id=metadata.model_id,
                feature_snapshot_id=snapshot.id,
                positive_class_probability=Decimal(str(probability[index])),
                predicted_class=int(probability[index] >= 0.5),
                rank=ranks[index],
                score_percentile=Decimal(str((len(snapshots) - ranks[index] + 1) / len(snapshots))),
                major_contributing_features=tuple(required_features[:5]),
                data_as_of=snapshot.data_as_of,
                timestamp=now,
                status="generated",
            )
        )
    return tuple(output)
