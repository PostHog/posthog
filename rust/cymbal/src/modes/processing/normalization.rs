//! Wire-order normalization for incoming exception payloads.
//!
//! Different PostHog SDKs historically disagreed on the order of two things:
//!
//! - `stacktrace.frames`: the canonical wire order is bottom-up, i.e.
//!   `frames[0]` is the entry point (e.g. `main`) and the last frame is the
//!   crash site. Some SDKs send crash-first (crash site first, entry point
//!   last) and need their frames reversed at ingest.
//! - `$exception_list`: the canonical wire order is caught/outermost exception
//!   first, root cause last. One SDK sends the list root-cause-first and needs
//!   the list reversed.
//!
//! The cross-SDK standardization effort (sdk-specs#11) is flipping SDKs to emit
//! the canonical order directly. Until an SDK ships that flip, cymbal
//! normalizes its payloads here, keyed on `$lib` and gated on `$lib_version`.
//!
//! To retire normalization for an SDK once it ships the canonical order, set
//! that entry's cutoff to `Some(version)`: payloads at or above the cutoff are
//! left untouched, payloads below it (or with an unparseable version) are still
//! normalized. A `None` cutoff means the SDK has not flipped yet, so everything
//! is normalized.

use std::sync::OnceLock;

use semver::Version;

use crate::types::ExceptionList;

/// Which parts of a payload a given `$lib` needs reversed to reach canonical
/// wire order.
#[derive(Debug, Clone, Copy)]
struct WireOrderFix {
    /// Reverse each exception's `stacktrace.frames` (crash-first -> bottom-up).
    reverse_frames: bool,
    /// Reverse `$exception_list` (root-cause-first -> outermost-first).
    reverse_exception_list: bool,
}

impl WireOrderFix {
    const FRAMES: Self = Self {
        reverse_frames: true,
        reverse_exception_list: false,
    };
    const EXCEPTION_LIST: Self = Self {
        reverse_frames: false,
        reverse_exception_list: true,
    };
}

/// A single SDK's normalization rule.
struct LibRule {
    /// The `$lib` value this rule matches.
    lib: &'static str,
    /// What to reverse.
    fix: WireOrderFix,
    /// The version at which the SDK started emitting canonical order. `None`
    /// means it has not flipped yet, so always normalize. `Some(v)` means
    /// normalize only for versions strictly below `v`.
    canonical_since: Option<Version>,
}

/// The normalization table, keyed on `$lib`.
///
/// All cutoffs are `None` today: no SDK has shipped the canonical-order flip
/// yet. When an SDK ships it, change its `canonical_since` to the release
/// version and leave everything else alone — legacy payloads keep normalizing,
/// new payloads pass through.
///
/// Built lazily because `semver::Version` is not `const`-constructible; cached
/// for the process lifetime since this is consulted for every ingested event.
fn lib_rules() -> &'static [LibRule] {
    static RULES: OnceLock<Vec<LibRule>> = OnceLock::new();
    RULES.get_or_init(|| {
        // Crash-first frames: entry point last, crash site first on the wire.
        let crash_first_frames = [
            "posthog-android",
            "posthog-flutter",
            "posthog-php",
            "posthog-go",
            "posthog-rs",
            "posthog-elixir",
            // Java: `posthog-server` is the current java server SDK identifier
            // (module in the posthog-android repo, shares the android coercer);
            // `posthog-java` is the tombstoned legacy SDK, included defensively.
            // Both are crash-first.
            "posthog-java",
            "posthog-server",
        ];

        let mut rules: Vec<LibRule> = crash_first_frames
            .into_iter()
            .map(|lib| LibRule {
                lib,
                fix: WireOrderFix::FRAMES,
                canonical_since: None,
            })
            .collect();

        // Root-cause-first `$exception_list`: python sends chained exceptions with
        // the root cause first. Its frames are already canonical (bottom-up).
        rules.push(LibRule {
            lib: "posthog-python",
            fix: WireOrderFix::EXCEPTION_LIST,
            canonical_since: None,
        });

        rules
    })
}

/// Parses a `$lib_version` leniently. `semver` rejects things like a bare
/// `1.2` or a leading `v`, both of which SDKs emit, so we coerce common shapes
/// before parsing. An unparseable version is treated as "old" by the caller
/// (i.e. normalization still applies), so `None` here is a normalize signal.
fn parse_lenient(version: &str) -> Option<Version> {
    let trimmed = version.trim().trim_start_matches(['v', 'V']);
    if let Ok(v) = Version::parse(trimmed) {
        return Some(v);
    }

    // Split off any pre-release/build metadata, then pad the numeric core to
    // three components so `1` and `1.2` parse.
    let core = trimmed.split(['-', '+']).next().unwrap_or(trimmed);
    let mut parts: Vec<&str> = core.split('.').collect();
    if parts.is_empty() || parts.len() > 3 {
        return None;
    }
    while parts.len() < 3 {
        parts.push("0");
    }
    if parts
        .iter()
        .any(|p| p.is_empty() || !p.bytes().all(|b| b.is_ascii_digit()))
    {
        return None;
    }
    Version::parse(&parts.join(".")).ok()
}

/// Decides whether a payload from `lib_version` still needs normalizing, given
/// the version at which its SDK started emitting canonical order.
///
/// - `None` cutoff: the SDK has not flipped yet, so always normalize.
/// - `Some(cutoff)`: normalize only versions strictly below the cutoff. A
///   version at/above the cutoff is left alone; an unparseable version is
///   treated as old, so it still normalizes.
///
/// The cutoff path deliberately does no work for post-flip payloads. It does
/// not need to: a flipped SDK's canonical events fingerprint identically to the
/// pre-flip legacy events this normalizer already reorders. While the cutoff is
/// `None` (the normalization window), those legacy events are aliased so the
/// canonical fingerprint already maps to the pre-flip issue, so the first
/// post-flip canonical event hits the fast `load_by_fingerprint` path and joins
/// the same issue with no split.
fn should_normalize(canonical_since: Option<&Version>, lib_version: Option<&str>) -> bool {
    let Some(cutoff) = canonical_since else {
        return true;
    };
    match lib_version.and_then(parse_lenient) {
        Some(v) => v < *cutoff,
        None => true,
    }
}

/// Returns the fix to apply for `lib`/`lib_version`, or `None` if the payload
/// already carries canonical order (or the SDK is unknown).
fn fix_for(lib: &str, lib_version: Option<&str>) -> Option<WireOrderFix> {
    let rule = lib_rules().iter().find(|r| r.lib == lib)?;
    should_normalize(rule.canonical_since.as_ref(), lib_version).then_some(rule.fix)
}

/// Normalizes `exception_list` to canonical wire order in place, keyed on
/// `$lib`/`$lib_version`. Returns the pre-normalization (legacy-order) list when
/// a reversal was applied, so the caller can compute the legacy fingerprint for
/// issue continuity, or `None` when nothing changed.
///
/// This must run before fingerprinting/resolution: fingerprints are computed
/// over stored frame/exception order, so normalizing here keeps grouping
/// consistent across SDKs.
///
/// Note on the no-in-app fingerprint fallback: when an exception has no in-app
/// frames, fingerprinting hashes `frames.first()`. After normalization that is
/// the entry frame rather than the crash site — but that is already how
/// natively-canonical SDKs (web, node, ...) fingerprint such stacks today, so
/// this brings crash-first SDKs into line rather than introducing new
/// divergence. Improving that fallback (e.g. keying on the crash-site frame) is
/// a cross-SDK fingerprinting change out of scope for wire-order normalization.
pub fn normalize_wire_order(
    exception_list: &mut ExceptionList,
    lib: Option<&str>,
    lib_version: Option<&str>,
) -> Option<ExceptionList> {
    let fix = fix_for(lib?, lib_version)?;

    // Snapshot only once we know a reversal is coming — the common (canonical)
    // path pays no clone.
    let legacy = exception_list.clone();
    apply_fix(exception_list, fix);
    Some(legacy)
}

fn apply_fix(exception_list: &mut ExceptionList, fix: WireOrderFix) {
    if fix.reverse_exception_list {
        exception_list.reverse();
    }

    if fix.reverse_frames {
        for exception in exception_list.iter_mut() {
            if let Some(stack) = exception.stack.as_mut() {
                match stack {
                    crate::types::Stacktrace::Raw { frames } => frames.reverse(),
                    crate::types::Stacktrace::Resolved { frames } => frames.reverse(),
                }
            }
        }
    }
}

/// Reconstructs `lib`'s legacy wire order from a canonical-order list,
/// regardless of `$lib_version` or cutoff — each fix is its own inverse, so
/// applying it to a canonical list recovers the pre-flip order.
///
/// This is how legacy fingerprint versions keep pre-normalization issues
/// addressable after an SDK ships the flip: the cutoff stops the reordering,
/// but must not stop legacy hashing. Reconstruction is exact except where
/// resolution reshaped the list (inline expansion, remapping) — those hashes
/// can only be reproduced from the pre-flip snapshot, which post-flip events
/// no longer carry.
pub fn legacy_wire_order(
    lib: Option<&str>,
    exception_list: &ExceptionList,
) -> Option<ExceptionList> {
    let lib = lib?;
    let rule = lib_rules().iter().find(|r| r.lib == lib)?;
    let mut legacy = exception_list.clone();
    apply_fix(&mut legacy, rule.fix);
    Some(legacy)
}

#[cfg(test)]
mod test {
    use super::*;
    use crate::frames::RawFrame;
    use crate::types::{Exception, Stacktrace};

    fn py_frame(function: &str) -> RawFrame {
        // Deserialize a minimal python frame so we don't have to hand-build the
        // full raw-frame struct; only the function name matters for ordering.
        let json = serde_json::json!({
            "platform": "python",
            "function": function,
            "filename": "app.py",
            "in_app": true,
        });
        serde_json::from_value(json).expect("valid python frame")
    }

    fn frame_names(exception: &Exception) -> Vec<String> {
        match exception.stack.as_ref().unwrap() {
            Stacktrace::Raw { frames } => frames
                .iter()
                .map(|f| match f {
                    RawFrame::Python(p) => p.function.clone(),
                    _ => panic!("expected python frame"),
                })
                .collect(),
            _ => panic!("expected raw stacktrace"),
        }
    }

    fn exception_with_frames(exc_type: &str, functions: &[&str]) -> Exception {
        Exception {
            exception_id: None,
            exception_type: exc_type.to_string(),
            exception_message: String::new(),
            mechanism: None,
            module: None,
            thread_id: None,
            stack: Some(Stacktrace::Raw {
                frames: functions.iter().map(|f| py_frame(f)).collect(),
            }),
        }
    }

    #[test]
    fn legacy_wire_order_reconstructs_pre_flip_order() {
        // Frames: reconstruction re-applies the reversal, independent of
        // `$lib_version` — this is what keeps legacy fingerprint versions
        // computable after an SDK ships the flip and its cutoff is set.
        let canonical: ExceptionList =
            vec![exception_with_frames("Boom", &["main", "boom"])].into();
        let legacy = legacy_wire_order(Some("posthog-go"), &canonical).expect("go is in the table");
        assert_eq!(frame_names(&legacy[0]), vec!["boom", "main"]);

        // Exception list: python's fix reverses the list, not the frames.
        let canonical: ExceptionList = vec![
            exception_with_frames("Outer", &["main", "wrap"]),
            exception_with_frames("RootCause", &["main", "boom"]),
        ]
        .into();
        let legacy =
            legacy_wire_order(Some("posthog-python"), &canonical).expect("python is in the table");
        assert_eq!(legacy[0].exception_type, "RootCause");
        assert_eq!(frame_names(&legacy[0]), vec!["main", "boom"]);

        // Natively-canonical SDKs have no legacy order.
        assert!(legacy_wire_order(Some("posthog-node"), &canonical).is_none());
        assert!(legacy_wire_order(None, &canonical).is_none());
    }

    #[test]
    fn java_server_libs_both_normalize() {
        // Java server SDK sends crash-first frames under both the current
        // (`posthog-server`) and legacy tombstoned (`posthog-java`) identifiers.
        for lib in ["posthog-java", "posthog-server"] {
            let mut list: ExceptionList =
                vec![exception_with_frames("Boom", &["main", "boom"])].into();
            let legacy = normalize_wire_order(&mut list, Some(lib), Some("1.0.0"));
            assert!(legacy.is_some(), "{lib} should normalize");
            assert_eq!(frame_names(&list[0]), vec!["boom", "main"]);
        }
    }

    #[test]
    fn crash_first_lib_reverses_frames_only() {
        // posthog-go sends crash-first frames; the list order is left alone.
        let mut list: ExceptionList = vec![
            exception_with_frames("Outer", &["main", "handler", "boom"]),
            exception_with_frames("Inner", &["a", "b"]),
        ]
        .into();

        let legacy = normalize_wire_order(&mut list, Some("posthog-go"), Some("1.2.3"));

        assert!(legacy.is_some());
        assert_eq!(frame_names(&list[0]), vec!["boom", "handler", "main"]);
        assert_eq!(frame_names(&list[1]), vec!["b", "a"]);
        // List order unchanged.
        assert_eq!(list[0].exception_type, "Outer");
        assert_eq!(list[1].exception_type, "Inner");
        // The returned legacy snapshot preserves the original (pre-reversal) order.
        let legacy = legacy.unwrap();
        assert_eq!(frame_names(&legacy[0]), vec!["main", "handler", "boom"]);
    }

    #[test]
    fn python_reverses_exception_list_only() {
        // posthog-python sends the list root-cause-first; frames stay put.
        let mut list: ExceptionList = vec![
            exception_with_frames("RootCause", &["main", "boom"]),
            exception_with_frames("Wrapper", &["main", "wrap"]),
        ]
        .into();

        let legacy = normalize_wire_order(&mut list, Some("posthog-python"), Some("3.0.0"));

        assert!(legacy.is_some());
        // List reversed: outermost (Wrapper) now first.
        assert_eq!(list[0].exception_type, "Wrapper");
        assert_eq!(list[1].exception_type, "RootCause");
        // Frames unchanged.
        assert_eq!(frame_names(&list[0]), vec!["main", "wrap"]);
    }

    #[test]
    fn canonical_lib_is_untouched() {
        // web already sends canonical order; nothing should change.
        let mut list: ExceptionList =
            vec![exception_with_frames("Error", &["main", "boom"])].into();

        let legacy = normalize_wire_order(&mut list, Some("web"), Some("1.170.1"));

        assert!(legacy.is_none());
        assert_eq!(frame_names(&list[0]), vec!["main", "boom"]);
    }

    #[test]
    fn unknown_lib_is_untouched() {
        let mut list: ExceptionList =
            vec![exception_with_frames("Error", &["main", "boom"])].into();
        assert!(normalize_wire_order(&mut list, Some("posthog-martian"), None).is_none());
        assert_eq!(frame_names(&list[0]), vec!["main", "boom"]);
    }

    #[test]
    fn missing_lib_is_untouched() {
        let mut list: ExceptionList =
            vec![exception_with_frames("Error", &["main", "boom"])].into();
        assert!(normalize_wire_order(&mut list, None, Some("1.0.0")).is_none());
        assert_eq!(frame_names(&list[0]), vec!["main", "boom"]);
    }

    #[test]
    fn version_cutoff_skips_new_and_normalizes_old() {
        // Exercise the version gate directly (the shipped table is all-`None`
        // today, so no live rule has a cutoff yet).
        let cutoff = Version::parse("2.0.0").unwrap();
        let since = Some(&cutoff);

        // At/above cutoff: canonical order already, don't normalize.
        assert!(!should_normalize(since, Some("2.0.0")));
        assert!(!should_normalize(since, Some("2.5.1")));
        // Below cutoff: still legacy order, normalize.
        assert!(should_normalize(since, Some("1.9.9")));
        // Unparseable or missing version -> treat as old -> normalize.
        assert!(should_normalize(since, Some("not-a-version")));
        assert!(should_normalize(since, None));
        // No cutoff -> SDK hasn't flipped -> always normalize.
        assert!(should_normalize(None, Some("99.0.0")));
    }

    #[test]
    fn normalized_crash_first_matches_native_canonical_fingerprint() {
        use crate::fingerprinting::Fingerprint;
        use crate::frames::Frame;
        use common_types::error_tracking::FrameId;

        let resolved = |name: &str| Frame {
            frame_id: FrameId::new(String::new(), 1, 0),
            mangled_name: name.to_string(),
            line: Some(1),
            column: None,
            source: Some(format!("{name}.rs")),
            in_app: true,
            resolved_name: Some(name.to_string()),
            lang: "rust".to_string(),
            resolved: true,
            resolve_failure: None,
            synthetic: false,
            suspicious: false,
            junk_drawer: None,
            code_variables: None,
            context: None,
            release: None,
            module: None,
        };

        let exception = |frames: Vec<Frame>| Exception {
            exception_id: None,
            exception_type: "Boom".to_string(),
            exception_message: "boom".to_string(),
            mechanism: None,
            module: None,
            thread_id: None,
            stack: Some(Stacktrace::Resolved { frames }),
        };

        // A crash-first SDK sends [crash, mid, entry]; a canonical SDK sends the
        // reverse. After normalization the crash-first payload must fingerprint
        // identically to the canonical one, so both group into one issue.
        let canonical: ExceptionList = vec![exception(vec![
            resolved("entry"),
            resolved("mid"),
            resolved("crash"),
        ])]
        .into();
        let mut crash_first: ExceptionList = vec![exception(vec![
            resolved("crash"),
            resolved("mid"),
            resolved("entry"),
        ])]
        .into();

        let canonical_fp = Fingerprint::from_exception_list(&canonical).value;
        let pre_norm_fp = Fingerprint::from_exception_list(&crash_first).value;
        assert_ne!(
            canonical_fp, pre_norm_fp,
            "crash-first order should fingerprint differently before normalization"
        );

        assert!(normalize_wire_order(&mut crash_first, Some("posthog-rs"), None).is_some());
        let post_norm_fp = Fingerprint::from_exception_list(&crash_first).value;
        assert_eq!(
            canonical_fp, post_norm_fp,
            "normalized crash-first order should match canonical fingerprint"
        );
    }

    #[test]
    fn lenient_version_parsing() {
        assert_eq!(
            parse_lenient("1.2.3"),
            Some(Version::parse("1.2.3").unwrap())
        );
        assert_eq!(parse_lenient("1.2"), Some(Version::parse("1.2.0").unwrap()));
        assert_eq!(parse_lenient("1"), Some(Version::parse("1.0.0").unwrap()));
        assert_eq!(
            parse_lenient("v1.2.3"),
            Some(Version::parse("1.2.3").unwrap())
        );
        assert_eq!(
            parse_lenient("1.2.3-beta.1"),
            Some(Version::parse("1.2.3-beta.1").unwrap())
        );
        assert_eq!(parse_lenient("garbage"), None);
        assert_eq!(parse_lenient(""), None);
    }
}
