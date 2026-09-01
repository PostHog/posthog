//! Log ingestion: sources that yield new raw lines since the last tick, keyed by
//! log stream (RDS instance id / file name), with cursors serialised into
//! collector state.

pub mod fingerprint;
pub mod parse;

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::io::{Read, Seek, SeekFrom};

pub struct Batch {
    /// stream name → lines (in order)
    pub lines: BTreeMap<String, Vec<String>>,
    /// Bytes/events still unread because the per-tick budget ran out.
    pub backlog: u64,
}

// ---------- file source (self-hosted / local dev) ----------

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct FileCursor {
    /// path → (byte offset, partial trailing line)
    pub offsets: BTreeMap<String, (u64, String)>,
    pub initialised: bool,
}

/// Tail every file matching the globs. On the very first run we start at the end
/// of existing files (no history replay); afterwards every new byte is read.
pub fn poll_files(globs: &[String], cur: &mut FileCursor, max_bytes: usize) -> Result<Batch> {
    let mut paths: Vec<std::path::PathBuf> = Vec::new();
    for g in globs {
        for p in glob::glob(g)
            .with_context(|| format!("bad glob {g}"))?
            .flatten()
        {
            if p.is_file() {
                paths.push(p);
            }
        }
    }
    paths.sort();
    let mut lines: BTreeMap<String, Vec<String>> = BTreeMap::new();
    let mut budget = max_bytes;
    let first = !cur.initialised;
    for p in &paths {
        let key = p.to_string_lossy().to_string();
        let len = std::fs::metadata(p)?.len();
        let (mut off, mut partial) = cur
            .offsets
            .get(&key)
            .cloned()
            .unwrap_or((if first { len } else { 0 }, String::new()));
        if len < off {
            off = 0;
            partial.clear();
        } // truncated / rotated in place
        if len > off && budget > 0 {
            let mut f = std::fs::File::open(p)?;
            f.seek(SeekFrom::Start(off))?;
            let take = ((len - off) as usize).min(budget);
            let mut buf = vec![0u8; take];
            f.read_exact(&mut buf)?;
            budget -= take;
            off += take as u64;
            let text = partial + &String::from_utf8_lossy(&buf);
            let mut parts: Vec<&str> = text.split('\n').collect();
            partial = parts.pop().unwrap_or("").to_string();
            let stream = p
                .file_name()
                .map(|n| n.to_string_lossy().to_string())
                .unwrap_or_default();
            lines
                .entry(stream)
                .or_default()
                .extend(parts.into_iter().map(str::to_string));
        }
        cur.offsets.insert(key, (off, partial));
    }
    // forget files that no longer exist
    cur.offsets
        .retain(|k, _| paths.iter().any(|p| p.to_string_lossy() == *k));
    cur.initialised = true;
    let backlog: u64 = paths
        .iter()
        .filter_map(|p| {
            let key = p.to_string_lossy().to_string();
            let len = std::fs::metadata(p).ok()?.len();
            Some(len.saturating_sub(cur.offsets.get(&key).map(|o| o.0).unwrap_or(len)))
        })
        .sum();
    Ok(Batch { lines, backlog })
}

// ---------- CloudWatch Logs source (RDS / Aurora) ----------

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct CloudWatchCursor {
    /// Last event timestamp (ms) fully consumed.
    pub last_ts: Option<i64>,
    /// Event ids seen at `last_ts`, to dedupe the boundary.
    pub seen_at_last_ts: Vec<String>,
    pub initialised: bool,
}

/// Aurora exports each instance's Postgres log to
/// `/aws/rds/cluster/<cluster>/postgresql` with one stream per instance.
/// We read the whole group with FilterLogEvents; events lag real time by a few
/// seconds, so we stop `lag_secs` short of now.
pub async fn poll_cloudwatch(
    client: &aws_sdk_cloudwatchlogs::Client,
    group: &str,
    cur: &mut CloudWatchCursor,
    lag_secs: i64,
    max_events: usize,
) -> Result<Batch> {
    let now_ms = chrono::Utc::now().timestamp_millis();
    let end = now_ms - lag_secs * 1000;
    let start = match cur.last_ts {
        Some(t) => t,
        None if !cur.initialised => end - 60_000, // first run: last minute only
        None => end - 60_000,
    };
    let mut lines: BTreeMap<String, Vec<String>> = BTreeMap::new();
    let mut token: Option<String> = None;
    let mut max_ts = cur.last_ts.unwrap_or(start);
    let mut ids_at_max: Vec<String> = if cur.last_ts == Some(max_ts) {
        cur.seen_at_last_ts.clone()
    } else {
        vec![]
    };
    let mut n = 0usize;
    loop {
        let mut req = client
            .filter_log_events()
            .log_group_name(group)
            .start_time(start)
            .end_time(end);
        if let Some(t) = &token {
            req = req.next_token(t);
        }
        let resp = req
            .send()
            .await
            .with_context(|| format!("FilterLogEvents {group}"))?;
        for ev in resp.events() {
            let (Some(ts), Some(msg)) = (ev.timestamp(), ev.message()) else {
                continue;
            };
            let id = ev.event_id().unwrap_or_default().to_string();
            if Some(ts) == cur.last_ts && cur.seen_at_last_ts.contains(&id) {
                continue;
            }
            if ts > max_ts {
                max_ts = ts;
                ids_at_max.clear();
            }
            if ts == max_ts {
                ids_at_max.push(id);
            }
            let stream = ev.log_stream_name().unwrap_or("unknown").to_string();
            let v = lines.entry(stream).or_default();
            for l in msg.split('\n') {
                v.push(l.to_string());
            }
            n += 1;
        }
        token = resp.next_token().map(str::to_string);
        if token.is_none() || n >= max_events {
            break;
        }
    }
    if n > 0 {
        cur.last_ts = Some(max_ts);
        cur.seen_at_last_ts = ids_at_max;
    }
    cur.initialised = true;
    Ok(Batch {
        lines,
        backlog: if token.is_some() { 1 } else { 0 },
    })
}
