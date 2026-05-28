//! Per-cohort kill switch (TDD decision D14).
//!
//! Lets operators disable specific cohorts without a redeploy; a disabled cohort is
//! treated as `false` at flag-eval and produces no output. Planned submodules (TDD §3):
//! - `env_flag`     — `COHORT_STREAM_PROCESSOR_DISABLED_COHORTS` env var (Phase 1–4)
//! - `feature_flag` — `behavioral-cohorts-disable-list` flag JSON payload (Phase 5+)
