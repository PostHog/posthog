//! `logs/services/unknown-token-recorder.ts`. capture-logs reads the set to turn away tokens that belong to no team.
//!
//! Public so that other ingestion ports that write the same set, such as the metrics consumer, share one implementation.

use std::collections::{BTreeMap, HashMap};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use redis::aio::ConnectionLike;

use crate::js::number_to_string;
use crate::rate_limiter::Clock;

/// Sorted set of project tokens that resolved to no team, scored by the last time one was seen (epoch ms).
pub const UNKNOWN_TOKENS_KEY: &str = "capture_logs:unknown_tokens";
/// Past the team lookup's 2.5 minute negative cache, so the miss that triggers a write came from a fresh lookup
/// and a project created a moment ago is never turned away.
pub const UNKNOWN_TOKEN_CONFIRM_MS: f64 = 3.0 * 60.0 * 1000.0;
/// A confirmed token is written at most this often per process.
pub const UNKNOWN_TOKEN_WRITE_DEBOUNCE_MS: f64 = 30_000.0;
/// A token not missed for this long is forgotten, and its confirmation starts over.
pub const UNKNOWN_TOKEN_IDLE_MS: f64 = 10.0 * 60.0 * 1000.0;
/// capture-logs only reads the last hour, so older entries are trimmed.
pub const UNKNOWN_TOKEN_RETENTION_MS: f64 = 60.0 * 60.0 * 1000.0;
/// Tokens are client input, so a flood of unique ones must not grow the set or this process without bound.
pub const UNKNOWN_TOKENS_MAX_ENTRIES: usize = 100_000;
/// A Redis that stops answering must not pile up pending writes.
pub const UNKNOWN_TOKEN_MAX_IN_FLIGHT_WRITES: usize = 20;
/// Node bounds only the pool acquire with this deadline. Rust bounds the whole write.
const WRITE_DEADLINE: Duration = Duration::from_millis(1000);
/// In UTF-16 code units, as Node's `token.length`.
const MAX_TOKEN_LENGTH: usize = 200;
const KEY_TTL_SECONDS: u64 = 2 * 60 * 60;
pub const UNKNOWN_TOKEN_WRITE_COUNTER: &str = "logs_ingestion_unknown_token_write_total";

/// Called only for a lookup that found no team. A failed lookup says nothing about the token, and recording it
/// would let a database blip turn a real token away at the edge.
pub trait UnknownTokens: Send + Sync {
    fn record(&self, token: &str);
}

struct TokenState {
    first_miss_at: f64,
    last_miss_at: f64,
    written_at: Option<f64>,
    order: u64,
}

/// Node keeps a `Map` in order of last miss. `by_order` gives the same order, so idle entries are always at the front.
#[derive(Default)]
struct Tokens {
    states: HashMap<String, TokenState>,
    by_order: BTreeMap<u64, String>,
    next_order: u64,
}

/// Writes are spawned and swallow errors, so Redis can never fail or slow a batch. `record` must run inside a Tokio runtime.
pub struct UnknownTokenRecorder<C> {
    tokens: Mutex<Tokens>,
    in_flight: Arc<AtomicUsize>,
    redis: C,
    clock: Clock,
    key: &'static str,
}

fn count(outcome: &'static str) {
    metrics::counter!(UNKNOWN_TOKEN_WRITE_COUNTER, "outcome" => outcome).increment(1);
}

/// Why `record` started no write, or `Write` when it did.
#[derive(Debug, Clone, Copy, PartialEq)]
enum Admission {
    Ignored,
    DroppedFull,
    Unconfirmed,
    Debounced,
    DroppedBusy,
    Write(f64),
}

impl<C> UnknownTokenRecorder<C>
where
    C: ConnectionLike + Clone + Send + Sync + 'static,
{
    pub fn new(redis: C, clock: Clock) -> Self {
        Self::with_key(redis, clock, UNKNOWN_TOKENS_KEY)
    }

    /// Tests point the recorder at their own key, so they never touch the set capture-logs reads.
    pub fn with_key(redis: C, clock: Clock, key: &'static str) -> Self {
        metrics::describe_counter!(
            UNKNOWN_TOKEN_WRITE_COUNTER,
            "Unknown project tokens written to the shared set that capture-logs reads, by outcome."
        );
        Self {
            tokens: Mutex::new(Tokens::default()),
            in_flight: Arc::new(AtomicUsize::new(0)),
            redis,
            clock,
            key,
        }
    }

    pub fn in_flight_writes(&self) -> usize {
        self.in_flight.load(Ordering::SeqCst)
    }

    fn admit(&self, token: &str) -> Admission {
        // Only a token over 200 bytes can be over 200 UTF-16 units, so the count runs only for those.
        if token.is_empty()
            || (token.len() > MAX_TOKEN_LENGTH && token.encode_utf16().count() > MAX_TOKEN_LENGTH)
        {
            return Admission::Ignored;
        }
        let now = (self.clock)();
        let mut guard = self.tokens.lock().unwrap_or_else(|e| e.into_inner());
        let tokens = &mut *guard;
        while let Some((&order, oldest)) = tokens.by_order.first_key_value() {
            if now - tokens.states[oldest].last_miss_at < UNKNOWN_TOKEN_IDLE_MS {
                break;
            }
            if let Some(oldest) = tokens.by_order.remove(&order) {
                tokens.states.remove(&oldest);
            }
        }
        if !tokens.states.contains_key(token) && tokens.states.len() >= UNKNOWN_TOKENS_MAX_ENTRIES {
            return Admission::DroppedFull;
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
        // Moving the token to the back keeps the order of last miss.
        tokens.by_order.remove(&state.order);
        state.order = order;
        state.last_miss_at = now;
        tokens.by_order.insert(order, token.to_string());

        if now - state.first_miss_at < UNKNOWN_TOKEN_CONFIRM_MS {
            return Admission::Unconfirmed;
        }
        if state
            .written_at
            .is_some_and(|at| now - at < UNKNOWN_TOKEN_WRITE_DEBOUNCE_MS)
        {
            return Admission::Debounced;
        }
        if self.in_flight.load(Ordering::SeqCst) >= UNKNOWN_TOKEN_MAX_IN_FLIGHT_WRITES {
            return Admission::DroppedBusy;
        }
        // Set before the write starts, so concurrent misses for one token share a single write.
        state.written_at = Some(now);
        // Taken under the lock, so concurrent callers cannot pass the cap together.
        self.in_flight.fetch_add(1, Ordering::SeqCst);
        Admission::Write(now)
    }

    fn write(&self, token: &str, now: f64) {
        let mut redis = self.redis.clone();
        let in_flight = self.in_flight.clone();
        let key = self.key;
        let mut pipe = redis::pipe();
        pipe.cmd("ZADD")
            .arg(key)
            .arg(number_to_string(now))
            .arg(token)
            .cmd("EXPIRE")
            .arg(key)
            .arg(KEY_TTL_SECONDS)
            // Both trims cost O(log N) when nothing is removed, so every write keeps the set within its cap.
            .cmd("ZREMRANGEBYSCORE")
            .arg(key)
            .arg("-inf")
            .arg(number_to_string(now - UNKNOWN_TOKEN_RETENTION_MS))
            .cmd("ZREMRANGEBYRANK")
            .arg(key)
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
                    tracing::warn!(error = "deadline exceeded", "unknown_token_record_failed");
                }
            }
            in_flight.fetch_sub(1, Ordering::SeqCst);
        });
    }
}

impl<C> UnknownTokenRecorder<C>
where
    C: ConnectionLike + Clone + Send + Sync + 'static,
{
    fn record_admission(&self, token: &str) -> Admission {
        let admission = self.admit(token);
        match admission {
            Admission::Ignored => {}
            Admission::DroppedFull => count("dropped_full"),
            Admission::Unconfirmed => count("unconfirmed"),
            Admission::Debounced => count("debounced"),
            Admission::DroppedBusy => count("dropped_busy"),
            Admission::Write(now) => self.write(token, now),
        }
        admission
    }
}

impl<C> UnknownTokens for UnknownTokenRecorder<C>
where
    C: ConnectionLike + Clone + Send + Sync + 'static,
{
    fn record(&self, token: &str) {
        self.record_admission(token);
    }
}

#[cfg(test)]
mod tests {
    //! The cases of `unknown-token-recorder.test.ts`, in its order.

    use std::sync::atomic::AtomicU64;

    use futures::FutureExt;
    use redis::{Cmd, Pipeline, RedisFuture, Value};

    use super::*;

    /// Node's `fail` option. Node's `null` result (the pool gave up) has no redis-rs form; the closest is the deadline.
    #[derive(Clone, Copy, PartialEq)]
    enum Mode {
        Answers,
        Throws,
        CommandFails,
        Hangs,
    }

    type Pipelines = Arc<Mutex<Vec<Vec<Vec<String>>>>>;

    #[derive(Clone)]
    struct FakeRedis {
        mode: Mode,
        pipelines: Pipelines,
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
                    Mode::Throws => Err(redis::RedisError::from((
                        redis::ErrorKind::IoError,
                        "redis down",
                    ))),
                    // redis-rs turns an error reply inside a pipeline into a `ResponseError`.
                    Mode::CommandFails => Err(redis::RedisError::from((
                        redis::ErrorKind::ResponseError,
                        "boom",
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
        pipelines: Pipelines,
        now: Arc<AtomicU64>,
    }

    impl Setup {
        fn new(mode: Mode) -> Self {
            let pipelines = Pipelines::default();
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

        fn now(&self) -> u64 {
            self.now.load(Ordering::SeqCst)
        }

        fn record(&self, token: &str) {
            self.recorder.record(token);
        }

        /// Lets the spawned writes run, as Node's `flush`.
        async fn writes(&self) -> usize {
            for _ in 0..10 {
                tokio::task::yield_now().await;
            }
            self.pipelines.lock().unwrap().len()
        }
    }

    #[tokio::test]
    async fn writes_a_token_once_it_keeps_missing_past_the_confirmation_window_trimming_the_set_each_time(
    ) {
        let setup = Setup::new(Mode::Answers);
        setup.record("token-unknown");
        setup.advance(UNKNOWN_TOKEN_CONFIRM_MS);
        setup.record("token-unknown");
        assert_eq!(setup.writes().await, 1);
        let now = setup.now();
        let expected: Vec<Vec<String>> = [
            vec![
                "ZADD".to_string(),
                UNKNOWN_TOKENS_KEY.to_string(),
                now.to_string(),
                "token-unknown".to_string(),
            ],
            vec![
                "EXPIRE".to_string(),
                UNKNOWN_TOKENS_KEY.to_string(),
                "7200".to_string(),
            ],
            vec![
                "ZREMRANGEBYSCORE".to_string(),
                UNKNOWN_TOKENS_KEY.to_string(),
                "-inf".to_string(),
                (now - UNKNOWN_TOKEN_RETENTION_MS as u64).to_string(),
            ],
            vec![
                "ZREMRANGEBYRANK".to_string(),
                UNKNOWN_TOKENS_KEY.to_string(),
                "0".to_string(),
                "-100001".to_string(),
            ],
        ]
        .into();
        assert_eq!(*setup.pipelines.lock().unwrap(), vec![expected]);
    }

    #[tokio::test]
    async fn never_writes_a_token_whose_misses_all_fall_inside_the_confirmation_window() {
        let setup = Setup::new(Mode::Answers);
        setup.record("token-new-project");
        setup.advance(UNKNOWN_TOKEN_CONFIRM_MS - 1.0);
        assert_eq!(
            setup.recorder.record_admission("token-new-project"),
            Admission::Unconfirmed
        );
        assert_eq!(setup.writes().await, 0);
    }

    #[tokio::test]
    async fn writes_a_steady_stream_of_misses_for_one_token_once_per_debounce_window() {
        let setup = Setup::new(Mode::Answers);
        setup.record("token-unknown");
        setup.advance(UNKNOWN_TOKEN_CONFIRM_MS);
        setup.record("token-unknown");
        for _ in 0..999 {
            assert_eq!(
                setup.recorder.record_admission("token-unknown"),
                Admission::Debounced
            );
        }
        assert_eq!(setup.writes().await, 1);

        setup.advance(UNKNOWN_TOKEN_WRITE_DEBOUNCE_MS);
        setup.record("token-unknown");
        assert_eq!(setup.writes().await, 2);
    }

    #[tokio::test]
    async fn writes_each_distinct_token() {
        let setup = Setup::new(Mode::Answers);
        setup.record("token-a");
        setup.record("token-b");
        setup.advance(UNKNOWN_TOKEN_CONFIRM_MS);
        setup.record("token-a");
        setup.record("token-b");
        assert_eq!(setup.writes().await, 2);
    }

    #[tokio::test]
    async fn turns_away_new_tokens_while_full_and_takes_them_again_once_old_ones_go_idle() {
        let setup = Setup::new(Mode::Answers);
        for i in 0..UNKNOWN_TOKENS_MAX_ENTRIES {
            setup.record(&format!("token-flood-{i}"));
        }
        assert_eq!(
            setup.recorder.record_admission("token-late"),
            Admission::DroppedFull
        );
        setup.advance(UNKNOWN_TOKEN_CONFIRM_MS);
        assert_eq!(
            setup.recorder.record_admission("token-late"),
            Admission::DroppedFull
        );
        assert_eq!(setup.writes().await, 0);

        setup.advance(UNKNOWN_TOKEN_IDLE_MS);
        setup.record("token-late");
        setup.advance(UNKNOWN_TOKEN_CONFIRM_MS);
        setup.record("token-late");
        assert_eq!(setup.writes().await, 1);
    }

    #[tokio::test]
    async fn stops_starting_writes_while_redis_is_not_answering() {
        let setup = Setup::new(Mode::Hangs);
        let tokens: Vec<String> = (0..UNKNOWN_TOKEN_MAX_IN_FLIGHT_WRITES + 5)
            .map(|i| format!("token-{i}"))
            .collect();
        tokens.iter().for_each(|t| setup.record(t));
        setup.advance(UNKNOWN_TOKEN_CONFIRM_MS);
        let admissions: Vec<Admission> = tokens
            .iter()
            .map(|t| setup.recorder.record_admission(t))
            .collect();
        assert_eq!(
            admissions
                .iter()
                .filter(|a| **a == Admission::DroppedBusy)
                .count(),
            5
        );
        assert_eq!(setup.writes().await, UNKNOWN_TOKEN_MAX_IN_FLIGHT_WRITES);
        assert_eq!(
            setup.recorder.in_flight_writes(),
            UNKNOWN_TOKEN_MAX_IN_FLIGHT_WRITES
        );
    }

    #[tokio::test]
    async fn ignores_an_empty_or_over_long_token() {
        let setup = Setup::new(Mode::Answers);
        // 201 UTF-16 units. 100 two-unit characters and one more are 201 units, so the cap counts units, not chars.
        let astral = format!("{}x", "\u{1F600}".repeat(100));
        for token in [String::new(), "x".repeat(201), astral] {
            assert_eq!(setup.recorder.record_admission(&token), Admission::Ignored);
            setup.advance(UNKNOWN_TOKEN_CONFIRM_MS);
            assert_eq!(setup.recorder.record_admission(&token), Admission::Ignored);
        }
        assert_eq!(setup.writes().await, 0);

        setup.record(&"x".repeat(200));
        setup.advance(UNKNOWN_TOKEN_CONFIRM_MS);
        setup.record(&"x".repeat(200));
        assert_eq!(setup.writes().await, 1);
    }

    async fn survives_a_failed_write(mode: Mode) {
        let setup = Setup::new(mode);
        setup.record("token-unknown");
        setup.advance(UNKNOWN_TOKEN_CONFIRM_MS);
        setup.record("token-unknown");
        assert_eq!(setup.writes().await, 1);
        assert_eq!(setup.recorder.in_flight_writes(), 0);
    }

    #[tokio::test]
    async fn never_throws_when_the_write_fails_throw() {
        survives_a_failed_write(Mode::Throws).await;
    }

    #[tokio::test]
    async fn never_throws_when_the_write_fails_command() {
        survives_a_failed_write(Mode::CommandFails).await;
    }

    /// Node's `null` case. A write that never answers is given up at the deadline and frees its slot.
    #[tokio::test(start_paused = true)]
    async fn never_throws_when_the_write_fails_deadline() {
        let setup = Setup::new(Mode::Hangs);
        setup.record("token-unknown");
        setup.advance(UNKNOWN_TOKEN_CONFIRM_MS);
        setup.record("token-unknown");
        assert_eq!(setup.writes().await, 1);
        assert_eq!(setup.recorder.in_flight_writes(), 1);
        tokio::time::sleep(WRITE_DEADLINE + Duration::from_millis(1)).await;
        tokio::task::yield_now().await;
        assert_eq!(setup.recorder.in_flight_writes(), 0);
    }
}
