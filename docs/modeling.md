# Modeling

The preserved binary target is one when the maximum close from the next session through the next 50 sessions is at least 10% above the prediction close. The current row is excluded from the future maximum. The final 50 rows per ticker remain unlabeled.

Features preserve 1/5/10/20-session returns, 5/10/20/50/100/200 moving averages and close relationships, 200-session momentum, 10/20-session volatility, RSI-14, MACD/signal/histogram, five-session volume change, and dollar volume. Formula metadata describes important features. Missing values remain null until their lookbacks are available; raw prices are never forward-filled.

Evaluation uses chronological dates, an explicit 50-session embargo between training and validation, deterministic seed 42, XGBoost histogram trees, and no final-period tuning. Metrics include ROC AUC, accuracy, balanced accuracy, precision, recall, F1, Brier score, and majority baseline. The legacy command also records confusion-matrix counts and accuracy relative to baseline.

Artifacts and metadata carry dataset, feature-manifest, and artifact SHA-256 hashes, periods, hyperparameters, metrics, approval state, and limitations. Training yields a candidate/evaluated model; only an explicit registry approval permits signals. Promotion should require stable walk-forward results, acceptable calibration/turnover/cost sensitivity, no final-test tuning, and reviewer approval. The fixture policy is test-only.

Known biases: the supplied universe is not fully point-in-time, so survivorship bias remains; delisting history and corporate actions require a qualified provider; classification metrics do not prove strategy returns; the supplied data quality scan found 85 OHLC high/low relationship anomalies that must be investigated before research promotion.

