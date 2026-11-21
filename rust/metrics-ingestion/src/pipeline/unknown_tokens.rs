use std::collections::{BTreeMap, HashMap};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use logs_ingestion::js::number_to_string;
use logs_ingestion::rate_limiter::Clock;
use redis::aio::ConnectionLike;

pub const UNKNOWN_TOKENS_KEY: &str = "capture_logs:unknown_tokens";
/// Past the team lookup's 2.5 minute negative cache, so the miss that triggers a write came from a fresh lookup.
pub const UNKNOWN_TOKEN_CONFIRM_MS: f64 = 3.0 * 60.0 * 1000.0;
pub const UNKNOWN_TOKEN_WRITE_DEBOUNCE_MS: f64 = 30_000.0;
pub const UNKNOWN_TOKEN_IDLE_MS: f64 = 10.0 * 60.0 * 1000.0;
pub const UNKNOWN_TOKEN_RETENTION_MS: f64 = 60.0 * 60.0 * 1000.0;
pub const UNKNOWN_TOKENS_MAX_ENTRIES: usize = 100_000;
pub const UNKNOWN_TOKEN_MAX_IN_FLIGHT_WRITES: usize = 20;
const WRITE_DEADLINE: Duration = Duration::from_millis(1000);
const MAX_TOKEN_LENGTH: usize = 200;
const KEY_TTL_SECONDS: u64 = 2 * 60 * 60;
pub const WRITE_COUNTER: &str = "logs_ingestion_unknown_token_write_total";

/// Called only for a lookup that found no team. A failed lookup says nothing about the token.
pub trait UnknownTokens: Send + Sync {
    fn record(&self, token: &str);
}

struct TokenState {
    first_miss_at: f64,
    last_miss_at: f64,
    written_at: Option<f64>,
    order: u64,
}

/// Tokens in order of last miss, so idle entries are always at the front.
#[derive(Default)]
struct Tokens {
    states: HashMap<String, TokenState>,
    by_order: BTreeMap<u64, String>,
    next_order: u64,
}

pub struct UnknownTokenRecorder<C> {
    tokens: Mutex<Tokens>,
    in_flight: Arc<AtomicUsize>,
    redis: C,
    clock: Clock,
}

fn count(outcome: &'static str) {
    metrics::counter!(WRITE_COUNTER, "outcome" => outcome).increment(1);
}

impl<C> UnknownTokenRecorder<C>
where
    C: ConnectionLike + Clone + Send + Sync + 'static,
{
    pub fn new(redis: C, clock: Clock) -> Self {
        metrics::describe_counter!(
            WRITE_COUNTER,
            "Unknown project tokens written to the shared set that capture-logs reads, by outcome."
        );
        Self {
            tokens: Mutex::new(Tokens::default()),
            in_flight: Arc::new(AtomicUsize::new(0)),
            redis,
            clock,
        }
    }

    pub fn in_flight_writes(&self) -> usize {
        self.in_flight.load(Ordering::SeqCst)
    }

    fn write(&self, token: &str, now: f64) {
        let mut redis = self.redis.clone();
        let in_flight = self.in_flight.clone();
        in_flight.fetch_add(1, Ordering::SeqCst);
        let mut pipe = redis::pipe();
        pipe.cmd("ZADD")
            .arg(UNKNOWN_TOKENS_KEY)
            .arg(number_to_string(now))
            .arg(token)
            .cmd("EXPIRE")
            .arg(UNKNOWN_TOKENS_KEY)
            .arg(KEY_TTL_SECONDS)
            // Both trims cost O(log N) when nothing is removed, so every write keeps the set within its cap.
            .cmd("ZREMRANGEBYSCORE")
            .arg(UNKNOWN_TOKENS_KEY)
            .arg("-inf")
            .arg(number_to_string(now - UNKNOWN_TOKEN_RETENTION_MS))
            .cmd("ZREMRANGEBYRANK")
            .arg(UNKNOWN_TOKENS_KEY)
            .arg(0)
            .arg(-(UNKNOWN_TOKENS_MAX_ENTRIES as i64 + 1));
        tokio::spawn(async move {
            let written =
                tokio::time::timeout(WRITE_DEADLINE, pipe.query_async::<redis::Value>(&mut redis))
                    .await;
            match written {
                Ok(Ok(_)) => count("written"),
                Ok(Err(error)) => {
                    count("error");
                    tracing::warn!(error = %error, "unknown_token_record_failed");
                }
                Err(_) => {
                    count("error");
                    tracing::warn!("unknown_token_record_failed: deadline");
                }
            }
            in_flight.fetch_sub(1, Ordering::SeqCst);
        });
    }
}

impl<C> UnknownTokens for UnknownTokenRecorder<C>
where
    C: ConnectionLike + Clone + Send + Sync + 'static,
{
    fn record(&self, token: &str) {
        if token.is_empty() || token.encode_utf16().count() > MAX_TOKEN_LENGTH {
            return;
        }
        let now = (self.clock)();
        let mut guard = self.tokens.lock().unwrap();
        let tokens = &mut *guard;
        while let Some((&order, oldest)) = tokens.by_order.first_key_value() {
            if now - tokens.states[oldest].last_miss_at < UNKNOWN_TOKEN_IDLE_MS {
                break;
            }
            let oldest = tokens.by_order.remove(&order).expect("present");
            tokens.states.remove(&oldest);
        }
        if !tokens.states.contains_key(token) && tokens.states.len() >= UNKNOWN_TOKENS_MAX_ENTRIES {
            count("dropped_full");
            return;
        }
        let order = tokens.next_order;
        tokens.next_order += 1;
        let state = tokens
            .states
            .entry(token.to_string())
            .or_insert(TokenState {
                first_miss_at: now,
                last_miss_at: now,
                written_at: None,
                order,
            });
        tokens.by_order.remove(&state.order);
        state.order = order;
        state.last_miss_at = now;
        tokens.by_order.insert(order, token.to_string());

        if now - state.first_miss_at < UNKNOWN_TOKEN_CONFIRM_MS {
            count("unconfirmed");
            return;
        }
        if state
            .written_at
            .is_some_and(|at| now - at < UNKNOWN_TOKEN_WRITE_DEBOUNCE_MS)
        {
            count("debounced");
            return;
        }
        if self.in_flight.load(Ordering::SeqCst) >= UNKNOWN_TOKEN_MAX_IN_FLIGHT_WRITES {
            count("dropped_busy");
            return;
        }
        // Set before the write starts, so concurrent misses for one token share a single write.
        state.written_at = Some(now);
        drop(guard);
        self.write(token, now);
    }
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::AtomicU64;

    use futures::FutureExt;
    use redis::{Cmd, Pipeline, RedisFuture, Value};

    use super::*;

    #[derive(Clone, Copy, PartialEq)]
    enum Mode {
        Answers,
        Fails,
        Hangs,
    }

    #[derive(Clone)]
    struct FakeRedis {
        mode: Mode,
        pipelines: Arc<Mutex<Vec<Vec<Vec<String>>>>>,
    }

    impl ConnectionLike for FakeRedis {
        fn req_packed_command<'a>(&'a mut self, _cmd: &'a Cmd) -> RedisFuture<'a, Value> {
            unreachable!("the recorder writes pipelines only")
        }

        fn req_packed_commands<'a>(
            &'a mut self,
            pipe: &'a Pipeline,
            _offset: usize,
            count: usize,
        ) -> RedisFuture<'a, Vec<Value>> {
            let calls = pipe
                .cmd_iter()
                .map(|cmd| {
                    cmd.args_iter()
                        .map(|arg| match arg {
                            redis::Arg::Simple(bytes) => {
                                String::from_utf8_lossy(bytes).into_owned()
                            }
                            redis::Arg::Cursor => String::new(),
                        })
                        .collect()
                })
                .collect();
            self.pipelines.lock().unwrap().push(calls);
            let mode = self.mode;
            async move {
                match mode {
                    Mode::Answers => Ok(vec![Value::Int(1); count]),
                    Mode::Fails => Err(redis::RedisError::from((
                        redis::ErrorKind::IoError,
                        "redis down",
                    ))),
                    Mode::Hangs => futures::future::pending().await,
                }
            }
            .boxed()
        }

        fn get_db(&self) -> i64 {
            0
        }
    }

    struct Setup {
        recorder: UnknownTokenRecorder<FakeRedis>,
        pipelines: Arc<Mutex<Vec<Vec<Vec<String>>>>>,
        now: Arc<AtomicU64>,
    }

    impl Setup {
        fn new(mode: Mode) -> Self {
            let pipelines = Arc::new(Mutex::new(Vec::new()));
            let now = Arc::new(AtomicU64::new(1_000_000_000_000));
            let clock_now = now.clone();
            let recorder = UnknownTokenRecorder::new(
                FakeRedis {
                    mode,
                    pipelines: pipelines.clone(),
                },
                Arc::new(move || clock_now.load(Ordering::SeqCst) as f64),
            );
            Self {
                recorder,
                pipelines,
                now,
            }
        }

        fn advance(&self, ms: f64) {
            self.now.fetch_add(ms as u64, Ordering::SeqCst);
        }

        async fn writes(&self) -> usize {
            tokio::time::sleep(Duration::from_millis(5)).await;
            self.pipelines.lock().unwrap().len()
        }
    }

    #[tokio::test]
    async fn writes_a_token_once_it_keeps_missing_past_the_confirmation_window() {
        let setup = Setup::new(Mode::Answers);
        setup.recorder.record("token-unknown");
        setup.advance(UNKNOWN_TOKEN_CONFIRM_MS);
        setup.recorder.record("token-unknown");
        assert_eq!(setup.writes().await, 1);
        let now = setup.now.load(Ordering::SeqCst);
        let calls: Vec<Vec<String>> = [
            vec![
                "ZADD",
                UNKNOWN_TOKENS_KEY,
                &now.to_string(),
                "token-unknown",
            ],
            vec!["EXPIRE", UNKNOWN_TOKENS_KEY, "7200"],
            vec![
                "ZREMRANGEBYSCORE",
                UNKNOWN_TOKENS_KEY,
                "-inf",
                &(now - UNKNOWN_TOKEN_RETENTION_MS as u64).to_string(),
            ],
            vec!["ZREMRANGEBYRANK", UNKNOWN_TOKENS_KEY, "0", "-100001"],
        ]
        .into_iter()
        .map(|call| call.into_iter().map(String::from).collect())
        .collect();
        assert_eq!(setup.pipelines.lock().unwrap()[0], calls);
    }

    #[tokio::test]
    async fn writes_only_confirmed_tokens_and_once_per_debounce_window() {
        let setup = Setup::new(Mode::Answers);
        setup.recorder.record("token-new-project");
        setup.advance(UNKNOWN_TOKEN_CONFIRM_MS - 1.0);
        setup.recorder.record("token-new-project");
        assert_eq!(setup.writes().await, 0);

        setup.recorder.record("token-a");
        setup.recorder.record("token-b");
        setup.advance(UNKNOWN_TOKEN_CONFIRM_MS);
        for _ in 0..1000 {
            setup.recorder.record("token-a");
        }
        setup.recorder.record("token-b");
        assert_eq!(setup.writes().await, 2);

        setup.advance(UNKNOWN_TOKEN_WRITE_DEBOUNCE_MS);
        setup.recorder.record("token-a");
        assert_eq!(setup.writes().await, 3);
    }

    #[tokio::test]
    async fn turns_away_new_tokens_while_full_and_takes_them_again_once_old_ones_go_idle() {
        let setup = Setup::new(Mode::Answers);
        for i in 0..UNKNOWN_TOKENS_MAX_ENTRIES {
            setup.recorder.record(&format!("token-flood-{i}"));
        }
        setup.recorder.record("token-late");
        setup.advance(UNKNOWN_TOKEN_CONFIRM_MS);
        setup.recorder.record("token-late");
        assert_eq!(setup.writes().await, 0);

        setup.advance(UNKNOWN_TOKEN_IDLE_MS);
        setup.recorder.record("token-late");
        setup.advance(UNKNOWN_TOKEN_CONFIRM_MS);
        setup.recorder.record("token-late");
        assert_eq!(setup.writes().await, 1);
    }

    #[tokio::test]
    async fn stops_starting_writes_while_redis_is_not_answering() {
        let setup = Setup::new(Mode::Hangs);
        let tokens: Vec<String> = (0..UNKNOWN_TOKEN_MAX_IN_FLIGHT_WRITES + 5)
            .map(|i| format!("token-{i}"))
            .collect();
        tokens.iter().for_each(|t| setup.recorder.record(t));
        setup.advance(UNKNOWN_TOKEN_CONFIRM_MS);
        tokens.iter().for_each(|t| setup.recorder.record(t));
        assert_eq!(setup.writes().await, UNKNOWN_TOKEN_MAX_IN_FLIGHT_WRITES);
    }

    #[tokio::test]
    async fn ignores_empty_and_over_long_tokens_and_survives_a_failed_write() {
        let setup = Setup::new(Mode::Fails);
        for token in [String::new(), "x".repeat(201), "token-unknown".to_string()] {
            setup.recorder.record(&token);
            setup.advance(UNKNOWN_TOKEN_CONFIRM_MS);
            setup.recorder.record(&token);
        }
        assert_eq!(setup.writes().await, 1);
        assert_eq!(setup.recorder.in_flight_writes(), 0);
    }
}
