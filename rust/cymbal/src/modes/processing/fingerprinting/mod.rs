use std::borrow::Cow;
use std::sync::OnceLock;

use crate::frames::Frame;
use crate::modes::processing::rules::grouping::GroupingRule;
use crate::types::{Exception, ExceptionList, Stacktrace};
use regex::Regex;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};
use uuid::Uuid;

// We put a vec of these on the event as a record of what actually went into a fingerprint.
// This data is user-facing/used in the frontend, so make changes with caution
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case", tag = "type")]
pub enum FingerprintRecordPart {
    Frame {
        raw_id: String,
        pieces: Vec<String>,
    },
    Exception {
        id: Option<String>,
        pieces: Vec<String>,
    },
    Custom {
        rule_id: Uuid,
    },
    Manual,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Fingerprint {
    pub value: String,
    pub record: Vec<FingerprintRecordPart>,
}

#[derive(Debug, Clone, Default)]
pub struct FingerprintBuilder {
    pub record: Vec<FingerprintRecordPart>,
    pub hasher: Sha512,
}

impl FingerprintBuilder {
    pub fn update(&mut self, data: impl AsRef<[u8]>) {
        self.hasher.update(data);
    }

    pub fn add_part(&mut self, part: impl Into<FingerprintRecordPart>) {
        self.record.push(part.into());
    }

    pub fn finalize(self) -> Fingerprint {
        let result = self.hasher.finalize();
        let content = format!("{result:x}");
        Fingerprint {
            value: content,
            record: self.record,
        }
    }
}

impl Fingerprint {
    pub fn from_rule(rule: GroupingRule) -> Self {
        let content = format!("custom-rule:{}", rule.id);
        Fingerprint {
            value: content,
            record: vec![FingerprintRecordPart::Custom { rule_id: rule.id }],
        }
    }

    pub fn from_exception_list(exception_list: &ExceptionList) -> Fingerprint {
        FingerprintVersion::V1
            .strategy()
            .from_exception_list(exception_list)
    }
}

// Versions of the automatic fingerprint algorithm. The grouping stage computes every
// registered version for each event, keeps the newest version already used by an existing issue,
// and falls back to the newest version for new issues. Adding a version = one variant + one arm
// in `strategy()` + appending to `all()`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FingerprintVersion {
    // Legacy-order twins of V1/V2: the same strategies computed over the pre-flip wire order
    // of SDKs whose ordering the pipeline normalizes (see `normalization::legacy_wire_order`).
    // They exist so issues keyed before wire-order normalization stay addressable; being
    // non-newest, they can never create issues — they only match existing ones. Delete them
    // once legacy-keyed traffic decays (watch `$exception_fingerprint_version`).
    V1Legacy,
    V2Legacy,
    // The historical algorithm — bit-for-bit (guarded by tests/fingerprint_golden.rs).
    V1,
    // Normalizing strategy: hashes all frames of every chain entry, drops unresolved
    // line/column, and normalizes volatile path and message tokens. Selected by an offline
    // research loop: pairwise F1 0.40 vs 0.26 for V1 on a held-out LLM-labeled pair dataset.
    V2,
}

impl FingerprintVersion {
    // All registered versions, ascending. Order is meaningful: selection keeps the newest
    // already-used fingerprint, and new issues are created under the last (newest) entry.
    pub fn all() -> &'static [FingerprintVersion] {
        &[
            FingerprintVersion::V1Legacy,
            FingerprintVersion::V2Legacy,
            FingerprintVersion::V1,
            FingerprintVersion::V2,
        ]
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            FingerprintVersion::V1Legacy => "v1_legacy",
            FingerprintVersion::V2Legacy => "v2_legacy",
            FingerprintVersion::V1 => "v1",
            FingerprintVersion::V2 => "v2",
        }
    }

    // Legacy versions hash the reconstructed pre-flip order instead of the canonical list;
    // the grouping stage supplies the right list per version.
    pub fn is_legacy(&self) -> bool {
        matches!(
            self,
            FingerprintVersion::V1Legacy | FingerprintVersion::V2Legacy
        )
    }

    pub fn compute(&self, exception_list: &ExceptionList) -> Fingerprint {
        self.strategy().from_exception_list(exception_list)
    }

    pub fn strategy(&self) -> FingerprintStrategy {
        match self {
            FingerprintVersion::V1 | FingerprintVersion::V1Legacy => FingerprintStrategy::default(),
            FingerprintVersion::V2 | FingerprintVersion::V2Legacy => FingerprintStrategy {
                frame_selection: FrameSelection::AllFrames,
                // `Last` scores better offline (holdout F1 0.55 vs 0.40) but SDKs disagree on
                // chain order — current SDKs put the root cause last, the legacy python SDK put
                // it first — so keying on one end regroups differently per SDK version. Stays
                // `All` until ordering is normalized across SDKs.
                chain_selection: ChainSelection::All,
                unresolved_include_line: false,
                unresolved_include_column: false,
                normalize: Normalization {
                    strip_query_strings: true,
                    strip_hashed_chunks: true,
                    basename_only: true,
                },
                message_normalize: MessageNormalization {
                    mask_quoted: true,
                    mask_hex_ids: true,
                    mask_numbers: true,
                    truncate: Some(200),
                },
            },
        }
    }
}

// Which frames of a resolved stack feed the fingerprint.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub enum FrameSelection {
    // V1 behavior: in-app frames, restricted to resolved ones when any frame resolved; when no
    // frame is in-app, only the first frame.
    #[default]
    InAppResolvedElseAll,
    // Every frame — stable when the in_app flag flips between captures of the same stack.
    AllFrames,
}

// Which exceptions of a chained list feed the hash. Wrapper exceptions (retry shims, error
// boundaries) vary while the underlying exception is stable; `Last` keys on the final chain
// entry only. (SDKs disagree on chain order — python sends root-cause-first, most others
// outermost-first — so `Last` means "root cause" for JS-style chains and "outermost wrapper"
// for python; both empirically group better than hashing the whole chain.)
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub enum ChainSelection {
    #[default]
    All,
    Last,
}

// String normalization applied to frame source/module before hashing: removes bytes that vary
// per deploy/device/build but not per bug. The all-off default (V1) is a byte-identity.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Normalization {
    // "app.js?v=abc123" -> "app.js"
    pub strip_query_strings: bool,
    // "chunk-PGUQKT6S.js" -> "chunk-*.js" — masks content-hashed build artifact names
    pub strip_hashed_chunks: bool,
    // "/var/mobile/.../<device-uuid>/bundle.js" -> "bundle.js"
    pub basename_only: bool,
}

static HASHED_CHUNK_TOKEN: OnceLock<Regex> = OnceLock::new();

impl Normalization {
    fn is_noop(&self) -> bool {
        !(self.strip_query_strings || self.strip_hashed_chunks || self.basename_only)
    }

    fn apply_source<'a>(&self, value: &'a str) -> Cow<'a, str> {
        if self.is_noop() {
            return Cow::Borrowed(value);
        }
        let mut out = value.to_string();
        if self.strip_query_strings {
            if let Some(idx) = out.find('?') {
                out.truncate(idx);
            }
        }
        if self.basename_only {
            if let Some(idx) = out.rfind(['/', '\\']) {
                out.drain(..=idx);
            }
        }
        if self.strip_hashed_chunks {
            // Build hashes are long alphanumeric runs containing at least one digit (the digit
            // constraint lives in the replacer because the regex crate has no lookahead).
            let re = HASHED_CHUNK_TOKEN
                .get_or_init(|| Regex::new(r"[A-Za-z0-9]{8,}").expect("valid regex"));
            out = re
                .replace_all(&out, |caps: &regex::Captures| {
                    let token = &caps[0];
                    if token.chars().any(|c| c.is_ascii_digit()) {
                        "*".to_string()
                    } else {
                        token.to_string()
                    }
                })
                .into_owned();
        }
        Cow::Owned(out)
    }

    fn apply_module<'a>(&self, value: &'a str) -> Cow<'a, str> {
        // Module names are logical identifiers, not build artifact paths. Keep dotted package
        // context and avoid chunk-hash masking so names like `sqlalchemy2.orm` don't collapse
        // into `*.orm`.
        if self.is_noop() || !self.strip_query_strings {
            return Cow::Borrowed(value);
        }

        let Some(idx) = value.find('?') else {
            return Cow::Borrowed(value);
        };
        Cow::Owned(value[..idx].to_string())
    }
}

// Masks dynamic tokens in the exception message before hashing, so interpolated values
// (ids, counts, durations) don't fork issues. The all-off default (V1) is a byte-identity.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct MessageNormalization {
    // '...' and "..." contents -> '*' (user input, entity names)
    pub mask_quoted: bool,
    // 0x…, UUIDs, and bare hex runs >= 16 chars -> '*' (addresses, ids, hashes)
    pub mask_hex_ids: bool,
    // digit runs (incl. decimals) -> '#' (counts, ports, durations, errnos)
    pub mask_numbers: bool,
    // keep only the first N chars (huge payloads embedded in messages)
    pub truncate: Option<usize>,
}

static QUOTED_TOKEN: OnceLock<Regex> = OnceLock::new();
static HEX_ID_TOKEN: OnceLock<Regex> = OnceLock::new();
static NUMBER_TOKEN: OnceLock<Regex> = OnceLock::new();

impl MessageNormalization {
    fn is_noop(&self) -> bool {
        !(self.mask_quoted || self.mask_hex_ids || self.mask_numbers) && self.truncate.is_none()
    }

    fn apply<'a>(&self, value: &'a str) -> Cow<'a, str> {
        if self.is_noop() {
            return Cow::Borrowed(value);
        }
        let mut out = value.to_string();
        if self.mask_quoted {
            let re =
                QUOTED_TOKEN.get_or_init(|| Regex::new(r#"'[^']*'|"[^"]*""#).expect("valid regex"));
            out = re.replace_all(&out, "'*'").into_owned();
        }
        if self.mask_hex_ids {
            // UUIDs before bare numbers: they contain both hyphens and digits.
            let re = HEX_ID_TOKEN.get_or_init(|| {
                Regex::new(
                    r"0x[0-9a-fA-F]+|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|[0-9a-fA-F]{16,}",
                )
                .expect("valid regex")
            });
            out = re.replace_all(&out, "*").into_owned();
        }
        if self.mask_numbers {
            let re = NUMBER_TOKEN.get_or_init(|| Regex::new(r"\d+(\.\d+)?").expect("valid regex"));
            out = re.replace_all(&out, "#").into_owned();
        }
        if let Some(n) = self.truncate {
            if let Some((idx, _)) = out.char_indices().nth(n) {
                out.truncate(idx);
            }
        }
        Cow::Owned(out)
    }
}

// A parameterized automatic fingerprint algorithm. `FingerprintStrategy::default()` IS the V1
// production algorithm — every knob's default reproduces the historical behavior bit-for-bit
// (guarded by tests/fingerprint_golden.rs). Named versions live in `FingerprintVersion`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FingerprintStrategy {
    pub frame_selection: FrameSelection,
    pub chain_selection: ChainSelection,
    // Unresolved frames hash line/column in V1 (no symbol to key on); library-version and
    // inline-script line drift forks issues, so V2 drops the positional pieces.
    pub unresolved_include_line: bool,
    pub unresolved_include_column: bool,
    pub normalize: Normalization,
    pub message_normalize: MessageNormalization,
}

impl Default for FingerprintStrategy {
    fn default() -> Self {
        Self {
            frame_selection: FrameSelection::default(),
            chain_selection: ChainSelection::default(),
            unresolved_include_line: true,
            unresolved_include_column: true,
            normalize: Normalization::default(),
            message_normalize: MessageNormalization::default(),
        }
    }
}

impl FingerprintStrategy {
    pub fn from_exception_list(&self, exception_list: &ExceptionList) -> Fingerprint {
        let mut fingerprint = FingerprintBuilder::default();

        let selected: Vec<&Exception> = match self.chain_selection {
            ChainSelection::All => exception_list.iter().collect(),
            ChainSelection::Last => exception_list.iter().last().into_iter().collect(),
        };
        for exc in selected {
            self.include_exception(exc, &mut fingerprint);
        }

        fingerprint.finalize()
    }

    fn include_exception(&self, exc: &Exception, fp: &mut FingerprintBuilder) {
        self.update_exception(exc, fp);

        let Some(Stacktrace::Resolved { frames }) = &exc.stack else {
            return;
        };

        for frame in self.select_frames(frames) {
            self.update_frame(frame, fp)
        }
    }

    fn update_exception(&self, exc: &Exception, fp: &mut FingerprintBuilder) {
        let mut pieces = vec![];
        fp.update(exc.exception_type.as_bytes());
        pieces.push("Exception Type".to_string());
        if !matches!(exc.stack, Some(Stacktrace::Resolved { frames: _ })) {
            fp.update(
                self.message_normalize
                    .apply(&exc.exception_message)
                    .as_bytes(),
            );
            pieces.push("Exception Message".to_string());
        };
        fp.add_part(FingerprintRecordPart::Exception {
            id: exc.exception_id.clone(),
            pieces,
        });
    }

    fn select_frames<'a>(&self, frames: &'a [Frame]) -> Vec<&'a Frame> {
        match self.frame_selection {
            FrameSelection::AllFrames => frames.iter().collect(),
            FrameSelection::InAppResolvedElseAll => {
                let has_no_resolved = !frames.iter().any(|f| f.resolved);
                let has_no_in_app = !frames.iter().any(|f| f.in_app);

                if has_no_in_app {
                    // TODO: we should try to be smarter about handling the case when
                    // there are no in-app frames
                    return frames.first().into_iter().collect();
                }

                frames
                    .iter()
                    .filter(|f| (has_no_resolved || f.resolved) && f.in_app)
                    .collect()
            }
        }
    }

    fn update_frame(&self, frame: &Frame, fp: &mut FingerprintBuilder) {
        let get_part = |s: &common_types::error_tracking::FrameId, p: Vec<&str>| {
            FingerprintRecordPart::Frame {
                raw_id: s.to_string(),
                pieces: p.into_iter().map(String::from).collect(),
            }
        };

        let mut included_pieces = Vec::new();

        // Include source and module in the fingerprint either way
        if let Some(source) = &frame.source {
            fp.update(self.normalize.apply_source(source).as_bytes());
            included_pieces.push("Source file name");
        }

        if let Some(module) = &frame.module {
            fp.update(self.normalize.apply_module(module).as_bytes());
            included_pieces.push("Module name");
        }

        // If we've resolved this frame, include function name, and then return
        if let Some(resolved) = &frame.resolved_name {
            fp.update(resolved.as_bytes());
            included_pieces.push("Resolved function name");

            fp.add_part(get_part(&frame.frame_id, included_pieces));
            return;
        }

        // Otherwise, get more granular
        fp.update(frame.mangled_name.as_bytes());
        included_pieces.push("Mangled function name");

        if self.unresolved_include_line {
            if let Some(line) = frame.line {
                fp.update(line.to_string().as_bytes());
                included_pieces.push("Line number");
            }
        }

        if self.unresolved_include_column {
            if let Some(column) = frame.column {
                fp.update(column.to_string().as_bytes());
                included_pieces.push("Column number");
            }
        }

        fp.update(frame.lang.as_bytes());
        included_pieces.push("Language");
        fp.add_part(get_part(&frame.frame_id, included_pieces));
    }
}

#[cfg(test)]
mod test {
    use crate::{
        frames::Frame,
        types::{Exception, Stacktrace},
    };
    use common_types::error_tracking::FrameId;

    use super::*;

    fn frame(
        mangled: &str,
        source: Option<&str>,
        resolved_name: Option<&str>,
        resolved: bool,
        in_app: bool,
        line: Option<u32>,
    ) -> Frame {
        Frame {
            frame_id: FrameId::new(String::new(), 1, 0),
            mangled_name: mangled.to_string(),
            line,
            column: line.map(|l| l + 1),
            source: source.map(String::from),
            in_app,
            resolved_name: resolved_name.map(String::from),
            resolved,
            resolve_failure: None,
            lang: "javascript".to_string(),
            junk_drawer: None,
            code_variables: None,
            context: None,
            release: None,
            synthetic: false,
            suspicious: false,
            module: None,
        }
    }

    fn exception(exc_type: &str, message: &str, stack: Option<Stacktrace>) -> Exception {
        Exception {
            exception_id: None,
            exception_type: exc_type.to_string(),
            exception_message: message.to_string(),
            mechanism: Default::default(),
            module: Default::default(),
            thread_id: None,
            stack,
        }
    }

    fn resolved_stack(frames: Vec<Frame>) -> Option<Stacktrace> {
        Some(Stacktrace::Resolved { frames })
    }

    fn value(version: FingerprintVersion, exceptions: Vec<Exception>) -> String {
        version
            .strategy()
            .from_exception_list(&exceptions.into())
            .value
    }

    // ---- V1 invariants (preserved from the original implementation) ----

    #[test]
    fn v1_ignores_unresolved_frames_when_some_resolved() {
        let resolved = vec![
            frame(
                "foo",
                Some("http://example.com/foo.js"),
                Some("bar"),
                true,
                true,
                Some(10),
            ),
            frame(
                "bar",
                Some("http://example.com/bar.js"),
                Some("baz"),
                true,
                true,
                Some(20),
            ),
        ];
        let mut with_unresolved = resolved.clone();
        with_unresolved.push(frame("xyz", None, None, false, true, Some(30)));

        let a = value(
            FingerprintVersion::V1,
            vec![exception("TypeError", "boom", resolved_stack(resolved))],
        );
        let b = value(
            FingerprintVersion::V1,
            vec![exception(
                "TypeError",
                "boom",
                resolved_stack(with_unresolved),
            )],
        );
        assert_eq!(a, b);
    }

    #[test]
    fn v1_uses_unresolved_frames_when_none_resolved() {
        let frames = vec![
            frame(
                "foo",
                Some("http://example.com/foo.js"),
                None,
                false,
                true,
                Some(10),
            ),
            frame("xyz", None, None, false, true, Some(30)),
        ];
        let no_stack = value(
            FingerprintVersion::V1,
            vec![exception("TypeError", "boom", None)],
        );
        let with_stack = value(
            FingerprintVersion::V1,
            vec![exception("TypeError", "boom", resolved_stack(frames))],
        );
        assert_ne!(no_stack, with_stack);
    }

    #[test]
    fn v1_ignores_non_in_app_frames() {
        let app_frame = frame(
            "foo",
            Some("http://example.com/foo.js"),
            Some("bar"),
            false,
            true,
            Some(10),
        );
        let vendor_frame = frame(
            "bar",
            Some("http://example.com/bar.js"),
            Some("baz"),
            false,
            false,
            Some(20),
        );

        let a = value(
            FingerprintVersion::V1,
            vec![exception(
                "TypeError",
                "boom",
                resolved_stack(vec![app_frame.clone()]),
            )],
        );
        let b = value(
            FingerprintVersion::V1,
            vec![exception(
                "TypeError",
                "boom",
                resolved_stack(vec![app_frame, vendor_frame]),
            )],
        );
        assert_eq!(a, b);
    }

    // ---- V1 vs V2 direction tests: one per differing knob ----

    #[test]
    fn v2_hashes_every_chain_entry() {
        // Chain selection is `All` until SDK chain ordering is normalized, so wrapper
        // variance still splits — but masked dynamic tokens in the wrapper do not.
        let chain = |wrapper_msg: &str| {
            vec![
                exception("WrapperError", wrapper_msg, None),
                exception("RootError", "root cause", None),
            ]
        };
        assert_ne!(
            value(FingerprintVersion::V2, chain("wrapped: attempt A")),
            value(FingerprintVersion::V2, chain("wrapped: attempt B")),
        );
        assert_eq!(
            value(FingerprintVersion::V2, chain("wrapped: attempt 12")),
            value(FingerprintVersion::V2, chain("wrapped: attempt 47")),
        );
    }

    #[test]
    fn v2_is_stable_when_in_app_flag_flips() {
        let stack = |in_app: bool| {
            resolved_stack(vec![
                frame("connect", Some("connection.py"), None, false, true, None),
                frame("retry", Some("retry.py"), None, false, in_app, None),
            ])
        };
        assert_ne!(
            value(
                FingerprintVersion::V1,
                vec![exception("Error", "boom", stack(true))]
            ),
            value(
                FingerprintVersion::V1,
                vec![exception("Error", "boom", stack(false))]
            ),
        );
        assert_eq!(
            value(
                FingerprintVersion::V2,
                vec![exception("Error", "boom", stack(true))]
            ),
            value(
                FingerprintVersion::V2,
                vec![exception("Error", "boom", stack(false))]
            ),
        );
    }

    #[test]
    fn v2_ignores_unresolved_line_drift() {
        let at_line = |line: u32| {
            resolved_stack(vec![frame(
                "connect",
                Some("connection.py"),
                None,
                false,
                true,
                Some(line),
            )])
        };
        assert_ne!(
            value(
                FingerprintVersion::V1,
                vec![exception("Error", "boom", at_line(378))]
            ),
            value(
                FingerprintVersion::V1,
                vec![exception("Error", "boom", at_line(698))]
            ),
        );
        assert_eq!(
            value(
                FingerprintVersion::V2,
                vec![exception("Error", "boom", at_line(378))]
            ),
            value(
                FingerprintVersion::V2,
                vec![exception("Error", "boom", at_line(698))]
            ),
        );
    }

    #[test]
    fn v2_normalizes_volatile_source_paths() {
        let cases = [
            (
                "http://x.com/app.js?v=abc123",
                "http://x.com/app.js?v=def456",
            ),
            ("chunk-PGUQKT6S.js", "chunk-Z9XW4B2Q.js"),
            (
                "/data/app/8CC63366-D88D/bundle.js",
                "/data/app/A4CD3A3C-8BE6/bundle.js",
            ),
        ];
        for (source_a, source_b) in cases {
            let with_source = |source: &str| {
                vec![exception(
                    "Error",
                    "boom",
                    resolved_stack(vec![frame(
                        "foo",
                        Some(source),
                        Some("foo"),
                        true,
                        true,
                        Some(1),
                    )]),
                )]
            };
            assert_ne!(
                value(FingerprintVersion::V1, with_source(source_a)),
                value(FingerprintVersion::V1, with_source(source_b)),
                "V1 should split {source_a} vs {source_b}"
            );
            assert_eq!(
                value(FingerprintVersion::V2, with_source(source_a)),
                value(FingerprintVersion::V2, with_source(source_b)),
                "V2 should merge {source_a} vs {source_b}"
            );
        }
    }

    #[test]
    fn v2_does_not_mask_dotted_module_names_as_chunks() {
        let with_module = |module: &str| {
            let mut frame = frame("execute", None, Some("execute"), true, true, Some(1));
            frame.module = Some(module.to_string());
            vec![exception("Error", "boom", resolved_stack(vec![frame]))]
        };

        assert_ne!(
            value(FingerprintVersion::V2, with_module("sqlalchemy2.orm")),
            value(FingerprintVersion::V2, with_module("customlib2.orm")),
        );
    }

    #[test]
    fn v2_masks_dynamic_message_tokens() {
        let cases = [
            (
                "timeout after 30s (attempt 2)",
                "timeout after 45.5s (attempt 7)",
            ),
            ("cannot read 'userName'", "cannot read 'accountId'"),
            (
                "session 8cc63366-d88d-41d6-9c39-5c0824fcc036 expired",
                "session a4cd3a3c-8be6-4f3f-93af-7e94d24e78bb expired",
            ),
        ];
        for (msg_a, msg_b) in cases {
            assert_ne!(
                value(
                    FingerprintVersion::V1,
                    vec![exception("Error", msg_a, None)]
                ),
                value(
                    FingerprintVersion::V1,
                    vec![exception("Error", msg_b, None)]
                ),
                "V1 should split {msg_a:?} vs {msg_b:?}"
            );
            assert_eq!(
                value(
                    FingerprintVersion::V2,
                    vec![exception("Error", msg_a, None)]
                ),
                value(
                    FingerprintVersion::V2,
                    vec![exception("Error", msg_b, None)]
                ),
                "V2 should merge {msg_a:?} vs {msg_b:?}"
            );
        }
    }

    #[test]
    fn versions_match_the_research_implementation() {
        // Cross-validation against the offline research harness (notebooks/ research project +
        // the fingerprint_sweep bin) that selected V2: both values below were produced by that
        // implementation for this exact fixture. If this test breaks, the algorithm diverged
        // from the evaluated one — don't update the constants without re-running the research
        // evaluation.
        let fixture = vec![Exception {
            exception_id: None,
            exception_type: "TypeError".to_string(),
            exception_message: "Cannot read property 'foo' of undefined".to_string(),
            mechanism: Default::default(),
            module: Default::default(),
            thread_id: None,
            stack: resolved_stack(vec![
                {
                    let mut first = frame(
                        "foo",
                        Some("http://example.com/alpha/foo.js"),
                        Some("bar"),
                        true,
                        true,
                        Some(10),
                    );
                    first.column = Some(5);
                    first
                },
                {
                    let mut second = frame(
                        "bar",
                        Some("http://example.com/bar.js"),
                        Some("baz"),
                        true,
                        true,
                        Some(20),
                    );
                    second.column = Some(15);
                    second.module = Some("app.module".to_string());
                    second
                },
            ]),
        }];
        assert_eq!(
            value(FingerprintVersion::V1, fixture.clone()),
            "d03a8ead4f42a8a315039e016979d6ded265ca61ebe08c5114b17626dc285f133e6a62b80d8122ff6b34198223f75bc4a682968b3608f97e9b341da4a1cc3dec"
        );
        assert_eq!(
            value(FingerprintVersion::V2, fixture),
            "444724bab3c0330331620497546290eff34b8cfe5363dcf938fc92ab80baff082a3616472e02ffadcb657cd7bdb211fbd9e1dcb04f2aae33e77c5c54e4835820"
        );
    }

    #[test]
    fn normalizations_are_identity_when_disabled() {
        let path = "chunk-PGUQKT6S.js?v=1";
        assert!(
            matches!(Normalization::default().apply_source(path), Cow::Borrowed(s) if s == path)
        );
        let msg = "timeout after 30s for 'user' at 0xdeadbeef";
        assert!(matches!(MessageNormalization::default().apply(msg), Cow::Borrowed(s) if s == msg));
    }
}
