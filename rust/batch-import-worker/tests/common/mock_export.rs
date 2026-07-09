//! A stateful mock of the Mixpanel / Amplitude raw export APIs.
//!
//! Unlike `httpmock`, this server can vary its response *per download attempt* of
//! the same date range, which is how the real APIs behave: Mixpanel's `/export`
//! gives no byte-stability guarantee between calls (event ordering shifts, late
//! data arrives), and that instability is the root cause of the offset-resume
//! failure class this test suite exists to pin down.
//!
//! Every response body is derived deterministically from `(seed, day, attempt)`,
//! so tests can compute exact ground truth via [`MockExport::expected_events`]
//! and remain reproducible run to run.

use std::collections::HashMap;
use std::io::Write;
use std::sync::{Arc, Mutex};

use axum::extract::{Query, State};
use axum::http::{header, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use axum::Router;
use chrono::{NaiveDate, Utc};
use flate2::write::GzEncoder;
use flate2::Compression;
use uuid::Uuid;

/// Mirrors `MIXPANEL_INSERT_ID_NAMESPACE` in `src/parse/content/mixpanel.rs`.
/// Duplicated on purpose: the namespace is a compatibility contract (changing it
/// silently breaks dedup against previously imported events), so the tests must
/// fail if it drifts rather than follow the production constant.
const MIXPANEL_INSERT_ID_NAMESPACE: Uuid = Uuid::from_bytes(*b"posthog_mixpanel");

/// Namespace for the deterministic `uuid` field the mock stamps on generated
/// Amplitude events. Purely test-internal.
const AMPLITUDE_TEST_UUID_NAMESPACE: Uuid = Uuid::from_bytes(*b"amplitude_e2e_ns");

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Provider {
    Mixpanel,
    Amplitude,
}

/// How the mock behaves for downloads of one day. Attempts are 1-indexed.
#[derive(Debug, Clone)]
pub enum Behavior {
    /// Byte-stable: every attempt returns identical bytes.
    Stable,
    /// Each attempt returns the same events in a different (seeded) order.
    /// This is the real Mixpanel behavior behind the incident.
    Reorder,
    /// Attempt N returns the day's events plus `extra_per_attempt * (N - 1)`
    /// additional late-arriving events, in stable order.
    LateData { extra_per_attempt: usize },
    /// The first `failures` attempts return 429 with a Retry-After header,
    /// after which the day downloads normally (byte-stable).
    RateLimit {
        failures: u32,
        retry_after_secs: u64,
    },
    /// Line `line` of the export is overwritten with same-length garbage that
    /// is not valid JSON, on every attempt. Same-length so byte offsets before
    /// and after the corrupt line are identical to the `Stable` body: a job
    /// paused on the corruption can resume byte-aligned once the behavior is
    /// flipped back to `Stable` (the "customer fixed their data" path).
    CorruptLine { line: usize },
    /// The day has no data: 404.
    NotFound,
    /// The day has no data: 200 with a zero-byte body.
    EmptyBody,
    /// Valid gzip header, body cut mid-stream.
    TruncatedGzip,
}

/// Ground truth for one generated event, for exactly-once assertions.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct ExpectedEvent {
    pub uuid: Uuid,
    pub name: String,
    pub distinct_id: String,
}

#[derive(Debug, Clone)]
struct GeneratedEvent {
    insert_id: String,
    name: String,
    user: String,
    time: i64,
    pad_len: usize,
}

struct ServerState {
    provider: Provider,
    seed: u64,
    events_per_day: usize,
    behaviors: Mutex<HashMap<String, Behavior>>,
    attempts: Mutex<HashMap<String, u32>>,
}

pub struct MockExport {
    state: Arc<ServerState>,
    addr: std::net::SocketAddr,
    server: tokio::task::JoinHandle<()>,
}

impl Drop for MockExport {
    fn drop(&mut self) {
        self.server.abort();
    }
}

impl MockExport {
    pub async fn start(provider: Provider, seed: u64, events_per_day: usize) -> Self {
        let state = Arc::new(ServerState {
            provider,
            seed,
            events_per_day,
            behaviors: Mutex::new(HashMap::new()),
            attempts: Mutex::new(HashMap::new()),
        });

        let router = Router::new()
            .route("/export", get(handle_export))
            .with_state(state.clone());

        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            axum::serve(listener, router).await.unwrap();
        });

        Self {
            state,
            addr,
            server,
        }
    }

    pub fn export_url(&self) -> String {
        format!("http://{}/export", self.addr)
    }

    pub fn provider(&self) -> Provider {
        self.state.provider
    }

    /// Program how downloads of `day` (a `%Y-%m-%d` string, matching the
    /// `from_date` query param) behave. Unprogrammed days are `Stable`.
    pub fn set_behavior(&self, day: &str, behavior: Behavior) {
        self.state
            .behaviors
            .lock()
            .unwrap()
            .insert(day.to_string(), behavior);
    }

    /// How many times `day` has been downloaded (attempts, including 429s).
    pub fn download_count(&self, day: &str) -> u32 {
        *self.state.attempts.lock().unwrap().get(day).unwrap_or(&0)
    }

    /// Ground truth for `day`: the events every successful import of that day
    /// must produce, with the UUIDs the production transforms will assign.
    pub fn expected_events(&self, day: &str) -> Vec<ExpectedEvent> {
        day_expected(
            self.state.provider,
            self.state.seed,
            day,
            self.state.events_per_day,
        )
    }

    /// The unique `(user_id, device_id)` pair count for `day`; with identify
    /// generation enabled, an Amplitude import of the day emits exactly one
    /// `$identify` per pair not already seen by the identify cache.
    pub fn expected_identify_pairs(&self, day: &str) -> usize {
        let events = generate_day(self.state.seed, day, self.state.events_per_day);
        let pairs: std::collections::HashSet<_> = events.iter().map(|ev| ev.user.clone()).collect();
        pairs.len()
    }
}

fn expected_for(provider: Provider, ev: &GeneratedEvent) -> ExpectedEvent {
    let uuid = match provider {
        Provider::Mixpanel => Uuid::new_v5(&MIXPANEL_INSERT_ID_NAMESPACE, ev.insert_id.as_bytes()),
        Provider::Amplitude => amplitude_uuid(ev),
    };
    ExpectedEvent {
        uuid,
        name: ev.name.clone(),
        distinct_id: ev.user.clone(),
    }
}

fn amplitude_uuid(ev: &GeneratedEvent) -> Uuid {
    Uuid::new_v5(&AMPLITUDE_TEST_UUID_NAMESPACE, ev.insert_id.as_bytes())
}

// ---- Deterministic generation ----

fn splitmix64(state: &mut u64) -> u64 {
    *state = state.wrapping_add(0x9e3779b97f4a7c15);
    let mut z = *state;
    z = (z ^ (z >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94d049bb133111eb);
    z ^ (z >> 31)
}

fn day_hash(day: &str) -> u64 {
    day.bytes().fold(0xcbf29ce484222325u64, |h, b| {
        (h ^ b as u64).wrapping_mul(0x100000001b3)
    })
}

fn day_epoch(day: &str) -> i64 {
    NaiveDate::parse_from_str(day, "%Y-%m-%d")
        .unwrap_or_else(|_| panic!("mock received unparseable from_date: {day}"))
        .and_hms_opt(0, 0, 0)
        .unwrap()
        .and_utc()
        .timestamp()
}

const EVENT_NAMES: [&str; 3] = ["Page Load", "Button Click", "Purchase"];
const USER_POOL: usize = 7;

fn generate_day(seed: u64, day: &str, count: usize) -> Vec<GeneratedEvent> {
    let mut rng = seed ^ day_hash(day);
    let epoch = day_epoch(day);
    (0..count)
        .map(|i| {
            let r = splitmix64(&mut rng);
            GeneratedEvent {
                insert_id: format!("ins-{day}-{i}"),
                name: EVENT_NAMES[(r % 3) as usize].to_string(),
                user: format!("user-{}", r % USER_POOL as u64),
                time: epoch + i as i64,
                // Variable line lengths guarantee that a reordered stream
                // misaligns any byte offset taken against a previous order.
                pad_len: (r % 240) as usize,
            }
        })
        .collect()
}

/// Extra events representing late-arriving data for `LateData` attempts.
fn generate_late(seed: u64, day: &str, count: usize) -> Vec<GeneratedEvent> {
    let mut rng = seed ^ day_hash(day) ^ 0x1a7e;
    let epoch = day_epoch(day);
    (0..count)
        .map(|i| {
            let r = splitmix64(&mut rng);
            GeneratedEvent {
                insert_id: format!("ins-late-{day}-{i}"),
                name: EVENT_NAMES[(r % 3) as usize].to_string(),
                user: format!("user-{}", r % USER_POOL as u64),
                time: epoch + 80_000 + i as i64,
                pad_len: (r % 240) as usize,
            }
        })
        .collect()
}

/// Seeded Fisher-Yates. `permutation == 0` leaves the order untouched so
/// `Stable` bodies are identical across attempts.
fn permute(events: &mut [GeneratedEvent], seed: u64, permutation: u64) {
    if permutation == 0 {
        return;
    }
    let mut rng = seed ^ permutation.wrapping_mul(0x9e3779b97f4a7c15);
    for i in (1..events.len()).rev() {
        let j = (splitmix64(&mut rng) % (i as u64 + 1)) as usize;
        events.swap(i, j);
    }
}

// ---- Serialization per provider ----

fn mixpanel_line(ev: &GeneratedEvent) -> String {
    serde_json::json!({
        "event": ev.name,
        "properties": {
            "time": ev.time,
            "distinct_id": ev.user,
            "$insert_id": ev.insert_id,
            "pad": "x".repeat(ev.pad_len),
        }
    })
    .to_string()
}

fn amplitude_line(ev: &GeneratedEvent) -> String {
    let event_time = chrono::DateTime::from_timestamp(ev.time, 0)
        .unwrap()
        .format("%Y-%m-%d %H:%M:%S")
        .to_string();
    serde_json::json!({
        "event_type": ev.name,
        "user_id": ev.user,
        "device_id": format!("dev-{}", ev.user),
        "$insert_id": ev.insert_id,
        "uuid": amplitude_uuid(ev).to_string(),
        "event_time": event_time,
        "amplitude_id": 1,
        "event_properties": { "pad": "x".repeat(ev.pad_len) },
    })
    .to_string()
}

fn gzip(data: &[u8]) -> Vec<u8> {
    let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
    encoder.write_all(data).unwrap();
    encoder.finish().unwrap()
}

/// Amplitude exports are a zip of `.json.gz` members; split the day across two
/// members to exercise member ordering and concatenation.
fn amplitude_zip(lines: &[String]) -> Vec<u8> {
    let mut zip = zip::ZipWriter::new(std::io::Cursor::new(Vec::new()));
    let options = zip::write::SimpleFileOptions::default();
    let mid = lines.len().div_ceil(2);
    for (name, chunk) in [
        ("000.json.gz", &lines[..mid]),
        ("001.json.gz", &lines[mid..]),
    ] {
        zip.start_file(name, options).unwrap();
        zip.write_all(&gzip(chunk.join("\n").as_bytes())).unwrap();
    }
    zip.finish().unwrap().into_inner()
}

/// One day's export body exactly as the mock serves it, for tests that stage
/// data somewhere other than this HTTP server (e.g. objects in a bucket for the
/// S3 source). `permutation` 0 is the canonical order.
pub fn day_body(
    provider: Provider,
    seed: u64,
    day: &str,
    events_per_day: usize,
    permutation: u64,
    late_events: usize,
) -> Vec<u8> {
    day_body_inner(
        provider,
        seed,
        day,
        events_per_day,
        permutation,
        late_events,
        None,
    )
}

fn day_body_inner(
    provider: Provider,
    seed: u64,
    day: &str,
    events_per_day: usize,
    permutation: u64,
    late_events: usize,
    corrupt_line: Option<usize>,
) -> Vec<u8> {
    let mut events = generate_day(seed, day, events_per_day);
    events.extend(generate_late(seed, day, late_events));
    permute(&mut events, seed ^ day_hash(day), permutation);

    let mut lines: Vec<String> = match provider {
        Provider::Mixpanel => events.iter().map(mixpanel_line).collect(),
        Provider::Amplitude => events.iter().map(amplitude_line).collect(),
    };
    if let Some(line) = corrupt_line {
        // Same-length garbage keeps every other line's byte offset identical
        // to the Stable body (see Behavior::CorruptLine).
        lines[line] = "x".repeat(lines[line].len());
    }

    match provider {
        Provider::Mixpanel => gzip(lines.join("\n").as_bytes()),
        Provider::Amplitude => amplitude_zip(&lines),
    }
}

/// Ground truth matching [`day_body`], usable without a running mock server.
pub fn day_expected(
    provider: Provider,
    seed: u64,
    day: &str,
    events_per_day: usize,
) -> Vec<ExpectedEvent> {
    generate_day(seed, day, events_per_day)
        .iter()
        .map(|ev| expected_for(provider, ev))
        .collect()
}

fn body_for(state: &ServerState, day: &str, permutation: u64, late_events: usize) -> Vec<u8> {
    day_body_inner(
        state.provider,
        state.seed,
        day,
        state.events_per_day,
        permutation,
        late_events,
        None,
    )
}

async fn handle_export(
    State(state): State<Arc<ServerState>>,
    Query(params): Query<HashMap<String, String>>,
) -> Response {
    let Some(day) = params.get("from_date").cloned() else {
        return (StatusCode::BAD_REQUEST, "missing from_date").into_response();
    };

    let attempt = {
        let mut attempts = state.attempts.lock().unwrap();
        let entry = attempts.entry(day.clone()).or_insert(0);
        *entry += 1;
        *entry
    };

    let behavior = state
        .behaviors
        .lock()
        .unwrap()
        .get(&day)
        .cloned()
        .unwrap_or(Behavior::Stable);

    let body = match behavior {
        Behavior::Stable => body_for(&state, &day, 0, 0),
        Behavior::Reorder => body_for(&state, &day, attempt as u64, 0),
        Behavior::LateData { extra_per_attempt } => {
            body_for(&state, &day, 0, extra_per_attempt * (attempt as usize - 1))
        }
        Behavior::RateLimit {
            failures,
            retry_after_secs,
        } => {
            if attempt <= failures {
                return (
                    StatusCode::TOO_MANY_REQUESTS,
                    [(header::RETRY_AFTER, retry_after_secs.to_string())],
                    "rate limited",
                )
                    .into_response();
            }
            body_for(&state, &day, 0, 0)
        }
        Behavior::CorruptLine { line } => day_body_inner(
            state.provider,
            state.seed,
            &day,
            state.events_per_day,
            0,
            0,
            Some(line),
        ),
        Behavior::NotFound => return StatusCode::NOT_FOUND.into_response(),
        Behavior::EmptyBody => Vec::new(),
        Behavior::TruncatedGzip => {
            let mut body = body_for(&state, &day, 0, 0);
            body.truncate(body.len() / 2);
            body
        }
    };

    // The `now` timestamp keeps generated timestamps in the past for Amplitude's
    // future-timestamp fallback logic; assert rather than let it drift silently.
    debug_assert!(day_epoch(&day) < Utc::now().timestamp());

    ([(header::CONTENT_TYPE, "application/octet-stream")], body).into_response()
}
