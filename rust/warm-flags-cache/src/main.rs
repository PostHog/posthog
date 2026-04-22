use std::collections::HashSet;
use std::sync::Arc;
use std::time::{Duration, Instant};

use aws_config::BehaviorVersion;
use clap::Parser;
use common_database::{get_pool, PostgresReader};
use common_hypercache::writer::HyperCacheWriter;
use common_hypercache::{HyperCacheConfig, KeyType};
use common_redis::{CompressionConfig, RedisClient, RedisValueFormat};
use common_s3::{S3Client, S3Impl};
use common_types::TeamId;
use envconfig::Envconfig;
use rand::Rng;
use tokio::task::JoinSet;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::EnvFilter;

use feature_flags::flags::cache_builder::build_flags_cache;

common_alloc::used!();

/// Redis sorted-set key used by Python's `FLAGS_CACHE_EXPIRY_SORTED_SET`. Keeping these
/// in lockstep lets the existing refresh/verification workflows pick up entries this
/// binary warms.
const FLAGS_CACHE_EXPIRY_SORTED_SET: &str = "flags_cache_expiry";

/// Page size for cursor-paged team-ID streaming. Bounds peak in-memory ID buffer to
/// `TEAM_ID_PAGE_SIZE * sizeof(i32)` regardless of total team count.
const TEAM_ID_PAGE_SIZE: i64 = 1000;

#[derive(Parser, Debug)]
#[command(name = "warm-flags-cache")]
struct Cli {
    #[arg(long, num_args = 1..)]
    team_ids: Option<Vec<TeamId>>,

    #[arg(long, conflicts_with = "team_ids")]
    team_ids_stdin: bool,

    #[arg(long, default_value = "10")]
    concurrency: usize,

    #[arg(long, default_value = "5")]
    min_ttl_days: u64,

    #[arg(long, default_value = "7")]
    max_ttl_days: u64,

    #[arg(long)]
    no_stagger: bool,

    /// Warm every team in `posthog_team`, not just teams that have ever had a flag.
    /// Defaults to the "teams-with-flags" scope, matching the Python warmer.
    #[arg(long, conflicts_with_all = ["team_ids", "team_ids_stdin"])]
    all_teams: bool,

    /// Allow falling back to the default `REDIS_URL` when `FLAGS_REDIS_URL` is unset.
    /// Without this flag, the binary refuses to run if `FLAGS_REDIS_URL` is empty —
    /// matching the Python warmer's `check_dedicated_cache_configured()` guard so we
    /// don't accidentally write flags-cache entries into the shared Redis tier.
    #[arg(long)]
    allow_default_redis: bool,
}

#[derive(Envconfig)]
struct InfraConfig {
    #[envconfig(
        from = "READ_DATABASE_URL",
        default = "postgres://posthog:posthog@localhost:5432/posthog"
    )]
    read_database_url: String,

    #[envconfig(from = "FLAGS_REDIS_URL", default = "")]
    flags_redis_url: String,

    #[envconfig(from = "REDIS_URL", default = "redis://localhost:6379/")]
    redis_url: String,

    #[envconfig(from = "OBJECT_STORAGE_BUCKET", default = "posthog")]
    object_storage_bucket: String,

    #[envconfig(from = "OBJECT_STORAGE_REGION", default = "us-east-1")]
    object_storage_region: String,

    #[envconfig(from = "OBJECT_STORAGE_ENDPOINT", default = "")]
    object_storage_endpoint: String,

    #[envconfig(from = "DATABASE_MAX_CONNECTIONS", default = "10")]
    database_max_connections: u32,

    /// Per-command Redis response timeout. Default of 1000ms is intentionally more lenient
    /// than the feature-flags service's 100ms request-path budget — batch warming makes many
    /// calls and a transient blip shouldn't fail the whole run. `0` disables the timeout.
    #[envconfig(from = "FLAGS_REDIS_RESPONSE_TIMEOUT_MS", default = "1000")]
    redis_response_timeout_ms: u64,

    #[envconfig(from = "FLAGS_REDIS_CONNECTION_TIMEOUT_MS", default = "5000")]
    redis_connection_timeout_ms: u64,
}

fn resolve_redis_url(infra: &InfraConfig, allow_default: bool) -> Option<&str> {
    if !infra.flags_redis_url.is_empty() {
        Some(&infra.flags_redis_url)
    } else if allow_default {
        Some(&infra.redis_url)
    } else {
        None
    }
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::builder()
                .with_default_directive(LevelFilter::INFO.into())
                .from_env_lossy(),
        )
        .init();

    let cli = Cli::parse();
    let infra = InfraConfig::init_from_env().expect("Invalid infrastructure configuration");

    if cli.concurrency == 0 {
        tracing::error!("--concurrency must be at least 1");
        std::process::exit(1);
    }

    if let Err(msg) = validate_ttl_range(cli.min_ttl_days, cli.max_ttl_days) {
        tracing::error!("{msg}");
        std::process::exit(1);
    }

    let Some(redis_url) = resolve_redis_url(&infra, cli.allow_default_redis) else {
        tracing::error!(
            "FLAGS_REDIS_URL is not set. Refusing to fall back to the default REDIS_URL — \
             that would write flags-cache entries into the shared Redis tier. \
             Set FLAGS_REDIS_URL or pass --allow-default-redis to override."
        );
        std::process::exit(1);
    };

    let pg_pool = get_pool(&infra.read_database_url, infra.database_max_connections)
        .expect("Failed to create database pool");
    let pg_reader: PostgresReader = Arc::new(pg_pool);

    tracing::info!("Connecting to Redis");
    let response_timeout = optional_duration_ms(infra.redis_response_timeout_ms);
    let connection_timeout = optional_duration_ms(infra.redis_connection_timeout_ms);
    let redis_client = RedisClient::with_config(
        redis_url.to_string(),
        CompressionConfig::default(),
        RedisValueFormat::default(),
        response_timeout,
        connection_timeout,
    )
    .await
    .expect("Failed to connect to Redis");
    let redis_client: Arc<dyn common_redis::Client + Send + Sync> = Arc::new(redis_client);

    let s3_client = create_s3_client(&infra).await;

    let mut cache_config = HyperCacheConfig::new(
        "feature_flags".to_string(),
        "flags.json".to_string(),
        infra.object_storage_region.clone(),
        infra.object_storage_bucket.clone(),
    );
    if !infra.object_storage_endpoint.is_empty() {
        cache_config.s3_endpoint = Some(infra.object_storage_endpoint.clone());
    }
    cache_config.expiry_sorted_set_key = Some(FLAGS_CACHE_EXPIRY_SORTED_SET.to_string());
    let writer = Arc::new(HyperCacheWriter::new(redis_client, s3_client, cache_config));

    let plan = build_team_plan(&cli, &pg_reader).await;
    if plan.total == 0 {
        tracing::info!("No teams to warm");
        return;
    }

    tracing::info!(
        "Warming flags cache for {} teams (concurrency: {})",
        plan.total,
        cli.concurrency
    );

    run_warm(plan, writer, pg_reader, &cli).await;
}

/// Coordinates the warm loop with bounded in-flight tasks and progress logging.
async fn run_warm(
    plan: TeamPlan,
    writer: Arc<HyperCacheWriter>,
    pg_reader: PostgresReader,
    cli: &Cli,
) {
    let total = plan.total;
    let start = Instant::now();
    let mut successful: usize = 0;
    let mut failed: usize = 0;
    let mut completed: usize = 0;
    let step = (total / 20).max(1);
    let mut next_log_at = step;

    let mut join_set: JoinSet<Result<(), (TeamId, String)>> = JoinSet::new();
    let log_progress = |completed: usize, successful: usize, failed: usize| {
        tracing::info!(
            "Progress: {}/{} teams ({}%) — {} ok, {} failed",
            completed,
            total,
            (100 * completed) / total,
            successful,
            failed
        );
    };
    let handle_completion =
        |result: Result<Result<(), (TeamId, String)>, tokio::task::JoinError>,
         successful: &mut usize,
         failed: &mut usize,
         completed: &mut usize,
         next_log_at: &mut usize| {
            match result {
                Ok(Ok(())) => *successful += 1,
                Ok(Err((team_id, err))) => {
                    *failed += 1;
                    tracing::warn!(team_id, error = %err, "Failed to warm cache");
                }
                Err(join_err) => {
                    *failed += 1;
                    tracing::warn!(error = %join_err, "Warm task panicked or was cancelled");
                }
            }
            *completed += 1;
            if *completed >= *next_log_at || *completed == total {
                log_progress(*completed, *successful, *failed);
                *next_log_at = next_log_at.saturating_add(step);
            }
        };

    let mut team_stream = TeamIdStream::new(plan, pg_reader.clone());
    while let Some(team_id) = team_stream.next().await {
        // Cap in-flight tasks at `concurrency`; combined with the seek-paged team-ID
        // stream, peak memory stays O(concurrency + page size) regardless of team count.
        if join_set.len() >= cli.concurrency {
            let result = join_set
                .join_next()
                .await
                .expect("join_set non-empty when len >= concurrency");
            handle_completion(
                result,
                &mut successful,
                &mut failed,
                &mut completed,
                &mut next_log_at,
            );
        }

        let pg = pg_reader.clone();
        let writer = writer.clone();
        let ttl_seconds = compute_ttl(cli);
        join_set.spawn(async move {
            warm_team(pg, &writer, team_id, ttl_seconds)
                .await
                .map_err(|e| (team_id, e.to_string()))
        });
    }

    while let Some(result) = join_set.join_next().await {
        handle_completion(
            result,
            &mut successful,
            &mut failed,
            &mut completed,
            &mut next_log_at,
        );
    }

    let duration = start.elapsed();
    tracing::info!(
        successful,
        failed,
        total,
        duration_secs = duration.as_secs_f64(),
        "Cache warming complete"
    );

    if failed > 0 {
        std::process::exit(1);
    }
}

async fn warm_team(
    pg_reader: PostgresReader,
    writer: &HyperCacheWriter,
    team_id: TeamId,
    ttl_seconds: u64,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let key = KeyType::int(team_id);
    let result = build_flags_cache(pg_reader, team_id).await?;

    let json = serde_json::to_string(&result)?;
    writer.set(&key, &json, ttl_seconds).await?;

    Ok(())
}

/// Validate TTL day range matches Python's warmer (`1..=30`, min <= max).
fn validate_ttl_range(min_ttl_days: u64, max_ttl_days: u64) -> Result<(), String> {
    if !(1..=30).contains(&min_ttl_days) {
        return Err(format!(
            "--min-ttl-days must be between 1 and 30 (got {min_ttl_days})"
        ));
    }
    if !(1..=30).contains(&max_ttl_days) {
        return Err(format!(
            "--max-ttl-days must be between 1 and 30 (got {max_ttl_days})"
        ));
    }
    if min_ttl_days > max_ttl_days {
        return Err(format!(
            "--min-ttl-days ({min_ttl_days}) cannot be greater than --max-ttl-days ({max_ttl_days})"
        ));
    }
    Ok(())
}

fn compute_ttl(cli: &Cli) -> u64 {
    let min_secs = cli.min_ttl_days * 24 * 3600;
    let max_secs = cli.max_ttl_days * 24 * 3600;

    if cli.no_stagger || min_secs == max_secs {
        max_secs
    } else {
        rand::thread_rng().gen_range(min_secs..=max_secs)
    }
}

fn optional_duration_ms(ms: u64) -> Option<Duration> {
    if ms == 0 {
        None
    } else {
        Some(Duration::from_millis(ms))
    }
}

struct TeamPlan {
    total: usize,
    source: TeamSource,
}

enum TeamSource {
    Explicit(Vec<TeamId>),
    DatabaseScan { all_teams: bool },
}

async fn build_team_plan(cli: &Cli, pg_reader: &PostgresReader) -> TeamPlan {
    if let Some(ref ids) = cli.team_ids {
        let validated = validate_team_ids(pg_reader, ids).await;
        reject_if_all_invalid(ids, &validated, "--team-ids");
        return TeamPlan {
            total: validated.len(),
            source: TeamSource::Explicit(validated),
        };
    }

    if cli.team_ids_stdin {
        let ids = read_team_ids_from_stdin();
        let validated = validate_team_ids(pg_reader, &ids).await;
        reject_if_all_invalid(&ids, &validated, "stdin");
        return TeamPlan {
            total: validated.len(),
            source: TeamSource::Explicit(validated),
        };
    }

    let total = count_teams(pg_reader, cli.all_teams).await;
    if cli.all_teams {
        tracing::info!("Found {} teams (all teams in posthog_team)", total);
    } else {
        tracing::info!("Found {} teams that have ever had a flag", total);
    }
    TeamPlan {
        total,
        source: TeamSource::DatabaseScan {
            all_teams: cli.all_teams,
        },
    }
}

/// Returns an error message when the user explicitly supplied team IDs but
/// none passed validation. Split from the exit path so it's unit-testable.
fn check_all_invalid(supplied: &[TeamId], validated: &[TeamId]) -> Option<String> {
    if supplied.is_empty() || !validated.is_empty() {
        None
    } else {
        Some(format!(
            "All supplied team IDs were invalid: {supplied:?}. \
             Check the values against posthog_team."
        ))
    }
}

/// Without this guard, `--team-ids 999999` against a missing team silently
/// exits 0 with "No teams to warm", so operator typos look successful.
fn reject_if_all_invalid(supplied: &[TeamId], validated: &[TeamId], source: &str) {
    if let Some(msg) = check_all_invalid(supplied, validated) {
        tracing::error!(source, "{msg}");
        std::process::exit(1);
    }
}

/// Drops typos and stale IDs so they don't silently produce empty caches and
/// orphan `flags_cache_expiry` entries. Mirrors Python's `_validate_teams()`.
async fn validate_team_ids(pg_reader: &PostgresReader, supplied: &[TeamId]) -> Vec<TeamId> {
    if supplied.is_empty() {
        return vec![];
    }

    let mut conn = pg_reader
        .get_connection()
        .await
        .expect("Failed to get database connection");

    let rows: Vec<(i32,)> = sqlx::query_as("SELECT id FROM posthog_team WHERE id = ANY($1)")
        .bind(supplied)
        .fetch_all(&mut *conn)
        .await
        .expect("Failed to look up team IDs");

    let found: HashSet<TeamId> = rows.iter().map(|(id,)| *id).collect();
    let supplied_set: HashSet<TeamId> = supplied.iter().copied().collect();
    let mut missing: Vec<TeamId> = supplied_set.difference(&found).copied().collect();
    missing.sort_unstable();

    if !missing.is_empty() {
        tracing::warn!(
            missing = ?missing,
            "Some supplied team IDs do not exist in posthog_team — skipping"
        );
    }

    let mut valid: Vec<TeamId> = found.into_iter().collect();
    valid.sort_unstable();
    valid
}

async fn count_teams(pg_reader: &PostgresReader, all_teams: bool) -> usize {
    let mut conn = pg_reader
        .get_connection()
        .await
        .expect("Failed to get database connection");

    let query = if all_teams {
        "SELECT COUNT(*) FROM posthog_team"
    } else {
        "SELECT COUNT(*) FROM posthog_team t \
         WHERE EXISTS (SELECT 1 FROM posthog_featureflag f WHERE f.team_id = t.id)"
    };

    let (count,): (i64,) = sqlx::query_as(query)
        .fetch_one(&mut *conn)
        .await
        .expect("Failed to count teams");
    count as usize
}

struct TeamIdStream {
    source: TeamSourceState,
    pg_reader: PostgresReader,
}

enum TeamSourceState {
    Explicit(std::vec::IntoIter<TeamId>),
    DatabaseScan {
        all_teams: bool,
        last_id: TeamId,
        buffer: std::vec::IntoIter<TeamId>,
        exhausted: bool,
    },
}

impl TeamIdStream {
    fn new(plan: TeamPlan, pg_reader: PostgresReader) -> Self {
        let source = match plan.source {
            TeamSource::Explicit(ids) => TeamSourceState::Explicit(ids.into_iter()),
            TeamSource::DatabaseScan { all_teams } => TeamSourceState::DatabaseScan {
                all_teams,
                last_id: 0,
                buffer: Vec::new().into_iter(),
                exhausted: false,
            },
        };
        Self { source, pg_reader }
    }

    async fn next(&mut self) -> Option<TeamId> {
        match &mut self.source {
            TeamSourceState::Explicit(iter) => iter.next(),
            TeamSourceState::DatabaseScan {
                all_teams,
                last_id,
                buffer,
                exhausted,
            } => loop {
                if let Some(id) = buffer.next() {
                    return Some(id);
                }
                if *exhausted {
                    return None;
                }

                let page = fetch_team_id_page(&self.pg_reader, *all_teams, *last_id).await;
                if page.is_empty() {
                    *exhausted = true;
                    return None;
                }
                *last_id = *page.last().expect("page non-empty");
                *buffer = page.into_iter();
            },
        }
    }
}

/// Fetch the next page of team IDs strictly greater than `after`, ordered by id.
/// Seek pagination keeps memory bounded by `TEAM_ID_PAGE_SIZE` and avoids OFFSET's
/// degradation on large tables.
async fn fetch_team_id_page(
    pg_reader: &PostgresReader,
    all_teams: bool,
    after: TeamId,
) -> Vec<TeamId> {
    let mut conn = pg_reader
        .get_connection()
        .await
        .expect("Failed to get database connection");

    let query = if all_teams {
        "SELECT id FROM posthog_team WHERE id > $1 ORDER BY id LIMIT $2"
    } else {
        "SELECT t.id FROM posthog_team t \
         WHERE t.id > $1 \
         AND EXISTS (SELECT 1 FROM posthog_featureflag f WHERE f.team_id = t.id) \
         ORDER BY t.id LIMIT $2"
    };

    let rows: Vec<(i32,)> = sqlx::query_as(query)
        .bind(after)
        .bind(TEAM_ID_PAGE_SIZE)
        .fetch_all(&mut *conn)
        .await
        .expect("Failed to query team IDs");
    rows.into_iter().map(|(id,)| id).collect()
}

#[derive(Debug)]
enum ParseTeamIdsError {
    Io(std::io::Error),
    Invalid(String, std::num::ParseIntError),
}

fn parse_team_ids<R: std::io::BufRead>(reader: R) -> Result<Vec<TeamId>, ParseTeamIdsError> {
    let mut ids = Vec::new();
    for line in reader.lines() {
        let line = line.map_err(ParseTeamIdsError::Io)?;
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        let id = trimmed
            .parse::<TeamId>()
            .map_err(|e| ParseTeamIdsError::Invalid(trimmed.to_string(), e))?;
        ids.push(id);
    }
    Ok(ids)
}

fn read_team_ids_from_stdin() -> Vec<TeamId> {
    tracing::info!("Reading team IDs from stdin");
    let stdin = std::io::stdin();
    let ids = parse_team_ids(stdin.lock()).unwrap_or_else(|e| match e {
        ParseTeamIdsError::Io(err) => {
            tracing::error!(error = %err, "Failed to read team IDs from stdin");
            std::process::exit(1);
        }
        ParseTeamIdsError::Invalid(value, err) => {
            tracing::error!(error = %err, "Invalid team ID: {value}");
            std::process::exit(1);
        }
    });
    tracing::info!("Read {} team IDs from stdin", ids.len());
    ids
}

async fn create_s3_client(infra: &InfraConfig) -> Arc<dyn S3Client + Send + Sync> {
    let mut aws_config_builder = aws_config::defaults(BehaviorVersion::latest())
        .region(aws_config::Region::new(infra.object_storage_region.clone()));

    if !infra.object_storage_endpoint.is_empty() {
        aws_config_builder = aws_config_builder.endpoint_url(&infra.object_storage_endpoint);
    }

    let aws_config = aws_config_builder.load().await;

    let mut s3_config_builder = aws_sdk_s3::config::Builder::from(&aws_config);
    if !infra.object_storage_endpoint.is_empty() {
        s3_config_builder = s3_config_builder.force_path_style(true);
    }

    let aws_s3_client = aws_sdk_s3::Client::from_conf(s3_config_builder.build());
    Arc::new(S3Impl::new(aws_s3_client))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cli(min: u64, max: u64, no_stagger: bool) -> Cli {
        Cli {
            team_ids: None,
            team_ids_stdin: false,
            concurrency: 10,
            min_ttl_days: min,
            max_ttl_days: max,
            no_stagger,
            all_teams: false,
            allow_default_redis: false,
        }
    }

    fn infra(flags: &str, default: &str) -> InfraConfig {
        InfraConfig {
            flags_redis_url: flags.to_string(),
            redis_url: default.to_string(),
            read_database_url: String::new(),
            object_storage_bucket: String::new(),
            object_storage_region: String::new(),
            object_storage_endpoint: String::new(),
            database_max_connections: 10,
            redis_response_timeout_ms: 1000,
            redis_connection_timeout_ms: 5000,
        }
    }

    #[test]
    fn test_compute_ttl_no_stagger_returns_max() {
        assert_eq!(compute_ttl(&cli(5, 7, true)), 7 * 24 * 3600);
    }

    #[test]
    fn test_compute_ttl_equal_min_max_returns_that_value() {
        assert_eq!(compute_ttl(&cli(5, 5, false)), 5 * 24 * 3600);
    }

    #[test]
    fn test_compute_ttl_stagger_returns_value_in_range() {
        let min_secs = 5 * 24 * 3600;
        let max_secs = 7 * 24 * 3600;
        for _ in 0..100 {
            let ttl = compute_ttl(&cli(5, 7, false));
            assert!(
                ttl >= min_secs && ttl <= max_secs,
                "TTL {ttl} outside [{min_secs}, {max_secs}]"
            );
        }
    }

    #[test]
    fn test_validate_ttl_range_accepts_valid() {
        assert!(validate_ttl_range(1, 30).is_ok());
        assert!(validate_ttl_range(5, 7).is_ok());
        assert!(validate_ttl_range(7, 7).is_ok());
    }

    #[test]
    fn test_validate_ttl_range_rejects_min_below_one() {
        assert!(validate_ttl_range(0, 7).is_err());
    }

    #[test]
    fn test_validate_ttl_range_rejects_max_above_thirty() {
        assert!(validate_ttl_range(5, 31).is_err());
    }

    #[test]
    fn test_validate_ttl_range_rejects_min_above_thirty() {
        assert!(validate_ttl_range(31, 31).is_err());
    }

    #[test]
    fn test_validate_ttl_range_rejects_min_greater_than_max() {
        assert!(validate_ttl_range(8, 7).is_err());
    }

    #[test]
    fn test_resolve_redis_url_prefers_flags_redis() {
        let infra = infra("redis://flags:6379/", "redis://default:6379/");
        assert_eq!(
            resolve_redis_url(&infra, false),
            Some("redis://flags:6379/")
        );
    }

    #[test]
    fn test_resolve_redis_url_returns_none_without_flags_url() {
        let infra = infra("", "redis://default:6379/");
        assert_eq!(resolve_redis_url(&infra, false), None);
    }

    #[test]
    fn test_resolve_redis_url_falls_back_with_explicit_opt_in() {
        let infra = infra("", "redis://default:6379/");
        assert_eq!(
            resolve_redis_url(&infra, true),
            Some("redis://default:6379/")
        );
    }

    #[test]
    fn test_resolve_redis_url_prefers_flags_even_with_opt_in() {
        let infra = infra("redis://flags:6379/", "redis://default:6379/");
        assert_eq!(resolve_redis_url(&infra, true), Some("redis://flags:6379/"));
    }

    #[test]
    fn test_optional_duration_ms_zero_returns_none() {
        assert_eq!(optional_duration_ms(0), None);
    }

    #[test]
    fn test_optional_duration_ms_nonzero_returns_some() {
        assert_eq!(optional_duration_ms(250), Some(Duration::from_millis(250)));
    }

    #[test]
    fn test_parse_team_ids_happy_path() {
        let input: &[u8] = b"1\n2\n3\n";
        let ids = parse_team_ids(input).unwrap();
        assert_eq!(ids, vec![1, 2, 3]);
    }

    #[test]
    fn test_parse_team_ids_skips_blank_and_whitespace_lines() {
        let input: &[u8] = b"1\n\n  2  \n\t\n3\n";
        let ids = parse_team_ids(input).unwrap();
        assert_eq!(ids, vec![1, 2, 3]);
    }

    #[test]
    fn test_parse_team_ids_empty_input_returns_empty() {
        let input: &[u8] = b"";
        let ids = parse_team_ids(input).unwrap();
        assert!(ids.is_empty());
    }

    #[test]
    fn test_parse_team_ids_invalid_id_returns_error() {
        let input: &[u8] = b"1\nabc\n3\n";
        let err = parse_team_ids(input).unwrap_err();
        match err {
            ParseTeamIdsError::Invalid(value, _) => assert_eq!(value, "abc"),
            other => panic!("expected Invalid, got {other:?}"),
        }
    }

    #[test]
    fn test_parse_team_ids_trims_before_reporting_invalid() {
        let input: &[u8] = b"  oops  \n";
        let err = parse_team_ids(input).unwrap_err();
        match err {
            ParseTeamIdsError::Invalid(value, _) => assert_eq!(value, "oops"),
            other => panic!("expected Invalid, got {other:?}"),
        }
    }

    #[test]
    fn test_parse_team_ids_propagates_io_error() {
        struct FailingReader;
        impl std::io::Read for FailingReader {
            fn read(&mut self, _buf: &mut [u8]) -> std::io::Result<usize> {
                Err(std::io::Error::other("boom"))
            }
        }

        let reader = std::io::BufReader::new(FailingReader);
        let err = parse_team_ids(reader).unwrap_err();
        match err {
            ParseTeamIdsError::Io(e) => assert_eq!(e.kind(), std::io::ErrorKind::Other),
            other => panic!("expected Io, got {other:?}"),
        }
    }

    #[test]
    fn test_check_all_invalid_none_supplied_returns_none() {
        assert_eq!(check_all_invalid(&[], &[]), None);
    }

    #[test]
    fn test_check_all_invalid_some_validated_returns_none() {
        assert_eq!(check_all_invalid(&[1, 2], &[1]), None);
    }

    #[test]
    fn test_check_all_invalid_all_invalid_returns_message() {
        let result = check_all_invalid(&[999, 1000], &[]);
        assert!(result.is_some(), "expected error message, got None");
        let msg = result.unwrap();
        assert!(msg.contains("999"), "message should cite the IDs: {msg}");
        assert!(msg.contains("1000"), "message should cite the IDs: {msg}");
    }
}
