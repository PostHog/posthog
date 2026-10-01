//! The remote image URLs one replay message collected, held outside the V8 heap until the produce
//! builds the fetch topic's records. `ml-mirror-image-fetch/collected-urls-record.ts` parses them.

use std::collections::{HashMap, HashSet};

use posthog_replay_anonymizer::collect::url_ref;
use posthog_replay_anonymizer::snapshot::UrlEntry;

use crate::dedup::{transport_url_key, DedupKey, RefDedupCache};

const RECORD_HEAD: &[u8] = br#"{"v":2,"jobs":["#;
const RECORD_TAIL: &[u8] = b"]}";

pub fn url_reference(namespace: Option<&str>, hash: &str) -> String {
    match namespace {
        Some(namespace) => format!("imageurl:{namespace}:{hash}"),
        None => url_ref(hash),
    }
}

struct CollectedUrl {
    reference: String,
    url: String,
    domain: String,
    key: DedupKey,
}

#[derive(Debug, PartialEq, Eq)]
pub struct OutOfOrder(pub &'static str);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Stage {
    Collected,
    Claimed,
    Built,
}

pub struct UrlBatch {
    first_ref: String,
    count: usize,
    entries: Vec<CollectedUrl>,
    /// The time bucket that every entry's `key` belongs to, or `None` when no key is valid yet.
    keys_bucket: Option<u64>,
    stage: Stage,
    published_keys: Vec<DedupKey>,
}

pub struct JobTemplate {
    head: Vec<u8>,
    tail: Vec<u8>,
}

impl JobTemplate {
    pub fn new(session_id: Option<&str>, first_seen_at_ms: u64) -> Self {
        let mut head = b"{".to_vec();
        if let Some(session_id) = session_id {
            head.extend_from_slice(br#""sessionId":"#);
            write_json_string(&mut head, session_id);
            head.push(b',');
        }
        head.extend_from_slice(br#""originalRef":"#);
        let tail = format!(
            r#","remainingHops":10,"notBeforeMs":0,"firstSeenAtMs":{first_seen_at_ms},"fetchCount":0,"republishCount":0,"lastRepublishReason":null}}"#
        )
        .into_bytes();
        Self { head, tail }
    }

    fn write(&self, out: &mut Vec<u8>, reference: &str, url: &str) {
        out.extend_from_slice(&self.head);
        write_json_string(out, reference);
        out.extend_from_slice(br#","currentUrl":"#);
        write_json_string(out, url);
        out.extend_from_slice(&self.tail);
    }
}

/// For a `str`, serde_json escapes the same characters as `JSON.stringify` and in the same form.
fn write_json_string(out: &mut Vec<u8>, value: &str) {
    serde_json::to_writer(&mut *out, value).expect("a str always serializes into a Vec");
}

#[derive(Debug, Clone, Copy)]
pub struct RecordLimits {
    pub max_bytes: usize,
    pub max_urls: usize,
}

#[derive(Debug, PartialEq)]
pub struct UrlRecord {
    pub registrable_domain: String,
    pub value: Vec<u8>,
    pub url_count: usize,
}

#[derive(Debug, PartialEq)]
pub struct UrlRecords {
    pub records: Vec<UrlRecord>,
    pub url_byte_lengths: Vec<u32>,
    pub domain_count: usize,
}

impl UrlBatch {
    pub fn collect(
        namespace: Option<&str>,
        entries: Vec<UrlEntry>,
        produced: Option<(&RefDedupCache, u64)>,
    ) -> (Option<Self>, usize) {
        let keys_bucket = produced.map(|(_, time_bucket)| time_bucket);
        let mut urls: Vec<CollectedUrl> = entries
            .into_iter()
            .map(|entry| {
                let reference = url_reference(namespace, &entry.hash);
                let key = keys_bucket.map_or([0; 16], |time_bucket| {
                    transport_url_key(&reference, &entry.url, time_bucket)
                });
                CollectedUrl {
                    reference,
                    url: entry.url,
                    domain: entry.domain,
                    key,
                }
            })
            .collect();
        let deduped = produced.map_or(0, |(cache, _)| {
            cache.retain_absent(&mut urls, |url| url.key)
        });
        (Self::from_collected(urls, keys_bucket), deduped)
    }

    pub fn from_urls(namespace: Option<&str>, urls: Vec<(String, String, String)>) -> Option<Self> {
        Self::from_collected(
            urls.into_iter()
                .map(|(hash, url, domain)| CollectedUrl {
                    reference: url_reference(namespace, &hash),
                    url,
                    domain,
                    key: [0; 16],
                })
                .collect(),
            None,
        )
    }

    fn from_collected(entries: Vec<CollectedUrl>, keys_bucket: Option<u64>) -> Option<Self> {
        let first_ref = entries.first()?.reference.clone();
        Some(Self {
            first_ref,
            count: entries.len(),
            entries,
            keys_bucket,
            stage: Stage::Collected,
            published_keys: Vec::new(),
        })
    }

    pub fn count(&self) -> usize {
        self.count
    }

    pub fn first_ref(&self) -> &str {
        &self.first_ref
    }

    pub fn claim(&mut self, cache: &RefDedupCache, time_bucket: u64) -> Result<usize, OutOfOrder> {
        if self.stage != Stage::Collected {
            return Err(OutOfOrder("the URL batch was already claimed"));
        }
        self.stage = Stage::Claimed;
        if self.keys_bucket != Some(time_bucket) {
            for url in &mut self.entries {
                url.key = transport_url_key(&url.reference, &url.url, time_bucket);
            }
            self.keys_bucket = Some(time_bucket);
        }
        let keys: Vec<DedupKey> = self.entries.iter().map(|url| url.key).collect();
        let mut claimed = cache.claim(&keys).into_iter();
        self.entries.retain(|_| claimed.next().unwrap_or(false));
        Ok(self.entries.len())
    }

    pub fn unique_refs(&self) -> Vec<&str> {
        let mut seen = HashSet::new();
        self.entries
            .iter()
            .map(|url| url.reference.as_str())
            .filter(|reference| seen.insert(*reference))
            .collect()
    }

    /// An excluded entry stays marked in the cache, so that the next sighting skips it without
    /// another crawl-history read.
    pub fn build_records(
        &mut self,
        excluded_refs: &HashSet<String>,
        job: &JobTemplate,
        limits: RecordLimits,
    ) -> Result<UrlRecords, OutOfOrder> {
        if self.stage != Stage::Claimed {
            return Err(OutOfOrder(
                "the URL batch must be claimed once before its records are built",
            ));
        }
        self.stage = Stage::Built;
        let published: Vec<CollectedUrl> = std::mem::take(&mut self.entries)
            .into_iter()
            .filter(|url| !excluded_refs.contains(&url.reference))
            .collect();
        self.published_keys = published.iter().map(|url| url.key).collect();
        Ok(pack_records(&published, job, limits))
    }

    pub fn release(&mut self, cache: &RefDedupCache) {
        cache.release(&std::mem::take(&mut self.published_keys));
    }
}

fn pack_records(urls: &[CollectedUrl], job: &JobTemplate, limits: RecordLimits) -> UrlRecords {
    let mut group_of_domain: HashMap<&str, usize> = HashMap::new();
    let mut groups: Vec<(&str, Vec<&CollectedUrl>)> = Vec::new();
    for url in urls {
        let group = *group_of_domain
            .entry(url.domain.as_str())
            .or_insert_with(|| {
                groups.push((url.domain.as_str(), Vec::new()));
                groups.len() - 1
            });
        groups[group].1.push(url);
    }

    let mut records = Vec::new();
    let mut job_json = Vec::new();
    for (domain, group) in &groups {
        let mut packer = RecordPacker::new(domain, limits);
        for url in group {
            job_json.clear();
            job.write(&mut job_json, &url.reference, &url.url);
            packer.push(&job_json, &mut records);
        }
        packer.flush(&mut records);
    }
    UrlRecords {
        records,
        url_byte_lengths: urls
            .iter()
            .map(|url| u32::try_from(url.url.len()).unwrap_or(u32::MAX))
            .collect(),
        domain_count: groups.len(),
    }
}

/// An entry always goes into a record, even alone above the byte budget, because a drop here loses
/// an image every earlier check accepted. `MAX_URL_LEN` keeps that record under the broker limit.
struct RecordPacker<'a> {
    registrable_domain: &'a str,
    limits: RecordLimits,
    value: Vec<u8>,
    url_count: usize,
    tallied_bytes: usize,
}

impl<'a> RecordPacker<'a> {
    fn new(registrable_domain: &'a str, limits: RecordLimits) -> Self {
        Self {
            registrable_domain,
            limits,
            value: RECORD_HEAD.to_vec(),
            url_count: 0,
            tallied_bytes: RECORD_HEAD.len() + RECORD_TAIL.len(),
        }
    }

    fn push(&mut self, job_json: &[u8], records: &mut Vec<UrlRecord>) {
        // The size keeps its comma when this job opens a new record, so a new record's tally runs
        // one byte high. produce-collected-urls-step.test.ts pins the split points this gives.
        let size = job_json.len() + usize::from(self.url_count > 0);
        if self.url_count > 0
            && (self.tallied_bytes + size > self.limits.max_bytes
                || self.url_count >= self.limits.max_urls)
        {
            self.flush(records);
        }
        if self.url_count > 0 {
            self.value.push(b',');
        }
        self.value.extend_from_slice(job_json);
        self.url_count += 1;
        self.tallied_bytes += size;
    }

    fn flush(&mut self, records: &mut Vec<UrlRecord>) {
        if self.url_count == 0 {
            return;
        }
        let mut value = std::mem::replace(&mut self.value, RECORD_HEAD.to_vec());
        value.extend_from_slice(RECORD_TAIL);
        records.push(UrlRecord {
            registrable_domain: self.registrable_domain.to_string(),
            value,
            url_count: self.url_count,
        });
        self.url_count = 0;
        self.tallied_bytes = RECORD_HEAD.len() + RECORD_TAIL.len();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const LIMITS: RecordLimits = RecordLimits {
        max_bytes: 512 * 1024,
        max_urls: 1_000,
    };

    fn url(hash: &str, url: &str, domain: &str) -> (String, String, String) {
        (hash.to_string(), url.to_string(), domain.to_string())
    }

    fn claimed_batch(urls: Vec<(String, String, String)>) -> UrlBatch {
        let mut batch = UrlBatch::from_urls(Some("v3:42:2026-09"), urls).unwrap();
        batch.claim(&RefDedupCache::new(100), 1).unwrap();
        batch
    }

    #[test]
    fn writes_session_id_first_only_for_a_keyed_session() {
        let urls = || vec![url("h1", "https://a.example.com/x.png", "example.com")];
        let keyed = claimed_batch(urls())
            .build_records(&HashSet::new(), &JobTemplate::new(Some("s-1"), 7), LIMITS)
            .unwrap();
        let unkeyed = claimed_batch(urls())
            .build_records(&HashSet::new(), &JobTemplate::new(None, 7), LIMITS)
            .unwrap();

        let job = r#""originalRef":"imageurl:v3:42:2026-09:h1","currentUrl":"https://a.example.com/x.png","remainingHops":10,"notBeforeMs":0,"firstSeenAtMs":7,"fetchCount":0,"republishCount":0,"lastRepublishReason":null}"#;
        assert_eq!(
            String::from_utf8(keyed.records[0].value.clone()).unwrap(),
            format!(r#"{{"v":2,"jobs":[{{"sessionId":"s-1",{job}]}}"#)
        );
        assert_eq!(
            String::from_utf8(unkeyed.records[0].value.clone()).unwrap(),
            format!(r#"{{"v":2,"jobs":[{{{job}]}}"#)
        );
    }

    #[test]
    fn an_excluded_ref_stays_claimed_and_only_published_entries_are_released() {
        let cache = RefDedupCache::new(100);
        let urls = || {
            vec![
                url("fresh", "https://a.example.com/1.png", "example.com"),
                url("missing", "https://a.example.com/2.png", "example.com"),
            ]
        };
        let mut batch = UrlBatch::from_urls(None, urls()).unwrap();
        assert_eq!(batch.claim(&cache, 1), Ok(2));
        assert_eq!(
            batch.unique_refs(),
            vec!["imageurl:fresh", "imageurl:missing"]
        );
        let excluded = HashSet::from(["imageurl:fresh".to_string()]);
        let built = batch
            .build_records(&excluded, &JobTemplate::new(None, 7), LIMITS)
            .unwrap();
        assert_eq!(built.url_byte_lengths.len(), 1);

        batch.release(&cache);
        let mut again = UrlBatch::from_urls(None, urls()).unwrap();
        assert_eq!(again.claim(&cache, 1), Ok(1));
        assert_eq!(again.unique_refs(), vec!["imageurl:missing"]);
    }

    #[test]
    fn a_claim_in_a_later_time_bucket_marks_that_bucket() {
        let cache = RefDedupCache::new(100);
        let entries = || {
            vec![UrlEntry {
                hash: "h".to_string(),
                url: "https://a.example.com/x.png".to_string(),
                host: "a.example.com".to_string(),
                domain: "example.com".to_string(),
            }]
        };
        let (batch, _) = UrlBatch::collect(None, entries(), Some((&cache, 1)));
        assert_eq!(batch.unwrap().claim(&cache, 2), Ok(1));

        let (batch, deduped) = UrlBatch::collect(None, entries(), Some((&cache, 2)));
        assert!(batch.is_none());
        assert_eq!(deduped, 1);
    }

    #[test]
    fn refuses_to_build_before_a_claim_or_to_claim_twice() {
        let mut batch =
            UrlBatch::from_urls(None, vec![url("h", "https://a.example/", "a.example")]).unwrap();
        let job = JobTemplate::new(None, 7);
        assert!(batch.build_records(&HashSet::new(), &job, LIMITS).is_err());
        batch.claim(&RefDedupCache::new(10), 1).unwrap();
        assert!(batch.claim(&RefDedupCache::new(10), 1).is_err());
    }
}
