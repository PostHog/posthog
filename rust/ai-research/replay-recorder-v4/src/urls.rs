//! Fetch jobs for the remote images a flush's blocks referenced, in the v3 fetch topic's job shape.

use std::collections::{BTreeMap, HashSet};

use posthog_replay_anonymizer::{is_public_host, is_tracking_beacon, try_canonicalize};
use replay_core_v4::keys::batch::{FlushKeys, SessionId};
use replay_core_v4::refs::{image_url_ref, reference_hash};
use replay_core_v4::seal::image_url_key;
use serde_json::{json, Value};

use replay_core_v4::inspect::stats::BlockStats;

use crate::batch::Block;

/// The v3 fetcher's limits on one Kafka record.
const MAX_JOBS_PER_RECORD: usize = 1000;
const MAX_RECORD_BYTES: usize = 512 * 1024;
/// How many redirects a job may follow, as in v3.
const REMAINING_HOPS: u32 = 10;

/// Builds one job per new remote image URL, grouped by registrable domain, the topic's key. Counts each block's URLs
/// in the stats paired with it. `already_sent` names references this process sent for the same team and day.
pub fn fetch_jobs<'b>(
    blocks: impl IntoIterator<Item = (&'b Block, &'b mut BlockStats)>,
    keys: &FlushKeys,
    write_day: &str,
    now_ms: i64,
    already_sent: &dyn Fn(&str) -> bool,
) -> BTreeMap<String, Vec<Value>> {
    let mut jobs: BTreeMap<String, Vec<Value>> = BTreeMap::new();
    let mut seen = HashSet::new();
    for (block, stats) in blocks {
        let id = SessionId {
            team_id: block.session.team_id,
            session_id: block.session.session_id.clone(),
        };
        let (Some(_), Some(team_key)) = (
            keys.sessions.get(&id),
            keys.team_days.get(&block.session.team_id),
        ) else {
            continue;
        };
        let url_key = image_url_key(team_key);
        for raw in &block.image_urls {
            let Ok(url) = try_canonicalize(raw) else {
                continue;
            };
            let path = url::Url::parse(&url.fetch)
                .map(|u| u.path().to_owned())
                .unwrap_or_default();
            if !is_public_host(&url.host) || is_tracking_beacon(&url.host, &path) {
                continue;
            }
            stats.image_urls += 1;
            let reference = image_url_ref(
                block.session.team_id,
                write_day,
                &reference_hash(&url_key, url.dedup.as_bytes()),
            );
            if already_sent(&reference) || !seen.insert(reference.clone()) {
                continue;
            }
            jobs.entry(url.domain.clone()).or_default().push(json!({
                "sessionId": block.session.session_id,
                "originalRef": reference,
                "currentUrl": url.fetch,
                "remainingHops": REMAINING_HOPS,
                "notBeforeMs": 0,
                "firstSeenAtMs": now_ms,
                "fetchCount": 0,
                "republishCount": 0,
                "lastRepublishReason": null,
            }));
        }
    }
    jobs
}

/// Splits each domain's jobs into records the fetcher accepts. Returns (key, payload, references) per record.
pub fn records(jobs: BTreeMap<String, Vec<Value>>) -> Vec<(String, Vec<u8>, Vec<String>)> {
    let mut records = Vec::new();
    for (domain, domain_jobs) in jobs {
        let mut batch: Vec<Value> = Vec::new();
        let mut bytes = 0;
        for job in domain_jobs {
            let size = job.to_string().len() + 1;
            if !batch.is_empty()
                && (batch.len() >= MAX_JOBS_PER_RECORD || bytes + size > MAX_RECORD_BYTES)
            {
                records.push(record(&domain, std::mem::take(&mut batch)));
                bytes = 0;
            }
            bytes += size;
            batch.push(job);
        }
        if !batch.is_empty() {
            records.push(record(&domain, batch));
        }
    }
    records
}

fn record(domain: &str, jobs: Vec<Value>) -> (String, Vec<u8>, Vec<String>) {
    let references = jobs
        .iter()
        .filter_map(|j| j["originalRef"].as_str().map(str::to_owned))
        .collect();
    (
        domain.to_owned(),
        json!({"v": 2, "jobs": jobs}).to_string().into_bytes(),
        references,
    )
}

#[cfg(test)]
mod tests {
    use replay_core_v4::keys::batch::SessionKey as Key;

    use super::*;
    use crate::batch::{Origin, SessionKey, Tp};

    #[test]
    fn sends_each_new_public_image_url_once_by_domain() {
        let urls = [
            "https://cdn.example.com/a.png",
            "https://cdn.example.com/a.png",
            "https://img2.cdn.example.com/b.png",
            "https://cdn.example.com/sent.png",
            "http://localhost/private.png",
            "https://bat.bing.com/action/0",
        ];
        let block = Block {
            session: SessionKey {
                team_id: 7,
                session_id: "s".to_owned(),
            },
            origin: Origin {
                tp: Tp {
                    topic: "main",
                    partition: 0,
                },
                start_offset: 0,
                end_offset: 0,
            },
            messages: Vec::new(),
            stats: BlockStats::default(),
            moments: Vec::new(),
            image_urls: urls.iter().map(|u| (*u).to_owned()).collect(),
        };
        let mut stats = BlockStats::default();
        let mut keys = FlushKeys::default();
        keys.sessions.insert(
            SessionId {
                team_id: 7,
                session_id: "s".to_owned(),
            },
            Key {
                key: [1; 32],
                key_day: "2026-10-15".to_owned(),
            },
        );
        keys.team_days.insert(7, [2; 32]);
        let sent_hash = reference_hash(
            &image_url_key(&[2; 32]),
            try_canonicalize("https://cdn.example.com/sent.png")
                .unwrap()
                .dedup
                .as_bytes(),
        );
        let sent = image_url_ref(7, "2026-10-15", &sent_hash);

        let jobs = fetch_jobs(
            [(&block, &mut stats)],
            &keys,
            "2026-10-15",
            1_000,
            &|reference| reference == sent,
        );
        let domains: Vec<_> = jobs.keys().cloned().collect();
        assert_eq!(domains, ["example.com"]);
        let fetched: Vec<_> = jobs["example.com"]
            .iter()
            .map(|j| j["currentUrl"].as_str().unwrap().to_owned())
            .collect();
        assert_eq!(
            fetched,
            [
                "https://cdn.example.com/a.png",
                "https://img2.cdn.example.com/b.png"
            ]
        );
        let job = &jobs["example.com"][0];
        assert!(job["originalRef"]
            .as_str()
            .unwrap()
            .starts_with("imageurl:v4:7:2026-10-15:"));
        assert_eq!(
            (job["sessionId"].as_str(), job["remainingHops"].as_u64()),
            (Some("s"), Some(10))
        );
        // Every public URL the block referenced counts, sent before or not.
        assert_eq!(stats.image_urls, 4);
    }

    #[test]
    fn splits_a_domains_jobs_at_the_fetchers_record_limit() {
        let jobs = BTreeMap::from([(
            "example.com".to_owned(),
            (0..2500)
                .map(|i| json!({"originalRef": format!("r{i}")}))
                .collect(),
        )]);
        let sizes: Vec<_> = records(jobs)
            .iter()
            .map(|(_, _, references)| references.len())
            .collect();
        assert_eq!(sizes, [1000, 1000, 500]);
    }
}
