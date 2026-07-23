//! Deferred image scrubbing: the walk swaps each image data URI for a token and queues the
//! decode+blur+encode on a small shared worker pool, so pixel work overlaps the rest of the walk.
//! Serialized output is patched wherever it becomes immutable — before each cv payload compresses,
//! and over the final block lines.
//!
//! Dedup is preserved: the job map is keyed on the original URI per message (the same role the
//! inline blur memo plays), so a recurring image submits one job and every occurrence patches to
//! the same result. Fail-safe matches the inline path: a failed or panicked job patches to the
//! occurrence's fallback (blank pixel or media placeholder), carried in the token.
//!
//! Tokens are plain base64-alphabet text (`xph<nonce><id><fallback>`), optionally wrapped as a
//! `data:image/png;base64,…` URI, so they survive JSON serialization byte-for-byte; the nonce is
//! random per process, so real payload bytes cannot collide with a live token.

use std::cell::{Cell, RefCell};
use std::collections::hash_map::RandomState;
use std::collections::HashMap;
use std::hash::{BuildHasher, Hasher};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::{mpsc, Arc, LazyLock, Mutex};
use std::time::Instant;

use crate::assets::PLACEHOLDER_SRC;
use crate::blur::{blur_image_data_uri, BLANK_PNG_BASE64};
use crate::timings::PhaseTimings;

/// How images found during the walk are scrubbed.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum ImagePolicy {
    /// Blur synchronously on the walk thread (the original behavior).
    #[default]
    Inline,
    /// Queue blurs on the shared worker pool and patch tokens into the serialized output.
    Parallel,
}

/// What a failed blur resolves to; chosen per occurrence, matching the inline call sites.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ImageFallback {
    /// Blank 1x1 PNG (inline images, canvas args, css).
    Blank,
    /// The media placeholder SVG (media `src`-style attributes).
    Placeholder,
}

const DATA_URI_PREFIX: &[u8] = b"data:image/png;base64,";
const ID_HEX_LEN: usize = 8;

/// Random per process: payload bytes can't be crafted to collide with a live token.
static NONCE: LazyLock<String> = LazyLock::new(|| {
    let mut h = RandomState::new().build_hasher();
    h.write_u32(std::process::id());
    format!("xph{:016x}", h.finish())
});

fn worker_count() -> usize {
    std::env::var("REPLAY_ANONYMIZER_IMAGE_THREADS")
        .ok()
        .and_then(|v| v.parse::<usize>().ok())
        .filter(|&n| n > 0)
        .unwrap_or_else(|| {
            std::thread::available_parallelism()
                .map(|n| n.get().min(4))
                .unwrap_or(2)
        })
}

struct Job {
    uri: String,
    result_tx: mpsc::SyncSender<JobResult>,
}

struct JobResult {
    /// PNG base64 (no `data:` prefix); `None` = the image could not be blurred.
    b64: Option<String>,
    elapsed_ns: u64,
}

/// One shared pool for the whole process: total blur parallelism stays bounded no matter how many
/// messages scrub concurrently on the libuv threadpool.
static POOL: LazyLock<mpsc::Sender<Job>> = LazyLock::new(|| {
    let (tx, rx) = mpsc::channel::<Job>();
    let rx = Arc::new(Mutex::new(rx));
    for i in 0..worker_count() {
        let rx = Arc::clone(&rx);
        std::thread::Builder::new()
            .name(format!("replay-img-scrub-{i}"))
            .spawn(move || loop {
                let job = match rx.lock() {
                    Ok(guard) => match guard.recv() {
                        Ok(job) => job,
                        Err(_) => break,
                    },
                    Err(_) => break,
                };
                let start = Instant::now();
                // A panic on a hostile image fails that one job closed, not the worker.
                let b64 = catch_unwind(AssertUnwindSafe(|| blur_image_data_uri(&job.uri)))
                    .unwrap_or(None)
                    .and_then(|uri| {
                        uri.strip_prefix("data:image/png;base64,")
                            .map(str::to_string)
                    });
                let elapsed_ns = u64::try_from(start.elapsed().as_nanos()).unwrap_or(u64::MAX - 1);
                // The queue side may already have given up on this job; a send error is fine.
                job.result_tx.send(JobResult { b64, elapsed_ns }).ok();
            })
            .expect("failed to spawn image scrub worker");
    }
    tx
});

enum JobState {
    Pending(mpsc::Receiver<JobResult>),
    /// Resolved blur output (PNG base64) plus the worker-side elapsed time, `0` once reported.
    Resolved(Option<String>),
}

/// Per-message queue: URI-keyed dedup plus id-keyed job states for the patch pass.
#[derive(Default)]
pub struct ImageQueue {
    ids_by_uri: RefCell<HashMap<String, u32>>,
    jobs: RefCell<HashMap<u32, JobState>>,
    next_id: Cell<u32>,
    /// Worker-side blur time and job count, accumulated as results are claimed.
    pub(crate) blur_ns: Cell<u64>,
    pub(crate) blur_count: Cell<u32>,
}

impl ImageQueue {
    /// Submits (or dedups) a blur job and returns the occurrence's token, `data:`-wrapped when the
    /// call site substitutes a full URI.
    pub(crate) fn submit(&self, uri: &str, fallback: ImageFallback, wrapped: bool) -> String {
        let known = self.ids_by_uri.borrow().get(uri).copied();
        let id = if let Some(id) = known {
            id
        } else {
            let id = self.next_id.get();
            self.next_id.set(id + 1);
            let (result_tx, result_rx) = mpsc::sync_channel(1);
            POOL.send(Job {
                uri: uri.to_string(),
                result_tx,
            })
            .expect("image scrub pool is gone");
            self.ids_by_uri.borrow_mut().insert(uri.to_string(), id);
            self.jobs
                .borrow_mut()
                .insert(id, JobState::Pending(result_rx));
            id
        };
        let fb = match fallback {
            ImageFallback::Blank => 'b',
            ImageFallback::Placeholder => 'p',
        };
        let core = format!("{}{id:08x}{fb}", &*NONCE);
        if wrapped {
            format!(
                "{}{core}",
                std::str::from_utf8(DATA_URI_PREFIX).expect("static prefix is utf-8")
            )
        } else {
            core
        }
    }

    /// Move blur time accumulated by claimed jobs into the timings sink (idempotent via reset).
    pub(crate) fn drain_blur_time_into(&self, timings: &PhaseTimings) {
        let (ns, count) = (self.blur_ns.replace(0), self.blur_count.replace(0));
        if count > 0 {
            timings.add_blur(ns, count);
        }
    }

    /// Whether any jobs were queued for this message (tokens may be present in output).
    pub(crate) fn has_pending(&self) -> bool {
        !self.jobs.borrow().is_empty()
    }

    /// Blocks until the job's result is in (the patch barrier); `None` = blur failed.
    fn resolve(&self, id: u32) -> Option<String> {
        let mut jobs = self.jobs.borrow_mut();
        let state = jobs.get_mut(&id)?;
        if let JobState::Pending(rx) = state {
            let result = match rx.recv() {
                Ok(r) => r,
                // The worker died before sending: fail this image closed.
                Err(_) => JobResult {
                    b64: None,
                    elapsed_ns: 0,
                },
            };
            self.blur_ns
                .set(self.blur_ns.get().saturating_add(result.elapsed_ns));
            self.blur_count.set(self.blur_count.get().saturating_add(1));
            *state = JobState::Resolved(result.b64);
        }
        match state {
            JobState::Resolved(b64) => b64.clone(),
            JobState::Pending(_) => unreachable!("state was just resolved"),
        }
    }

    /// Replaces every token in `buf` with its blur result (waiting for stragglers), returning the
    /// input untouched when nothing was queued or nothing matches. Call wherever serialized bytes
    /// become immutable: before a cv payload compresses, and on the final block lines.
    pub(crate) fn patch(&self, buf: Vec<u8>) -> Vec<u8> {
        if !self.has_pending() {
            return buf;
        }
        let needle = NONCE.as_bytes();
        let token_len = needle.len() + ID_HEX_LEN + 1;
        let mut out: Option<Vec<u8>> = None;
        let mut copied_to = 0usize;
        let mut search_from = 0usize;
        while let Some(rel) = memchr::memmem::find(&buf[search_from..], needle) {
            let start = search_from + rel;
            if start + token_len > buf.len() {
                break;
            }
            let Some(id) =
                parse_hex_id(&buf[start + needle.len()..start + needle.len() + ID_HEX_LEN])
            else {
                search_from = start + needle.len();
                continue;
            };
            let fallback = match buf[start + token_len - 1] {
                b'b' => ImageFallback::Blank,
                b'p' => ImageFallback::Placeholder,
                _ => {
                    search_from = start + needle.len();
                    continue;
                }
            };
            if !self.jobs.borrow().contains_key(&id) {
                // Nonce collision with real payload bytes; astronomically unlikely — leave as-is.
                search_from = start + needle.len();
                continue;
            }
            let wrapped = start >= DATA_URI_PREFIX.len()
                && &buf[start - DATA_URI_PREFIX.len()..start] == DATA_URI_PREFIX;
            let span_start = if wrapped {
                start - DATA_URI_PREFIX.len()
            } else {
                start
            };
            let span_end = start + token_len;
            let replacement: String = match (self.resolve(id), fallback) {
                (Some(b64), _) => {
                    if wrapped {
                        format!("data:image/png;base64,{b64}")
                    } else {
                        b64
                    }
                }
                (None, ImageFallback::Placeholder) => PLACEHOLDER_SRC.to_string(),
                (None, ImageFallback::Blank) => {
                    if wrapped {
                        format!("data:image/png;base64,{BLANK_PNG_BASE64}")
                    } else {
                        BLANK_PNG_BASE64.to_string()
                    }
                }
            };
            let out = out.get_or_insert_with(|| Vec::with_capacity(buf.len()));
            out.extend_from_slice(&buf[copied_to..span_start]);
            out.extend_from_slice(replacement.as_bytes());
            copied_to = span_end;
            search_from = span_end;
        }
        match out {
            Some(mut out) => {
                out.extend_from_slice(&buf[copied_to..]);
                out
            }
            None => buf,
        }
    }
}

fn parse_hex_id(bytes: &[u8]) -> Option<u32> {
    let s = std::str::from_utf8(bytes).ok()?;
    u32::from_str_radix(s, 16).ok()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testkit::png_data_uri;

    #[test]
    fn submit_dedups_by_uri_and_patch_replaces_every_occurrence() {
        let q = ImageQueue::default();
        let uri = png_data_uri(64, 32, [10, 20, 30, 255]);
        let t1 = q.submit(&uri, ImageFallback::Blank, true);
        let t2 = q.submit(&uri, ImageFallback::Blank, true);
        assert_eq!(t1, t2);
        assert_eq!(q.next_id.get(), 1);

        let raw = q.submit(&uri, ImageFallback::Blank, false);
        assert!(t1.ends_with(&raw));

        let buf = format!("{{\"a\":\"{t1}\",\"b\":\"{t2}\",\"c\":\"{raw}\"}}").into_bytes();
        let patched = String::from_utf8(q.patch(buf)).unwrap();
        let expected = blur_image_data_uri(&uri).unwrap();
        let expected_b64 = expected.strip_prefix("data:image/png;base64,").unwrap();
        assert_eq!(
            patched,
            format!("{{\"a\":\"{expected}\",\"b\":\"{expected}\",\"c\":\"{expected_b64}\"}}")
        );
        assert_eq!(q.blur_count.get(), 1);
        assert!(q.blur_ns.get() > 0);
    }

    #[test]
    fn failed_blur_patches_to_the_occurrence_fallback() {
        let q = ImageQueue::default();
        let bad = "data:image/png;base64,bm90IGFuIGltYWdl";
        let wrapped = q.submit(bad, ImageFallback::Blank, true);
        let placeholder = q.submit(bad, ImageFallback::Placeholder, true);
        let raw = q.submit(bad, ImageFallback::Blank, false);

        let buf = format!("[\"{wrapped}\",\"{placeholder}\",\"{raw}\"]").into_bytes();
        let patched = String::from_utf8(q.patch(buf)).unwrap();
        assert_eq!(
            patched,
            format!("[\"data:image/png;base64,{BLANK_PNG_BASE64}\",\"{PLACEHOLDER_SRC}\",\"{BLANK_PNG_BASE64}\"]")
        );
        assert_eq!(q.blur_count.get(), 1);
    }

    #[test]
    fn patch_is_a_no_op_without_queued_jobs() {
        let q = ImageQueue::default();
        let buf = b"{\"text\":\"no tokens here\"}".to_vec();
        assert_eq!(q.patch(buf.clone()), buf);
    }
}
