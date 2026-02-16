use std::io::{self, Stdout};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use chrono::Utc;
use common_kafka::kafka_producer::{create_kafka_producer, send_keyed_iter_to_kafka_with_headers};
use common_types::CapturedEvent;
use crossterm::event::{self, Event, KeyCode};
use futures::FutureExt;
use crossterm::terminal::{
    disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen,
};
use crossterm::ExecutableCommand;
use envconfig::Envconfig;
use health::HealthRegistry;
use ratatui::layout::{Constraint, Layout};
use ratatui::prelude::CrosstermBackend;
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, Cell, Gauge, Paragraph, Row, Sparkline, Table};
use ratatui::Terminal;
use rdkafka::consumer::{BaseConsumer, Consumer};
use rdkafka::message::OwnedHeaders;
use rdkafka::{ClientConfig, Offset, TopicPartitionList};
use time::OffsetDateTime;
use std::sync::Mutex;
use uuid::Uuid;

const RATE_STEP: usize = 500;
const DISTINCT_ID_STEP: usize = 10;

#[derive(Envconfig)]
struct BenchmarkConfig {
    #[envconfig(from = "TOKEN")]
    token: String,

    #[envconfig(from = "KAFKA_HOSTS", default = "localhost:9092")]
    kafka_hosts: String,

    #[envconfig(from = "KAFKA_TOPIC", default = "events_plugin_ingestion")]
    kafka_topic: String,

    #[envconfig(from = "KAFKA_GROUP_ID", default = "clickhouse-ingestion")]
    kafka_group_id: String,

    #[envconfig(from = "EVENT_COUNT", default = "0")]
    event_count: usize, // 0 = unlimited

    #[envconfig(from = "BATCH_SIZE", default = "500")]
    batch_size: usize,

    #[envconfig(from = "EVENTS_PER_SEC", default = "0")]
    events_per_sec: usize,

    #[envconfig(from = "DISTINCT_ID_COUNT", default = "100")]
    distinct_id_count: usize,
}

/// Lock-free controls that the UI thread writes and the work task reads
struct Controls {
    events_per_sec: AtomicUsize,
    distinct_id_count: AtomicUsize,
}

fn build_event(i: usize, token: &str, distinct_id_count: usize) -> CapturedEvent {
    let uuid = Uuid::now_v7();
    let id_index = if distinct_id_count > 0 {
        i % distinct_id_count
    } else {
        i
    };
    let distinct_id = format!("bench-user-{id_index}");
    let now = Utc::now();
    let now_rfc3339 = now.to_rfc3339();
    let data = serde_json::json!({
        "uuid": uuid.to_string(),
        "event": "$pageview",
        "distinct_id": distinct_id,
        "token": token,
        "properties": { "benchmark": true, "$current_url": format!("/page/{i}") }
    })
    .to_string();

    CapturedEvent {
        uuid,
        distinct_id,
        session_id: None,
        ip: "127.0.0.1".to_string(),
        data,
        now: now_rfc3339,
        sent_at: Some(OffsetDateTime::from(std::time::SystemTime::now())),
        token: token.to_string(),
        event: "$pageview".to_string(),
        timestamp: now,
        is_cookieless_mode: false,
        historical_migration: false,
    }
}

// -- Ring buffer for sparkline data --

struct RingBuffer {
    data: Vec<u64>,
    head: usize,
    len: usize,
}

impl RingBuffer {
    fn new(capacity: usize) -> Self {
        Self {
            data: vec![0; capacity],
            head: 0,
            len: 0,
        }
    }

    fn push(&mut self, value: u64) {
        self.data[self.head] = value;
        self.head = (self.head + 1) % self.data.len();
        if self.len < self.data.len() {
            self.len += 1;
        }
    }

    fn as_slice_ordered(&self) -> Vec<u64> {
        if self.len < self.data.len() {
            self.data[..self.len].to_vec()
        } else {
            let mut out = Vec::with_capacity(self.data.len());
            out.extend_from_slice(&self.data[self.head..]);
            out.extend_from_slice(&self.data[..self.head]);
            out
        }
    }
}

// -- Shared application state --

#[derive(Clone)]
struct PartitionInfo {
    id: i32,
    committed: i64,
    high_watermark: i64,
    lag: i64,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Phase {
    Producing,
    #[allow(dead_code)]
    Monitoring,
    Done,
}

impl Phase {
    fn label(self) -> &'static str {
        match self {
            Phase::Producing => "Producing",
            Phase::Monitoring => "Monitoring",
            Phase::Done => "Done",
        }
    }
}

/// Snapshot of render-relevant state, cloned from AppState under a brief lock
#[derive(Clone)]
struct StateSnapshot {
    phase: Phase,
    events_produced: usize,
    event_count: usize,
    partitions: Vec<PartitionInfo>,
    log_lines: Vec<(Phase, String)>,
    start_time: Instant,
    config_token: String,
    config_topic: String,
    config_count: usize,
    config_batch: usize,
    // live controls (read from atomics, not from the mutex)
    rate_limit: usize,
    distinct_ids: usize,
}

struct AppState {
    phase: Phase,
    events_produced: usize,
    event_count: usize,
    partitions: Vec<PartitionInfo>,
    total_lag: i64,
    log_lines: Vec<(Phase, String)>,
    start_time: Instant,
    config_token: String,
    config_topic: String,
    config_count: usize,
    config_batch: usize,
}

impl AppState {
    fn log(&mut self, msg: String) {
        self.log_lines.push((self.phase, msg));
        if self.log_lines.len() > 100 {
            self.log_lines.remove(0);
        }
    }

    fn snapshot(&self, controls: &Controls) -> StateSnapshot {
        StateSnapshot {
            phase: self.phase,
            events_produced: self.events_produced,
            event_count: self.event_count,
            partitions: self.partitions.clone(),
            log_lines: self.log_lines.clone(),
            start_time: self.start_time,
            config_token: self.config_token.clone(),
            config_topic: self.config_topic.clone(),
            config_count: self.config_count,
            config_batch: self.config_batch,
            rate_limit: controls.events_per_sec.load(Ordering::Relaxed),
            distinct_ids: controls.distinct_id_count.load(Ordering::Relaxed),
        }
    }
}

// -- Terminal setup / teardown --

fn init_terminal() -> io::Result<Terminal<CrosstermBackend<Stdout>>> {
    enable_raw_mode()?;
    io::stdout().execute(EnterAlternateScreen)?;
    let backend = CrosstermBackend::new(io::stdout());
    Terminal::new(backend)
}

fn restore_terminal() {
    drop(disable_raw_mode());
    drop(io::stdout().execute(LeaveAlternateScreen));
}

// -- Drawing --

fn draw(
    terminal: &mut Terminal<CrosstermBackend<Stdout>>,
    snap: &StateSnapshot,
    throughput_buf: &RingBuffer,
    lag_buf: &RingBuffer,
) -> io::Result<()> {
    terminal.draw(|frame| {
        let area = frame.area();

        let partition_rows = snap.partitions.len().max(1) as u16 + 3; // borders(2) + header(1) + data rows
        let chunks = Layout::vertical([
            Constraint::Length(3), // Header
            Constraint::Length(3), // Progress
            Constraint::Length(7), // Throughput sparkline
            Constraint::Length(7), // Lag sparkline
            Constraint::Length(partition_rows), // Partition table
            Constraint::Min(5),   // Status log
            Constraint::Length(1), // Footer
        ])
        .split(area);

        // -- Header --
        let rate_display = if snap.rate_limit == 0 {
            "unlimited".to_string()
        } else {
            format!("{}/s", snap.rate_limit)
        };
        let header_text = vec![Line::from(vec![
            Span::styled(
                format!("token={}", snap.config_token),
                Style::default().fg(Color::Cyan),
            ),
            Span::raw(" | "),
            Span::styled(
                format!("topic={}", snap.config_topic),
                Style::default().fg(Color::Cyan),
            ),
            Span::raw(" | "),
            Span::styled(
                if snap.config_count == 0 {
                    "count=unlimited".to_string()
                } else {
                    format!("count={}", snap.config_count)
                },
                Style::default().fg(Color::Cyan),
            ),
            Span::raw(" | "),
            Span::styled(
                format!("batch={}", snap.config_batch),
                Style::default().fg(Color::Cyan),
            ),
            Span::raw(" | "),
            Span::styled(
                format!("rate={}", rate_display),
                Style::default().fg(Color::Green),
            ),
            Span::raw(" | "),
            Span::styled(
                format!("distinct_ids={}", snap.distinct_ids),
                Style::default().fg(Color::Green),
            ),
        ])];
        let header = Paragraph::new(header_text).block(
            Block::default()
                .borders(Borders::ALL)
                .title(" Benchmark Config "),
        );
        frame.render_widget(header, chunks[0]);

        // -- Progress gauge --
        let unlimited = snap.event_count == 0;
        let ratio = if !unlimited && snap.event_count > 0 {
            (snap.events_produced as f64 / snap.event_count as f64).min(1.0)
        } else {
            0.0
        };
        let gauge_label = if unlimited {
            format!("{} events produced", snap.events_produced)
        } else {
            format!(
                "{}/{} ({:.1}%)",
                snap.events_produced,
                snap.event_count,
                ratio * 100.0
            )
        };
        let gauge = Gauge::default()
            .block(
                Block::default()
                    .borders(Borders::ALL)
                    .title(if unlimited {
                        " Production (unlimited) "
                    } else {
                        " Production Progress "
                    }),
            )
            .gauge_style(Style::default().fg(Color::Green))
            .ratio(ratio)
            .label(gauge_label);
        frame.render_widget(gauge, chunks[1]);

        // -- Throughput sparkline --
        let throughput_data = throughput_buf.as_slice_ordered();
        let latest_throughput = throughput_data.last().copied().unwrap_or(0);
        let throughput_spark = Sparkline::default()
            .block(
                Block::default()
                    .borders(Borders::ALL)
                    .title(format!(
                        " Throughput (latest: {} events/sec) ",
                        latest_throughput
                    )),
            )
            .data(&throughput_data)
            .style(Style::default().fg(Color::Yellow));
        frame.render_widget(throughput_spark, chunks[2]);

        // -- Lag sparkline --
        let lag_data = lag_buf.as_slice_ordered();
        let current_lag = lag_data.last().copied().unwrap_or(0);
        let lag_spark = Sparkline::default()
            .block(
                Block::default()
                    .borders(Borders::ALL)
                    .title(format!(" E2E Lag (current: {}) ", current_lag)),
            )
            .data(&lag_data)
            .style(Style::default().fg(Color::Magenta));
        frame.render_widget(lag_spark, chunks[3]);

        // -- Partition offset table --
        let header_cells = ["Partition", "Committed", "High Watermark", "Lag"]
            .iter()
            .map(|h| {
                Cell::from(*h).style(
                    Style::default()
                        .fg(Color::White)
                        .add_modifier(Modifier::BOLD),
                )
            });
        let table_header = Row::new(header_cells).height(1);

        let rows = snap.partitions.iter().map(|p| {
            let lag_color = if p.lag == 0 {
                Color::Green
            } else if p.lag < 100 {
                Color::Yellow
            } else {
                Color::Red
            };
            Row::new(vec![
                Cell::from(format!("{:^5}", p.id)),
                Cell::from(format!("{:>10}", p.committed)),
                Cell::from(format!("{:>14}", p.high_watermark)),
                Cell::from(format!("{:>8}", p.lag)).style(Style::default().fg(lag_color)),
            ])
        });

        let table = Table::new(
            rows,
            [
                Constraint::Length(10),
                Constraint::Length(14),
                Constraint::Length(18),
                Constraint::Length(12),
            ],
        )
        .header(table_header)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .title(" Partition Offsets "),
        );
        frame.render_widget(table, chunks[4]);

        // -- Status log --
        let visible_lines: usize = chunks[5].height.saturating_sub(2) as usize;
        let skip = snap.log_lines.len().saturating_sub(visible_lines);
        let log_lines: Vec<Line<'_>> = snap.log_lines[skip..]
            .iter()
            .map(|(phase, msg)| {
                let tag_color = match phase {
                    Phase::Producing => Color::Yellow,
                    Phase::Monitoring => Color::Cyan,
                    Phase::Done => Color::Green,
                };
                Line::from(vec![
                    Span::styled(
                        format!("[{}] ", phase.label()),
                        Style::default().fg(tag_color),
                    ),
                    Span::raw(msg.as_str()),
                ])
            })
            .collect();
        let log = Paragraph::new(log_lines).block(
            Block::default()
                .borders(Borders::ALL)
                .title(" Status "),
        );
        frame.render_widget(log, chunks[5]);

        // -- Footer --
        let elapsed = snap.start_time.elapsed();
        let phase_indicator = match snap.phase {
            Phase::Producing => Span::styled("● Producing", Style::default().fg(Color::Yellow)),
            Phase::Monitoring => Span::styled("● Monitoring", Style::default().fg(Color::Cyan)),
            Phase::Done => Span::styled("● Done", Style::default().fg(Color::Green)),
        };
        let footer = Paragraph::new(Line::from(vec![
            Span::styled(
                " q=quit",
                Style::default().fg(Color::DarkGray),
            ),
            Span::raw(" "),
            Span::styled(
                "↑↓=rate",
                Style::default().fg(Color::Green),
            ),
            Span::raw(" "),
            Span::styled(
                "←→=distinct_ids",
                Style::default().fg(Color::Green),
            ),
            Span::raw(" │ "),
            Span::styled(
                format!("Elapsed: {:.1}s", elapsed.as_secs_f64()),
                Style::default().fg(Color::White),
            ),
            Span::raw(" │ "),
            phase_indicator,
        ]));
        frame.render_widget(footer, chunks[6]);
    })?;

    Ok(())
}

// -- Offset polling task: runs concurrently, updates partition info in state --

async fn run_offset_poller(
    kafka_hosts: String,
    kafka_topic: String,
    kafka_group_id: String,
    state: Arc<Mutex<AppState>>,
) -> anyhow::Result<()> {
    let monitor: Arc<BaseConsumer> = Arc::new(
        ClientConfig::new()
            .set("bootstrap.servers", &kafka_hosts)
            .set("group.id", &kafka_group_id)
            .create()?,
    );

    let topic = kafka_topic.clone();
    let mon = monitor.clone();
    let metadata = tokio::task::spawn_blocking(move || {
        mon.fetch_metadata(Some(&topic), Duration::from_secs(5))
    })
    .await??;
    let partitions: Vec<i32> = metadata.topics()[0]
        .partitions()
        .iter()
        .map(|p| p.id())
        .collect();

    loop {
        let mut total_lag: i64 = 0;
        let mut partition_infos = Vec::new();

        let topic = kafka_topic.clone();
        let mon = monitor.clone();
        let parts = partitions.clone();
        let committed = tokio::task::spawn_blocking(move || {
            let mut tpl = TopicPartitionList::new();
            for &p in &parts {
                tpl.add_partition(&topic, p);
            }
            mon.committed_offsets(tpl, Duration::from_secs(2))
        })
        .await??;

        for &p in &partitions {
            let topic = kafka_topic.clone();
            let mon = monitor.clone();
            let (_low, high) = tokio::task::spawn_blocking(move || {
                mon.fetch_watermarks(&topic, p, Duration::from_secs(2))
            })
            .await??;

            let committed_offset = committed
                .find_partition(&kafka_topic, p)
                .and_then(|tp| match tp.offset() {
                    Offset::Offset(o) => Some(o),
                    _ => None,
                })
                .unwrap_or(0);

            let lag = (high - committed_offset).max(0);
            total_lag += lag;

            partition_infos.push(PartitionInfo {
                id: p,
                committed: committed_offset,
                high_watermark: high,
                lag,
            });
        }

        {
            let mut s = state.lock().unwrap();
            s.partitions = partition_infos;
            s.total_lag = total_lag;
        }

        tokio::time::sleep(Duration::from_secs(1)).await;
    }
}

// -- Work task: produce events, then optionally wait for consumer to catch up --

async fn run_work(
    config_token: String,
    config_kafka_topic: String,
    config_event_count: usize,
    config_batch_size: usize,
    controls: Arc<Controls>,
    state: Arc<Mutex<AppState>>,
) -> anyhow::Result<()> {
    let kafka_config = common_kafka::config::KafkaConfig::init_from_env()?;
    let health = Arc::new(HealthRegistry::new("benchmark"));
    let handle = health
        .register("rdkafka".to_string(), Duration::from_secs(30))
        .await;
    let producer = create_kafka_producer(&kafka_config, handle).await?;

    let unlimited = config_event_count == 0;
    let produce_start = Instant::now();
    let mut produced: usize = 0;
    let mut batch_num: usize = 0;

    {
        let mut s = state.lock().unwrap();
        if unlimited {
            s.log(format!(
                "Starting unlimited event production (batch size {})...",
                config_batch_size
            ));
        } else {
            s.log(format!(
                "Starting event production ({} events, batch size {})...",
                config_event_count, config_batch_size
            ));
        }
    }

    loop {
        if !unlimited && produced >= config_event_count {
            break;
        }

        let batch_start = Instant::now();
        let this_batch = if unlimited {
            config_batch_size
        } else {
            (config_event_count - produced).min(config_batch_size)
        };

        let distinct_id_count = controls.distinct_id_count.load(Ordering::Relaxed);
        let events_per_sec = controls.events_per_sec.load(Ordering::Relaxed);

        let events: Vec<CapturedEvent> = (0..this_batch)
            .map(|j| build_event(produced + j, &config_token, distinct_id_count))
            .collect();

        let results = send_keyed_iter_to_kafka_with_headers(
            &producer,
            &config_kafka_topic,
            |e: &CapturedEvent| Some(e.key()),
            |e: &CapturedEvent| -> Option<OwnedHeaders> { Some(e.to_headers().into()) },
            events,
        )
        .await;

        let errors: Vec<_> = results.iter().filter(|r| r.is_err()).collect();
        if !errors.is_empty() {
            let mut s = state.lock().unwrap();
            s.log(format!(
                "Batch {}: {} errors out of {} events",
                batch_num + 1,
                errors.len(),
                this_batch
            ));
        }

        produced += this_batch;
        batch_num += 1;
        {
            let mut s = state.lock().unwrap();
            s.events_produced = produced;
        }

        if events_per_sec > 0 {
            let target_duration =
                Duration::from_secs_f64(this_batch as f64 / events_per_sec as f64);
            let elapsed = batch_start.elapsed();
            if elapsed < target_duration {
                tokio::time::sleep(target_duration - elapsed).await;
            }
        }
    }

    // In unlimited mode we never get here (task is aborted on 'q')
    let produce_elapsed = produce_start.elapsed();
    let produce_rate = produced as f64 / produce_elapsed.as_secs_f64();

    {
        let mut s = state.lock().unwrap();
        s.phase = Phase::Done;
        s.log(format!(
            "Production complete: {} events in {:.1}s ({:.0} events/sec)",
            produced,
            produce_elapsed.as_secs_f64(),
            produce_rate
        ));
    }

    Ok(())
}

/// Render loop that also handles input. Returns when user presses 'q'.
fn render_loop(
    terminal: &mut Terminal<CrosstermBackend<Stdout>>,
    state: &Arc<Mutex<AppState>>,
    controls: &Arc<Controls>,
    work_handle: &mut Option<tokio::task::JoinHandle<anyhow::Result<()>>>,
) -> io::Result<()> {
    let mut throughput_buf = RingBuffer::new(120);
    let mut lag_buf = RingBuffer::new(120);
    let mut last_produced: usize = 0;
    let mut last_tick = Instant::now();

    loop {
        // Poll for input (250ms = 4 Hz)
        if event::poll(Duration::from_millis(250))? {
            if let Event::Key(key) = event::read()? {
                match key.code {
                    KeyCode::Char('q') => {
                        if let Some(h) = work_handle.take() {
                            h.abort();
                        }
                        return Ok(());
                    }
                    KeyCode::Up => {
                        let cur = controls.events_per_sec.load(Ordering::Relaxed);
                        controls
                            .events_per_sec
                            .store(cur.saturating_add(RATE_STEP), Ordering::Relaxed);
                    }
                    KeyCode::Down => {
                        let cur = controls.events_per_sec.load(Ordering::Relaxed);
                        controls
                            .events_per_sec
                            .store(cur.saturating_sub(RATE_STEP), Ordering::Relaxed);
                    }
                    KeyCode::Right => {
                        let cur = controls.distinct_id_count.load(Ordering::Relaxed);
                        controls
                            .distinct_id_count
                            .store(cur.saturating_add(DISTINCT_ID_STEP), Ordering::Relaxed);
                    }
                    KeyCode::Left => {
                        let cur = controls.distinct_id_count.load(Ordering::Relaxed);
                        controls.distinct_id_count.store(
                            cur.saturating_sub(DISTINCT_ID_STEP).max(1),
                            Ordering::Relaxed,
                        );
                    }
                    _ => {}
                }
            }
        }

        // Brief lock: clone snapshot, then drop
        let snap = {
            let s = state.lock().unwrap();
            let tick_elapsed = last_tick.elapsed().as_secs_f64();
            if tick_elapsed > 0.0 {
                let events_delta = s.events_produced.saturating_sub(last_produced);
                let rate = (events_delta as f64 / tick_elapsed) as u64;
                throughput_buf.push(rate);
                last_produced = s.events_produced;
                last_tick = Instant::now();
            }
            lag_buf.push(s.total_lag.max(0) as u64);
            s.snapshot(controls)
            // lock dropped here
        };

        draw(terminal, &snap, &throughput_buf, &lag_buf)?;

        // If work task finished, handle result then keep rendering until 'q'
        if let Some(h) = work_handle.as_ref() {
            if h.is_finished() {
                let h = work_handle.take().unwrap();
                match h.now_or_never().unwrap() {
                    Ok(Ok(())) => {}
                    Ok(Err(e)) => {
                        let mut s = state.lock().unwrap();
                        s.phase = Phase::Done;
                        s.log(format!("Error: {}", e));
                    }
                    Err(e) if e.is_cancelled() => {}
                    Err(e) => {
                        let mut s = state.lock().unwrap();
                        s.phase = Phase::Done;
                        s.log(format!("Task panicked: {}", e));
                    }
                }
            }
        }
    }
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Install panic hook that restores terminal
    let default_hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        restore_terminal();
        default_hook(info);
    }));

    let config = BenchmarkConfig::init_from_env()?;

    let truncated_token = if config.token.len() > 8 {
        format!("{}...", &config.token[..8])
    } else {
        config.token.clone()
    };

    let controls = Arc::new(Controls {
        events_per_sec: AtomicUsize::new(config.events_per_sec),
        distinct_id_count: AtomicUsize::new(config.distinct_id_count.max(1)),
    });

    let state = Arc::new(Mutex::new(AppState {
        phase: Phase::Producing,
        events_produced: 0,
        event_count: config.event_count,
        partitions: vec![],
        total_lag: 0,
        log_lines: vec![],
        start_time: Instant::now(),
        config_token: truncated_token,
        config_topic: config.kafka_topic.clone(),
        config_count: config.event_count,
        config_batch: config.batch_size,
    }));

    let mut terminal = init_terminal()?;

    // Spawn offset poller (runs for the entire lifetime)
    let poller_state = state.clone();
    let _poller_handle = tokio::spawn(run_offset_poller(
        config.kafka_hosts.clone(),
        config.kafka_topic.clone(),
        config.kafka_group_id.clone(),
        poller_state,
    ));

    // Spawn the producer task
    let work_state = state.clone();
    let work_controls = controls.clone();
    let mut work_handle = Some(tokio::spawn(async move {
        run_work(
            config.token,
            config.kafka_topic,
            config.event_count,
            config.batch_size,
            work_controls,
            work_state,
        )
        .await
    }));

    // Run the render loop on the current thread (blocking, handles crossterm I/O)
    let result = render_loop(
        &mut terminal,
        &state,
        &controls,
        &mut work_handle,
    );

    restore_terminal();
    result.map_err(Into::into)
}
