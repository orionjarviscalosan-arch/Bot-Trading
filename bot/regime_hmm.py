"""
regime_hmm.py — Detección de régimen de mercado con HMM (Hidden Markov Model)

Estados típicos: bear | range | bull (ordenados por retorno medio del estado).
Fallback sin hmmlearn: clasificación por cuantiles de retorno y volatilidad.
"""
from __future__ import annotations

import logging
import warnings
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

REGIME_LABELS = ("bear", "range", "bull")

try:
    from hmmlearn.hmm import GaussianHMM
    HAS_HMMLEARN = True
except ImportError:
    HAS_HMMLEARN = False

DEFAULT_HMM_PARAMS = {
    "hmm_n_states": 3,
    "hmm_train_bars": 500,
    "hmm_refit_every": 100,
    "hmm_vol_window": 20,
    "hmm_allow_range_trades": False,
    "use_hmm_regime": False,
}


def merge_hmm_params(params: dict) -> dict:
    merged = DEFAULT_HMM_PARAMS.copy()
    merged.update({k: v for k, v in params.items() if k.startswith("hmm_") or k == "use_hmm_regime"})
    return merged


def extract_features(df: pd.DataFrame, vol_window: int = 20) -> np.ndarray:
    """Features: log-return y volatilidad rolling normalizada."""
    close = df["close"].astype(float)
    log_ret = np.log(close / close.shift(1)).fillna(0.0)
    vol = log_ret.rolling(vol_window).std().fillna(log_ret.expanding().std().fillna(0.01))
    vol = vol.replace(0, 0.01)
    feats = np.column_stack([log_ret.values, vol.values])
    return np.nan_to_num(feats, nan=0.0, posinf=0.0, neginf=0.0)


def _map_states_to_labels(model, features: np.ndarray) -> dict[int, str]:
    """Asigna bear/range/bull según retorno medio de cada estado oculto."""
    n_states = model.n_components
    state_means = []
    for s in range(n_states):
        mask = model.predict(features) == s
        if mask.any():
            state_means.append((s, float(features[mask, 0].mean())))
        else:
            state_means.append((s, 0.0))
    state_means.sort(key=lambda x: x[1])
    mapping = {}
    if n_states == 1:
        mapping[state_means[0][0]] = "range"
    elif n_states == 2:
        mapping[state_means[0][0]] = "bear"
        mapping[state_means[1][0]] = "bull"
    else:
        mapping[state_means[0][0]] = "bear"
        mapping[state_means[1][0]] = "range"
        mapping[state_means[2][0]] = "bull"
        for i, (st, _) in enumerate(state_means[3:], start=3):
            mapping[st] = REGIME_LABELS[min(i, 2)]
    return mapping


def _fit_hmm(features: np.ndarray, n_states: int):
    if len(features) < max(n_states * 10, 50):
        return None, {}
    if HAS_HMMLEARN:
        model = GaussianHMM(
            n_components=n_states,
            covariance_type="diag",
            n_iter=50,
            random_state=42,
        )
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                model.fit(features)
            mapping = _map_states_to_labels(model, features)
            return model, mapping
        except Exception as e:
            logger.debug(f"HMM fit falló: {e}")
            return None, {}
    return None, _quantile_fallback_mapping(features, n_states)


def _quantile_fallback_mapping(features: np.ndarray, n_states: int) -> dict:
    """Fallback sin hmmlearn: terciles por retorno medio rolling."""
    rets = features[:, 0]
    if n_states <= 2:
        med = np.median(rets)
        return {0: "bear" if n_states == 2 else "range", 1: "bull"}
    q33, q66 = np.percentile(rets, [33, 66])
    return {0: "bear", 1: "range", 2: "bull"}


def _predict_state(model, mapping: dict, features: np.ndarray) -> str:
    if model is None or not mapping:
        return _quantile_label(features[-1, 0], features[:, 0])
    try:
        state = int(model.predict(features[-1:])[0])
        return mapping.get(state, "range")
    except Exception:
        return "range"


def _quantile_label(last_ret: float, all_rets: np.ndarray) -> str:
    q33, q66 = np.percentile(all_rets, [33, 66])
    if last_ret <= q33:
        return "bear"
    if last_ret >= q66:
        return "bull"
    return "range"


def predict_current_regime(df: pd.DataFrame, params: dict) -> tuple[str, dict]:
    """Régimen actual para la última vela (live / diagnose)."""
    p = merge_hmm_params(params)
    train = int(p["hmm_train_bars"])
    if len(df) < train:
        return "range", {"bear": 0.33, "range": 0.34, "bull": 0.33}

    vol_w = int(p["hmm_vol_window"])
    feats = extract_features(df, vol_w)
    window = feats[-train:]
    model, mapping = _fit_hmm(window, int(p["hmm_n_states"]))
    label = _predict_state(model, mapping, window)
    probs = {lbl: 1.0 if lbl == label else 0.0 for lbl in REGIME_LABELS}
    return label, probs


def compute_regime_series(df: pd.DataFrame, params: dict) -> pd.Series:
    """
    Serie walk-forward de régimen por barra (para backtest).
    Re-entrena cada hmm_refit_every barras.
    """
    p = merge_hmm_params(params)
    train = int(p["hmm_train_bars"])
    refit = int(p["hmm_refit_every"])
    vol_w = int(p["hmm_vol_window"])
    n_states = int(p["hmm_n_states"])

    feats = extract_features(df, vol_w)
    labels = pd.Series("range", index=df.index, dtype=object)

    model = None
    mapping: dict = {}

    for i in range(train, len(df)):
        if model is None or (i - train) % refit == 0:
            window = feats[max(0, i - train):i]
            model, mapping = _fit_hmm(window, n_states)

        slice_feats = feats[max(0, i - train):i + 1]
        labels.iloc[i] = _predict_state(model, mapping, slice_feats)

    return labels


def hmm_allows_long(regime: str, params: dict) -> bool:
    p = merge_hmm_params(params)
    if regime == "bull":
        return True
    if regime == "range" and p.get("hmm_allow_range_trades"):
        return True
    return False


def hmm_allows_short(regime: str, params: dict) -> bool:
    p = merge_hmm_params(params)
    if regime == "bear":
        return True
    if regime == "range" and p.get("hmm_allow_range_trades"):
        return True
    return False


def get_hmm_pure_signal(regime: str, prev_regime: str | None,
                        has_position: bool, position_side: str | None) -> str:
    """Señal simple por transición de régimen HMM."""
    if has_position:
        if position_side == "long" and regime in ("bear",):
            return "close"
        if position_side == "short" and regime in ("bull",):
            return "close"
        return "none"

    if prev_regime != "bull" and regime == "bull":
        return "long"
    if prev_regime != "bear" and regime == "bear":
        return "short"
    return "none"
