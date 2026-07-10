//! In-process harness driving the real batch-import pipeline: a genuine
//! `DateRangeExportSource` (with the production extractor for the provider)
//! pointed at the [`mock_export`](super::mock_export) server, the production
//! JSONL parser and per-provider transform, and the DB-free job fetch loop
//! (`select_and_fetch_next_chunk`).
//!
//! Commits are modeled by the shared `JobState`: the loop advances part offsets
//! in place, exactly as a successfully committed chunk would persist them.
//! [`Harness::restart`] simulates a pod replacement: the source (and with it
//! every prepared key, streaming reader, and staged `.raw` file) is dropped and
//! rebuilt, while the persisted `JobState` survives - the same shape as a
//! deploy landing mid-part in production.

use std::collections::HashMap;
use std::sync::Arc;

use anyhow::Error;
use batch_import_worker::cache::{MockGroupCache, MockIdentifyCache};
use batch_import_worker::extractor::ExtractorType;
use batch_import_worker::job::config::{JobConfig, JobSecrets};
use batch_import_worker::job::model::{JobModel, JobState, JobStatus, PartState};
use batch_import_worker::job::select_and_fetch_next_chunk;
use batch_import_worker::parse::content::amplitude::AmplitudeEvent;
use batch_import_worker::parse::content::mixpanel::MixpanelEvent;
use batch_import_worker::parse::content::TransformContext;
use batch_import_worker::parse::format::{json_nd, skip_geoip, ParserFn};
use batch_import_worker::parse::Parsed;
use batch_import_worker::source::date_range_export::{AuthConfig, DateRangeExportSource};
use batch_import_worker::source::DataSource;
use chrono::{DateTime, TimeZone, Utc};
use common_types::InternallyCapturedEvent;
use rayon::iter::{IntoParallelIterator, ParallelIterator};
use tempfile::TempDir;
use tokio::sync::Mutex;
use uuid::Uuid;

use super::mock_export::{MockExport, Provider};

pub const TEAM_ID: i32 = 42;
pub const TOKEN: &str = "e2e-test-token";

pub struct Harness {
    pub mock: MockExport,
    provider: Provider,
    chunk_size: usize,
    job_id: Uuid,
    staging: TempDir,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
    state: Mutex<JobState>,
    model: Mutex<JobModel>,
    parser: Arc<ParserFn>,
    source: DateRangeExportSource,
    pub emitted: Vec<InternallyCapturedEvent>,
}

/// Outcome of driving the fetch loop.
#[derive(Debug)]
pub enum RunOutcome {
    /// Every part is done.
    Complete,
    /// The requested number of chunks was fetched with work still remaining.
    MoreRemaining,
}

impl Harness {
    /// A harness over `days` consecutive UTC days starting at `start_day`
    /// (`%Y-%m-%d`). One part per day, matching production Mixpanel imports.
    pub async fn new(mock: MockExport, start_day: &str, days: u32, chunk_size: usize) -> Self {
        let provider = mock.provider();
        let date = chrono::NaiveDate::parse_from_str(start_day, "%Y-%m-%d").unwrap();
        let start = Utc
            .from_utc_datetime(&date.and_hms_opt(0, 0, 0).unwrap())
            .to_utc();
        let end = start + chrono::Duration::days(days as i64);

        let staging = TempDir::new().unwrap();
        let job_id = Uuid::now_v7();
        let source = build_source(&mock, provider, staging.path(), start, end);
        source.prepare_for_job().await.unwrap();

        let parts: Vec<PartState> = source
            .keys()
            .await
            .unwrap()
            .into_iter()
            .map(|key| PartState {
                key,
                current_offset: 0,
                total_size: None,
            })
            .collect();
        let job_state = JobState { parts };

        let model = JobModel {
            id: job_id,
            team_id: TEAM_ID,
            created_at: Utc::now(),
            updated_at: Utc::now(),
            lease_id: None,
            leased_until: None,
            status: JobStatus::Running,
            status_message: None,
            display_status_message: None,
            state: Some(job_state.clone()),
            import_config: minimal_job_config(provider),
            secrets: JobSecrets::empty(),
            backoff_attempt: 0,
            backoff_until: None,
            was_leased: false,
        };

        Self {
            provider,
            chunk_size,
            job_id,
            staging,
            start,
            end,
            state: Mutex::new(job_state),
            model: Mutex::new(model),
            parser: Arc::new(build_parser(provider, job_id)),
            source,
            mock,
            emitted: Vec::new(),
        }
    }

    /// Drop and rebuild the source: prepared keys, streaming readers, and staged
    /// `.raw` files are all lost, while the committed `JobState` survives. This
    /// is a pod replacement mid-job.
    pub async fn restart(&mut self) {
        self.source = build_source(
            &self.mock,
            self.provider,
            self.staging.path(),
            self.start,
            self.end,
        );
        self.source.prepare_for_job().await.unwrap();
    }

    /// Fetch and parse up to `max_chunks` chunks, appending emitted events.
    pub async fn run_chunks(&mut self, max_chunks: usize) -> Result<RunOutcome, Error> {
        for _ in 0..max_chunks {
            let next = select_and_fetch_next_chunk(
                &self.state,
                &self.model,
                &self.source,
                &self.parser,
                self.chunk_size,
                self.job_id,
            )
            .await?;
            match next {
                None => return Ok(RunOutcome::Complete),
                Some((_key, parsed, _reset_backoff)) => self.emitted.extend(parsed.data),
            }
        }
        Ok(RunOutcome::MoreRemaining)
    }

    /// Drive the loop until every part is done.
    pub async fn run_to_end(&mut self) -> Result<(), Error> {
        loop {
            if matches!(self.run_chunks(usize::MAX).await?, RunOutcome::Complete) {
                return Ok(());
            }
        }
    }

    /// The committed part states (the harness's stand-in for the DB row).
    pub async fn parts(&self) -> Vec<PartState> {
        self.state.lock().await.parts.clone()
    }
}

fn build_source(
    mock: &MockExport,
    provider: Provider,
    staging: &std::path::Path,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
) -> DateRangeExportSource {
    let extractor = match provider {
        Provider::Mixpanel => ExtractorType::PlainGzip,
        Provider::Amplitude => ExtractorType::ZipGzipJson,
    };
    let auth = match provider {
        Provider::Mixpanel => AuthConfig::MixpanelAuth {
            secret_key: "mock-secret".to_string(),
        },
        Provider::Amplitude => AuthConfig::BasicAuth {
            username: "mock-key".to_string(),
            password: "mock-secret".to_string(),
        },
    };

    DateRangeExportSource::builder(
        mock.export_url(),
        start,
        end,
        86_400,
        extractor.create_extractor(),
        staging.to_path_buf(),
    )
    .with_query_params("from_date".to_string(), "to_date".to_string())
    .with_date_format("%Y-%m-%d".to_string())
    .with_auth(auth)
    .with_retries(0)
    .with_headers(HashMap::new())
    .build()
    .unwrap()
}

/// Assemble the production parser for `provider` around a hand-built
/// `TransformContext`, mirroring `FormatConfig::get_parser` without its
/// `AppContext` (team-token DB lookup) dependency.
fn build_parser(provider: Provider, job_id: Uuid) -> ParserFn {
    let context = TransformContext {
        team_id: TEAM_ID,
        token: TOKEN.to_string(),
        job_id,
        identify_cache: Arc::new(MockIdentifyCache::new()),
        group_cache: Arc::new(MockGroupCache::new()),
        import_events: true,
        generate_identify_events: true,
        generate_group_identify_events: true,
    };

    match provider {
        Provider::Mixpanel => {
            let format_parse = json_nd::<MixpanelEvent>(true);
            let transform =
                MixpanelEvent::parse_fn(context, false, chrono::Duration::zero(), skip_geoip());
            Box::new(move |data| {
                let parsed = format_parse(data)?;
                let consumed = parsed.consumed;
                let result: Result<Vec<_>, Error> = parsed
                    .data
                    .into_par_iter()
                    .map(&transform)
                    .filter_map(|x| x.transpose())
                    .collect();
                Ok(Parsed {
                    data: result?,
                    consumed,
                })
            })
        }
        Provider::Amplitude => {
            let format_parse = json_nd::<AmplitudeEvent>(true);
            let transform = AmplitudeEvent::parse_fn(context, skip_geoip());
            Box::new(move |data| {
                let parsed = format_parse(data)?;
                let consumed = parsed.consumed;
                let result: Result<Vec<Vec<_>>, Error> =
                    parsed.data.into_par_iter().map(&transform).collect();
                Ok(Parsed {
                    data: result?.into_iter().flatten().collect(),
                    consumed,
                })
            })
        }
    }
}

/// The smallest valid `JobConfig`; `select_and_fetch_next_chunk` never reads it,
/// but `JobModel` requires one.
fn minimal_job_config(provider: Provider) -> JobConfig {
    let content = match provider {
        Provider::Mixpanel => serde_json::json!({
            "type": "mixpanel",
            "skip_no_distinct_id": false,
            "timestamp_offset_seconds": null,
        }),
        Provider::Amplitude => serde_json::json!({ "type": "amplitude" }),
    };
    serde_json::from_value(serde_json::json!({
        "source": { "type": "folder", "path": "/unused" },
        "data_format": { "type": "json_lines", "skip_blanks": true, "content": content },
        "sink": { "type": "noop" },
    }))
    .expect("minimal job config must deserialize")
}
