# ML Model Agent (V2) — CLAUDE.md

# Usage: cp this file to ./CLAUDE.md in project root

# NOTE: This is V2 — only activate after V1 is profitable for 3+ months

## Role

ML engineer building a signal filter for ADA and XRP ICT/SMC signals.
The model's job: predict which V1 setups have the highest win probability.

## V2 Readiness Gate

Before writing any ML code, confirm all are true:
- [ ] V1 is live and profitable on CoinSwitch for 3+ months
- [ ] Minimum 300 labelled ADA signals available
- [ ] Minimum 200 labelled XRP signals available
- [ ] Feature engineering pipeline is running in shadow mode (logging features)
- [ ] Delta Exchange validation of feature pipeline is complete

If any are false → return to V1 development.

## Separate Models Per Asset

```python
# ADA model: trained on ADA signals only
ada_signal_filter = XGBClassifier(...)
ada_signal_filter.fit(X_ada, y_ada)

# XRP model: trained on XRP signals only
xrp_signal_filter = XGBClassifier(...)
xrp_signal_filter.fit(X_xrp, y_xrp)

# NEVER combine ADA and XRP training data
# They have different volatility, liquidity, and news dynamics
```

## ADA-Specific Features

```python
ADA_FEATURES = [
    "htf_bias",               # 4H structure: 1=LONG, -1=SHORT
    "itf_confirmation",       # 1H order flow aligned: 1=yes, 0=no
    "ob_age_bars",            # Age of OB at signal time
    "ob_strength_atr",        # OB impulse size in ATR units
    "ob_visit_count",         # 1=fresh, 2=second visit (ADA max)
    "fvg_confluence",         # OB + FVG overlap: 1=yes, 0=no
    "bsl_distance_atr",       # Distance to nearest BSL in ATR
    "ssl_distance_atr",       # Distance to nearest SSL in ATR
    "premium_discount",       # Where price is in range: 0=discount, 1=premium
    "session_london",         # 1 if London session
    "session_ny",             # 1 if NY session
    "atr_ratio",              # Current ATR / 20-period avg ATR
    "funding_rate",           # Funding rate at signal time
    "btc_4h_bias",            # BTC 4H structure (ADA correlation filter)
    "consecutive_bos_count",  # HTF momentum strength
]
```

## XRP-Specific Features (ADA features + these)

```python
XRP_EXTRA_FEATURES = [
    "news_flag",              # XRP news in last 2h: 1=yes, 0=no
    "volume_spike_ratio",     # Current volume / 20-period avg volume
    "xrp_btc_divergence",    # XRP moving opposite to BTC: 1=yes (risky)
]
# XRP model has fewer features than ADA — keep it simpler (less data)
```

## Training Standards

- Walk-forward validation only (no random splits — time dependency)
- Max 15 features per model (prevent overfitting — altcoin data is noisier)
- Minimum out-of-sample AUC: 0.58 (lower threshold for altcoins than BTC)
- Shadow mode first: run predictions without filtering for 4 weeks on Delta
- Compare shadow mode predictions vs actual outcomes before going live

## Deployment Gate (Shadow → Live)

- Shadow mode accuracy > 60% on Delta Exchange live signals
- Would-approve rate between 40–80% (if filtering everything or nothing → problem)
- Manual review of 20 approved vs 20 rejected signals — do they make sense?
- SHAP values reviewed — is the model using sensible features?
