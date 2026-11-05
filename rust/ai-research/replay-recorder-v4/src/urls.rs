//! Fetch jobs for the remote images and fonts a flush's blocks referenced, in the v3 fetch topic's job shape.

use std::collections::{BTreeMap, HashMap};
use std::time::Duration;

use metrics::counter;
use replay_core_v4::keys::batch::{FlushKeys, SessionId};
use replay_core_v4::refs::{public_font_url_ref, reference_hash, url_ref, UrlAsset};
use replay_core_v4::seal::image_url_key;
use replay_core_v4::url_policy::{checked_url, CanonicalUrl, Decline};
use serde_json::{json, Value};

use replay_core_v4::inspect::stats::BlockStats;

use crate::batch::Block;

/// The fetcher's limits on one Kafka record: its job count, and the byte length of its value without key or headers.
const MAX_JOBS_PER_RECORD: usize = 1000;
const MAX_RECORD_BYTES: usize = 512 * 1024;
/// How many redirects a job may follow, as in v3.
const REMAINING_HOPS: u32 = 10;

/// Grouped by asset as well as by domain, the topic's key, because a fetcher that cannot parse one reference dead-letters the whole record.
pub type FetchJobs = BTreeMap<(String, UrlAsset), Vec<Value>>;

/// The remote image and font URLs of a flush's blocks that the URL policy accepts. The flush holds these until it builds
/// its jobs, so a reference is held once, and only while this process had not sent it today when the flush started.
pub struct FlushUrls {
    unsent: Vec<(CanonicalUrl, UrlAsset, String)>,
    blocks: Vec<BlockUrls>,
}

#[derive(Default)]
struct BlockUrls {
    accepted_images: u32,
    unsent: Vec<usize>,
}

impl FlushUrls {
    pub fn new<'b>(
        blocks: impl IntoIterator<Item = &'b Block>,
        keys: &FlushKeys,
        key_month: &str,
        already_sent: &dyn Fn(&str) -> bool,
    ) -> Self {
        let mut unsent = Vec::new();
        let mut positions: HashMap<String, usize> = HashMap::new();
        let blocks = blocks
            .into_iter()
            .map(|block| {
                let mut urls = BlockUrls::default();
                for (url, asset, reference) in remote_urls(block, keys, key_month) {
                    if asset == UrlAsset::Image {
                        urls.accepted_images += 1;
                    }
                    if already_sent(&reference) {
                        continue;
                    }
                    let position = *positions.entry(reference.clone()).or_insert_with(|| {
                        unsent.push((url, asset, reference));
                        unsent.len() - 1
                    });
                    urls.unsent.push(position);
                }
                urls
            })
            .collect();
        Self { unsent, blocks }
    }

    pub fn unsent_references(&self) -> impl Iterator<Item = &String> {
        self.unsent.iter().map(|(_, _, reference)| reference)
    }
}

/// Empty when the flush has no keys for the block's session.
fn remote_urls(
    block: &Block,
    keys: &FlushKeys,
    key_month: &str,
) -> Vec<(CanonicalUrl, UrlAsset, String)> {
    let id = SessionId {
        team_id: block.session.team_id,
        session_id: block.session.session_id.clone(),
    };
    let (Some(_), Some(team_key)) = (
        keys.sessions.get(&id),
        keys.team_months.get(&block.session.team_id),
    ) else {
        return Vec::new();
    };
    let url_key = image_url_key(team_key);
    let images = block.image_urls.iter().map(|url| (url, UrlAsset::Image));
    let fonts = block.font_urls.iter().map(|url| (url, UrlAsset::Font));
    images
        .chain(fonts)
        .filter_map(|(raw, asset)| {
            let (url, reference) =
                url_reference(raw, asset, block.session.team_id, key_month, &url_key).ok()?;
            Some((url, asset, reference))
        })
        .collect()
}

/// Builds one job per new remote image or font URL. Counts the image URLs of each block in the stats paired with it.
/// `index` is the block's position in the blocks that `urls` was built from. `already_sent` names references this
/// process sent or found fresh today.
pub fn fetch_jobs<'b>(
    urls: &FlushUrls,
    blocks: impl IntoIterator<Item = (usize, &'b Block, &'b mut BlockStats)>,
    now_ms: i64,
    already_sent: &dyn Fn(&str) -> bool,
) -> FetchJobs {
    let mut jobs = FetchJobs::new();
    let mut seen = vec![false; urls.unsent.len()];
    for (index, block, stats) in blocks {
        let block_urls = &urls.blocks[index];
        stats.image_urls += block_urls.accepted_images;
        for &position in &block_urls.unsent {
            let (url, asset, reference) = &urls.unsent[position];
            if seen[position] || already_sent(reference) {
                continue;
            }
            seen[position] = true;
            jobs.entry((url.domain.clone(), *asset))
                .or_default()
                .push(json!({
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

/// The reference of a remote image URL, the same in the fetch job and in the stored block, or why the policy declines
/// the URL. `url_key` is the team's URL key for `key_month`.
pub fn url_reference(
    raw: &str,
    asset: UrlAsset,
    team_id: i64,
    key_month: &str,
    url_key: &[u8; 32],
) -> Result<(CanonicalUrl, String), Decline> {
    let url = checked_url(raw)?;
    let public = match asset {
        UrlAsset::Font => public_font_url_ref(&url),
        UrlAsset::Image => None,
    };
    let reference = public.unwrap_or_else(|| {
        url_ref(
            asset,
            team_id,
            key_month,
            &reference_hash(url_key, url.dedup.as_bytes()),
        )
    });
    Ok((url, reference))
}

/// Splits each group of jobs into records the fetcher accepts. Returns (domain, payload, references) per record.
/// The fetcher rejects a whole record whose value exceeds its byte limit, so a job too large for any record is dropped.
pub fn records(jobs: FetchJobs) -> Vec<(String, Vec<u8>, Vec<String>)> {
    let empty_bytes = payload(Vec::new()).len();
    let mut records = Vec::new();
    let mut oversized = 0u64;
    for ((domain, _), domain_jobs) in jobs {
        let mut batch: Vec<Value> = Vec::new();
        let mut bytes = empty_bytes;
        for job in domain_jobs {
            let size = job.to_string().len();
            if empty_bytes + size > MAX_RECORD_BYTES {
                oversized += 1;
                continue;
            }
            if !batch.is_empty()
                && (batch.len() >= MAX_JOBS_PER_RECORD || bytes + 1 + size > MAX_RECORD_BYTES)
            {
                records.push(record(&domain, std::mem::take(&mut batch)));
                bytes = empty_bytes;
            }
            bytes += size + usize::from(!batch.is_empty());
            batch.push(job);
        }
        if !batch.is_empty() {
            records.push(record(&domain, batch));
        }
    }
    if oversized > 0 {
        counter!("ai_research_v4_recorder_dropped_image_fetch_jobs_total", "reason" => "oversized")
            .increment(oversized);
    }
    records
}

fn record(domain: &str, jobs: Vec<Value>) -> (String, Vec<u8>, Vec<String>) {
    let references = jobs
        .iter()
        .filter_map(|j| j["originalRef"].as_str().map(str::to_owned))
        .collect();
    (domain.to_owned(), payload(jobs), references)
}

/// The record value exactly as the fetcher measures it.
fn payload(jobs: Vec<Value>) -> Vec<u8> {
    json!({"v": 2, "jobs": jobs}).to_string().into_bytes()
}

/// The marks of references sent to the fetcher, by UTC day. The recorder only inserts marks and asks for them with
/// `contains_key`, which does not count as a read. So moka's default policy would refuse every new mark once the cache
/// is full, and LRU is the policy that keeps the newest.
pub fn sent_urls(capacity: u64) -> moka::sync::Cache<(String, String), ()> {
    moka::sync::Cache::builder()
        .max_capacity(capacity)
        // A mark names its UTC day, so it is of no use after a day.
        .time_to_live(Duration::from_secs(24 * 3600))
        .eviction_policy(moka::policy::EvictionPolicy::lru())
        .build()
}

#[cfg(test)]
mod tests {
    use replay_core_v4::keys::batch::SessionKey as Key;
    use replay_core_v4::url_policy::try_canonicalize;

    use super::*;
    use crate::batch::{Origin, SessionKey, Tp};

    #[test]
    fn a_full_sent_cache_still_keeps_new_marks() {
        let sent = sent_urls(100);
        let mark = |round: u32, i: u32| ("2026-10-15".to_owned(), format!("{round}-{i}"));
        for round in 0..2 {
            for i in 0..100 {
                sent.insert(mark(round, i), ());
            }
            sent.run_pending_tasks();
        }
        assert!((0..100).all(|i| sent.contains_key(&mark(1, i))));
    }

    fn block(session_id: &str, urls: &[&str]) -> Block {
        Block {
            session: SessionKey {
                team_id: 7,
                session_id: session_id.to_owned(),
            },
            origin: Origin {
                tp: Tp {
                    topic: "main",
                    partition: 0,
                },
                start_offset: 0,
                end_offset: 0,
                flush_end_offset: 0,
            },
            messages: Vec::new(),
            stats: BlockStats::default(),
            moments: Vec::new(),
            image_urls: urls.iter().map(|u| (*u).to_owned()).collect(),
            font_urls: Vec::new(),
            url_limit: None,
            edits: Vec::new(),
            unplaced: false,
            visited_urls: Vec::new(),
            captured_at_ms: None,
        }
    }

    fn keys(session_ids: &[&str]) -> FlushKeys {
        let mut keys = FlushKeys::default();
        for session_id in session_ids {
            keys.sessions.insert(
                SessionId {
                    team_id: 7,
                    session_id: (*session_id).to_owned(),
                },
                Key {
                    key: [1; 32],
                    key_month: "2026-10".to_owned(),
                },
            );
        }
        keys.team_months.insert(7, [2; 32]);
        keys
    }

    #[test]
    fn sends_each_new_public_image_url_once_by_domain() {
        let block = block(
            "s",
            &[
                "https://cdn.example.com/a.png",
                "https://cdn.example.com/a.png",
                "https://img2.cdn.example.com/b.png",
                "https://cdn.example.com/sent.png",
                "http://localhost/private.png",
                "https://bat.bing.com/action/0",
            ],
        );
        let mut stats = BlockStats::default();
        let sent_hash = reference_hash(
            &image_url_key(&[2; 32]),
            try_canonicalize("https://cdn.example.com/sent.png")
                .unwrap()
                .dedup
                .as_bytes(),
        );
        let sent = url_ref(UrlAsset::Image, 7, "2026-10", &sent_hash);
        let already_sent = |reference: &str| reference == sent;

        let urls = FlushUrls::new([&block], &keys(&["s"]), "2026-10", &already_sent);
        let jobs = fetch_jobs(&urls, [(0, &block, &mut stats)], 1_000, &already_sent);
        let images = ("example.com".to_owned(), UrlAsset::Image);
        assert_eq!(jobs.keys().collect::<Vec<_>>(), [&images]);
        let fetched: Vec<_> = jobs[&images]
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
        let job = &jobs[&images][0];
        assert!(job["originalRef"]
            .as_str()
            .unwrap()
            .starts_with("imageurl:v4:7:2026-10:"));
        assert_eq!(
            (job["sessionId"].as_str(), job["remainingHops"].as_u64()),
            (Some("s"), Some(10))
        );
        // Every public URL the block referenced counts, sent before or not.
        assert_eq!(stats.image_urls, 4);
    }

    fn jobs_of(asset: UrlAsset, jobs: Vec<Value>) -> FetchJobs {
        BTreeMap::from([(("example.com".to_owned(), asset), jobs)])
    }

    #[test]
    fn holds_each_unsent_reference_once_and_sends_it_for_the_first_kept_block() {
        let shared = "https://cdn.example.com/shared.png";
        let blocks = [
            block("dropped", &[shared]),
            block(
                "first",
                &[shared, shared, "https://cdn.example.com/own.png"],
            ),
            block("second", &[shared]),
        ];
        let urls = FlushUrls::new(
            &blocks,
            &keys(&["dropped", "first", "second"]),
            "2026-10",
            &|_| false,
        );
        assert_eq!(urls.unsent_references().count(), 2);

        let mut stats = [BlockStats::default(), BlockStats::default()];
        let [first_stats, second_stats] = &mut stats;
        let jobs = fetch_jobs(
            &urls,
            [(1, &blocks[1], first_stats), (2, &blocks[2], second_stats)],
            1_000,
            &|_| false,
        );
        let sessions: Vec<_> = jobs[&("example.com".to_owned(), UrlAsset::Image)]
            .iter()
            .map(|job| job["sessionId"].as_str().unwrap())
            .collect();
        assert_eq!(sessions, ["first", "first"]);
        assert_eq!((stats[0].image_urls, stats[1].image_urls), (3, 1));
    }

    #[test]
    fn splits_a_domains_jobs_at_the_fetchers_record_limit_and_by_asset() {
        let mut jobs = jobs_of(
            UrlAsset::Image,
            (0..2500)
                .map(|i| json!({"originalRef": format!("r{i}")}))
                .collect(),
        );
        jobs.extend(jobs_of(
            UrlAsset::Font,
            vec![json!({"originalRef": "font"})],
        ));
        let records = records(jobs);
        let sizes: Vec<_> = records
            .iter()
            .map(|(_, _, references)| references.len())
            .collect();
        assert_eq!(sizes, [1000, 1000, 500, 1]);
        assert_eq!(records[3].2, ["font"]);
        assert!(records.iter().all(|(domain, _, _)| domain == "example.com"));
    }

    fn padded(reference: &str, pad: usize) -> Value {
        json!({"originalRef": reference, "pad": "x".repeat(pad)})
    }

    #[test]
    fn fills_a_record_to_the_fetchers_byte_limit_and_no_further() {
        let empty = payload(Vec::new()).len();
        let bare = padded("a", 0).to_string().len();
        // Two jobs and a comma that fill the record value to the exact limit.
        let first = MAX_RECORD_BYTES - empty - 2 * bare - 1 - 10;
        for (extra, expected) in [(0, vec![2]), (1, vec![1, 1])] {
            let jobs = jobs_of(
                UrlAsset::Image,
                vec![padded("a", first), padded("b", 10 + extra)],
            );
            let records = records(jobs);
            let sizes: Vec<_> = records.iter().map(|(_, _, r)| r.len()).collect();
            assert_eq!(sizes, expected, "extra {extra}");
            assert!(records.iter().all(|(_, p, _)| p.len() <= MAX_RECORD_BYTES));
            if extra == 0 {
                assert_eq!(records[0].1.len(), MAX_RECORD_BYTES);
            }
        }
    }

    #[test]
    fn drops_only_a_job_too_large_for_any_record() {
        let room = MAX_RECORD_BYTES - payload(Vec::new()).len() - padded("a", 0).to_string().len();
        let jobs = jobs_of(
            UrlAsset::Image,
            vec![
                padded("fits", 0),
                padded("a", room + 1),
                padded("full", room - 3),
            ],
        );
        let records = records(jobs);
        let references: Vec<_> = records.iter().map(|(_, _, r)| r.clone()).collect();
        assert_eq!(
            references,
            [vec!["fits".to_owned()], vec!["full".to_owned()]]
        );
        assert_eq!(records[1].1.len(), MAX_RECORD_BYTES);
    }
}
