//! PostHog Scout reports, brought into the inboxes of topics that asked for them,
//! with the person's verdict written back to PostHog.
use crate::Server;
use anyhow::Result;
use meep_posthog::signals::{ScoutReport, ScoutSignal, Signals};
use meep_topic::{
    ExternalReport, ReportEvidence, ReportOutcome, ReportPriority, ReportSources, TopicId,
};
use serde_json::Value;
use std::time::Duration;
use tokio_util::sync::CancellationToken;

/// The producer name imported reports carry.
pub(crate) const PROVIDER: &str = "posthog-scout";
const POLL: Duration = Duration::from_secs(120);
const PER_POLL: usize = 20;

pub(super) async fn run(s: Server, stop: CancellationToken) {
    // Not at boot: startup has better things to do than poll PostHog.
    let start = tokio::time::Instant::now() + Duration::from_secs(30);
    let mut tick = tokio::time::interval_at(start, POLL);
    tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    loop {
        tokio::select! {
            _ = stop.cancelled() => break,
            _ = tick.tick() => {}
        }
        // Read committed snapshots, off the async workers, so the poll never
        // waits on (or holds up) a topic's live state.
        let engine = s.engine.clone();
        let due = tokio::task::spawn_blocking(move || {
            engine
                .topic_ids()
                .into_iter()
                .filter_map(|t| pending(&engine.snapshot(t).ok()?.state).map(|p| (t, p)))
                .collect::<Vec<_>>()
        })
        .await
        .unwrap_or_default();
        for (topic, work) in due {
            if let Err(e) = sync(&s, topic, work).await {
                log::warn!("Scout reports for topic {topic}: {e:#}");
            }
        }
    }
}

/// What a topic needs from PostHog: its feed, and verdicts not yet written back.
struct Pending {
    feed: Option<String>,
    unsynced: Vec<(meep_topic::ThreadId, String, ReportOutcome, String)>,
}

fn pending(st: &meep_topic::TopicState) -> Option<Pending> {
    let feed = (!st.archived && !st.deleted)
        .then(|| st.topic.settings.scout_feed.clone())
        .flatten();
    let unsynced: Vec<_> = st
        .threads
        .iter()
        .filter_map(|t| {
            let r = t.report_sources.as_ref()?;
            let e = r.external.as_ref().filter(|e| e.provider == PROVIDER)?;
            let v = r.verdict.as_ref()?;
            (e.synced != Some(v.outcome)).then(|| (t.id, e.id.clone(), v.outcome, v.reason.clone()))
        })
        .collect();
    (feed.is_some() || !unsynced.is_empty()).then_some(Pending { feed, unsynced })
}

/// Import new ready reports for one topic and push its verdicts back, now.
pub(crate) async fn sync_topic(s: &Server, topic: TopicId) -> Result<usize> {
    match pending(&s.engine.snapshot(topic)?.state) {
        Some(work) => sync(s, topic, work).await,
        None => Ok(0),
    }
}

async fn sync(s: &Server, topic: TopicId, work: Pending) -> Result<usize> {
    let Pending { feed, unsynced } = work;
    let Ok((_, project)) = s.accounts.project(topic) else {
        return Ok(0);
    };
    let signals = Signals::new(&project.origin, project.project)?;
    for (thread, id, outcome, reason) in unsynced {
        let resolved = outcome == ReportOutcome::Resolved;
        signals
            .set_state(
                &project.token,
                &id,
                resolved,
                posthog_reason(resolved, &reason),
            )
            .await?;
        s.engine.mark_report_synced(topic, thread, outcome).await?;
    }
    let Some(feed) = feed else { return Ok(0) };
    // PostHog matches a search as one phrase; the feed is keywords, any of which may match.
    let words: Vec<&str> = feed
        .split(|c: char| c.is_whitespace() || c == ',')
        .filter(|w| w.len() > 1)
        .take(5)
        .collect();
    let mut reports: Vec<ScoutReport> = vec![];
    for term in if words.is_empty() { vec![""] } else { words } {
        for r in signals
            .ready_reports(&project.token, Some(term), PER_POLL)
            .await?
        {
            if !reports.iter().any(|seen| seen.id == r.id) {
                reports.push(r);
            }
        }
    }
    let mut imported = 0;
    for report in reports {
        let known = s.engine.snapshot(topic).map(|snap| {
            snap.state.threads.iter().any(|t| {
                t.report_sources
                    .as_ref()
                    .and_then(|r| r.external.as_ref())
                    .is_some_and(|e| e.provider == PROVIDER && e.id == report.id)
            })
        })?;
        if known {
            continue;
        }
        let evidence = signals
            .signals(&project.token, &report.id)
            .await
            .unwrap_or_default();
        let url = format!(
            "{}/project/{}/inbox/reports/{}",
            project.origin.trim_end_matches('/'),
            project.project,
            report.id
        );
        let (title, body, sources) = convert(&report, &evidence, url);
        if s.engine
            .import_report(topic, "PostHog Scout", &title, &body, sources)
            .await?
            .is_some()
        {
            imported += 1;
        }
    }
    Ok(imported)
}

/// A Scout report as a Meep inbox report: headline, write-up and sources.
pub(crate) fn convert(
    r: &ScoutReport,
    signals: &[ScoutSignal],
    url: String,
) -> (String, String, ReportSources) {
    let title = headline(r.title.as_deref().unwrap_or("Untitled Scout report"));
    let mut body = r.summary.clone().unwrap_or_default().trim().to_owned();
    if body.is_empty() || body == title {
        body = format!("PostHog Scout found this. Open it in PostHog for the full write-up: {url}");
    }
    body = body.chars().take(16000).collect();
    let evidence = signals
        .iter()
        .take(10)
        .filter_map(|sig| {
            let text = sig
                .headline
                .clone()
                .filter(|h| !h.trim().is_empty())
                .unwrap_or_else(|| sig.content.lines().next().unwrap_or_default().to_owned());
            let text: String = text.trim().chars().take(300).collect();
            if text.is_empty() {
                return None;
            }
            let link = sig
                .link
                .as_ref()
                .and_then(|l| l.get("url").or(Some(l)))
                .and_then(Value::as_str)
                .filter(|u| u.starts_with("https://") || u.starts_with("http://"))
                .map(str::to_owned);
            let source =
                link.unwrap_or_else(|| format!("{} · {}", sig.source_product, sig.source_id));
            Some(ReportEvidence {
                description: text,
                source_id: source.chars().take(2000).collect(),
                kind: Some(kind(&sig.source_product).into()),
                at: sig
                    .timestamp
                    .as_deref()
                    .and_then(|t| chrono::DateTime::parse_from_rfc3339(t).ok())
                    .map(|t| t.with_timezone(&chrono::Utc)),
            })
        })
        .collect::<Vec<_>>();
    // Evidence can lag behind the report in PostHog; the report itself is then the source.
    let evidence = if evidence.is_empty() {
        vec![ReportEvidence {
            description: "The full Scout report in PostHog".into(),
            source_id: url.clone(),
            kind: None,
            at: None,
        }]
    } else {
        evidence
    };
    let sources = ReportSources {
        priority: r.priority.as_deref().and_then(ReportPriority::parse),
        impact: impact(&r.metrics),
        proposal: proposal(&body).or_else(|| {
            r.suggested_prompts
                .first()
                .map(|p| p.trim().chars().take(600).collect())
                .filter(|p: &String| !p.is_empty())
        }),
        evidence,
        references: vec![],
        external: Some(ExternalReport {
            provider: PROVIDER.into(),
            id: r.id.clone(),
            url,
            synced: None,
        }),
        ..Default::default()
    };
    (title, body, sources)
}

/// Drop a conventional-commit prefix ("fix(web): …") and keep one line.
fn headline(title: &str) -> String {
    let line = title.lines().next().unwrap_or_default().trim();
    let line = match line.split_once(": ") {
        Some((prefix, rest))
            if prefix.len() <= 24 && !prefix.contains(' ') && !rest.trim().is_empty() =>
        {
            rest.trim()
        }
        _ => line,
    };
    let mut out: String = line.chars().take(300).collect();
    if let Some(first) = out.get(0..1) {
        out.replace_range(0..1, &first.to_uppercase());
    }
    out
}

/// The sentence with the number that matters: the affected-users metric, else the primary one.
fn impact(metrics: &[Value]) -> Option<String> {
    let pick = metrics
        .iter()
        .find(|m| m["kind"] == "affected_users" && !m["value"].is_null())
        .or_else(|| {
            metrics
                .iter()
                .find(|m| m["role"] == "primary" && !m["value"].is_null())
        })?;
    let value = pick["value"].as_f64()?;
    let title = pick["title"].as_str()?.trim();
    let number = if value.fract() == 0.0 && value.abs() < 1e15 {
        thousands(value as i64)
    } else {
        format!("{value:.1}")
    };
    let mut label = title.to_owned();
    if let Some(first) = label.get(0..1) {
        label.replace_range(0..1, &first.to_lowercase());
    }
    Some(format!("{number} {label}"))
}

fn thousands(n: i64) -> String {
    let digits = n.unsigned_abs().to_string();
    let mut out = String::new();
    for (i, c) in digits.chars().enumerate() {
        if i > 0 && (digits.len() - i).is_multiple_of(3) {
            out.push(',');
        }
        out.push(c);
    }
    if n < 0 { format!("-{out}") } else { out }
}

/// The write-up's Solution (or Fix, Recommendation, Next steps) section.
fn proposal(summary: &str) -> Option<String> {
    const NAMES: &[&str] = &[
        "solution",
        "fix",
        "proposed fix",
        "recommendation",
        "next steps",
        "proposal",
    ];
    let mut lines = summary.lines().peekable();
    while let Some(line) = lines.next() {
        let t = line.trim();
        let (name, inline) = if let Some(h) = t.strip_prefix('#') {
            (
                h.trim_start_matches('#')
                    .trim()
                    .trim_end_matches(':')
                    .to_lowercase(),
                String::new(),
            )
        } else if let Some(b) = t.strip_prefix("**") {
            let (name, rest) = b.split_once("**").unwrap_or((b, ""));
            (
                name.trim().trim_end_matches(':').to_lowercase(),
                rest.trim_start_matches(':').trim().to_owned(),
            )
        } else {
            continue;
        };
        if !NAMES.contains(&name.as_str()) {
            continue;
        }
        let mut text = inline;
        while let Some(next) = lines.peek() {
            let n = next.trim();
            if n.starts_with('#') || (n.starts_with("**") && n.contains(":**")) {
                break;
            }
            if !n.is_empty() {
                if !text.is_empty() {
                    text.push(' ');
                }
                text.push_str(n);
            }
            lines.next();
        }
        let text: String = text.chars().take(600).collect();
        if !text.is_empty() {
            return Some(text);
        }
    }
    None
}

/// Evidence kinds from PostHog product names.
fn kind(product: &str) -> &'static str {
    match product {
        "error_tracking" | "sentry" => "error",
        "session_replay" | "replay_vision" => "replay",
        "analytics" | "web_analytics" | "product_analytics" => "insight",
        "github" | "gitlab" => "github",
        "conversations" | "zendesk" => "ticket",
        "surveys" => "survey",
        "logs" => "log",
        "llm_analytics" => "event",
        _ => "other",
    }
}

/// PostHog's reason codes for a Meep verdict.
fn posthog_reason(resolved: bool, reason: &str) -> &'static str {
    match (resolved, reason) {
        (true, "No action needed") => "no_action_needed",
        (true, _) => "fixed_outside_posthog",
        (false, "Already fixed") => "already_fixed",
        (false, "Report unclear") => "report_unclear",
        (false, "Analysis wrong") => "analysis_wrong",
        (false, r) if r.starts_with("Won") => "wontfix_intentional",
        (false, "Not relevant") => "wontfix_irrelevant",
        (false, _) => "other",
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn a_scout_report_becomes_an_inbox_report_with_its_number_and_proposal() {
        let report: ScoutReport = serde_json::from_value(json!({
            "id": "r1", "title": "fix(home): stop first Today home load failing", "status": "ready",
            "priority": "P1",
            "summary": "Users land on a broken Today home.\n\n## Problem\nThe retry was removed.\n\n## Solution\nBring back a bounded first-load retry.\n\n## Impact\nMany.",
            "metrics": [{"kind": "affected_users", "role": "primary", "title": "Users who see the toast", "value": 4749}],
        })).unwrap();
        let signals: Vec<ScoutSignal> = serde_json::from_value(json!([
            {"source_product": "session_replay", "source_id": "s1", "headline": "A red toast appears", "content": "", "timestamp": "2026-11-20T10:00:00Z", "link": {"url": "https://example.org/replay/s1"}},
            {"source_product": "error_tracking", "source_id": "e1", "content": "Error: Not found\nstack", "timestamp": null},
        ])).unwrap();
        let (title, body, s) = convert(
            &report,
            &signals,
            "https://example.org/inbox/reports/r1".into(),
        );
        assert_eq!(title, "Stop first Today home load failing");
        assert!(body.starts_with("Users land on a broken Today home."));
        assert_eq!(s.priority, Some(ReportPriority::P1));
        assert_eq!(s.impact.as_deref(), Some("4,749 users who see the toast"));
        assert_eq!(
            s.proposal.as_deref(),
            Some("Bring back a bounded first-load retry.")
        );
        assert_eq!(s.evidence[0].kind.as_deref(), Some("replay"));
        assert_eq!(s.evidence[0].source_id, "https://example.org/replay/s1");
        assert_eq!(s.evidence[1].description, "Error: Not found");
        assert_eq!(s.external.unwrap().id, "r1");
    }
}
