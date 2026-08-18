use std::sync::Arc;

use common_types::error_tracking::FrameId;
use proguard::StackFrame;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};
use tracing::warn;

use crate::{
    error::{FrameError, ProguardError, ResolveError, UnhandledError},
    frames::{record_frame_resolution_failure, Frame},
    langs::{utils::add_raw_to_junk, CommonFrameMetadata},
    symbolication::symbol_store::{
        chunk_id::OrChunkId,
        proguard::{FetchedMapping, ProguardRef},
        SymbolCatalog,
    },
};

// Namespace tag for the frame id construction below. It sits outside the digest on purpose:
// every other language's encoder emits a bare digest over a concatenation of fields the
// client controls, so any of them can be handed values that reproduce this construction's
// byte stream exactly. A tag inside the hash input would be part of what they can
// reproduce; a tag on the key itself is not. Changing the construction means bumping this.
const FRAME_ID_VERSION: &str = "java-v2";

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RawJavaFrame {
    pub filename: Option<String>, // The relative path of the file the context line is in
    pub function: String,         // The name of the function the exception came from
    pub lineno: Option<usize>,    // The line number of the context line
    pub module: String,           // The java-import style module name the function is in
    pub map_id: Option<String>, // ID of the proguard mapping symbol set this frame can be demangled with
    #[serde(default)]
    // Java compilers sometimes generate synthetic methods, for stuff like implied accessors from the source
    // More info at https://docs.oracle.com/javase/specs/jvms/se7/html/jvms-4.html#jvms-4.7.8
    //
    // TODO - we've used "synthetic" to mean "constructed by our SDK". This is a language-specific
    // meaning, and I'm not sure how to use it in our app. I'm also not /sure/ it matters, though.
    pub method_synthetic: bool,
    #[serde(flatten)]
    pub meta: CommonFrameMetadata,
}

// Feed a variable-length value with its length in front, so the hash sees where the value
// ends. Concatenating raw would let bytes move across a field boundary without changing the
// digest.
fn update_len_prefixed(hasher: &mut Sha512, value: &[u8]) {
    hasher.update((value.len() as u64).to_be_bytes());
    hasher.update(value);
}

// An absent value is one byte apart from a present empty one, which a length prefix alone
// would fold together.
fn update_optional(hasher: &mut Sha512, value: Option<&str>) {
    match value {
        Some(value) => {
            hasher.update([1u8]);
            update_len_prefixed(hasher, value.as_bytes());
        }
        None => hasher.update([0u8]),
    }
}

impl RawJavaFrame {
    pub fn frame_id(&self) -> String {
        // We don't have version info for java frames, so we rely on
        // the module, function and line number to
        // uniquely identify a frame, with the intuition being that even
        // if two frames are from two different library versions, if the
        // files they're in are sufficiently similar we can consider
        // them to be the same frame
        //
        // This id is the cache key for stored frame results, so two frames whose fields
        // differ must never encode to the same bytes. Every variable-length field is
        // length-prefixed and every optional one carries a presence byte: a flat
        // concatenation let module "a1.d" with map_id "release" hash identically to module
        // "a1.drelease" with no map_id. Project tokens ship inside client apps, so whoever
        // submits a crafted colliding frame first decides which record the other shape
        // reads. `filename: None` is therefore distinct from `Some("")`, and an absent
        // `lineno` from `Some(0)`: nothing rejects a zero line on the way in, and the two
        // resolve to frames with different `line` values.
        //
        // The mapping reference has to participate at all because a pass-through frame is
        // saved as resolved, with no linked symbol set and the longer resolved TTL, so if it
        // shared an id with the same source location captured *with* a map_id, that cached
        // record would be served to the obfuscated frame and suppress its proguard remap,
        // and a later mapping upload would not invalidate it. Proguard can renumber lines
        // even for classes it keeps, so matching file/function/line/module across the two
        // shapes is reachable.
        //
        // The tag on the front of the key gives this construction its own keyspace. Without
        // it the key is a bare digest, which leaves two ways for records of different shapes
        // to alias: a rolling deploy has old and new instances reading each other's java
        // records, and the encoders for the other languages, which hash flat concatenations
        // of client-controlled strings, can be fed values that land on a java key. It retires
        // every stored java id once and they re-resolve on next sight, which the ~30 minute
        // TTL makes cheap. Fingerprints are unaffected: this id only appears as `raw_id` in
        // the fingerprint record, never in the hash itself.
        let mut hasher = Sha512::new();
        update_optional(&mut hasher, self.filename.as_deref());
        update_len_prefixed(&mut hasher, self.function.as_bytes());
        // Fixed to u64 rather than usize, so the key does not depend on the pointer width of
        // the instance that wrote it.
        match self.lineno {
            Some(lineno) => {
                hasher.update([1u8]);
                hasher.update((lineno as u64).to_be_bytes());
            }
            None => hasher.update([0u8]),
        }
        update_len_prefixed(&mut hasher, self.module.as_bytes());
        update_optional(&mut hasher, self.map_id.as_deref());
        format!("{FRAME_ID_VERSION}:{:x}", hasher.finalize())
    }

    pub async fn resolve_frame<C>(
        &self,
        team_id: i32,
        catalog: &C,
    ) -> Result<Vec<Frame>, UnhandledError>
    where
        C: SymbolCatalog<OrChunkId<ProguardRef>, FetchedMapping>,
    {
        match self.resolve_impl(team_id, catalog).await {
            Ok(frames) => Ok(frames),
            Err(ResolveError::ResolutionError(FrameError::Proguard(e))) => {
                Ok(vec![self.handle_resolution_error(e)])
            }
            Err(ResolveError::ResolutionError(FrameError::MissingChunkIdData(chunk_id))) => Ok(
                vec![self.handle_resolution_error(ProguardError::MissingMap(chunk_id))],
            ),
            Err(ResolveError::ResolutionError(e)) => {
                warn!(
                    team_id,
                    "Unexpected Proguard symbol resolution error: {:?}", e
                );
                Ok(vec![
                    self.handle_resolution_error(ProguardError::InvalidMapping)
                ])
            }
            Err(ResolveError::UnhandledError(e)) => Err(e),
        }
    }

    async fn resolve_impl<C>(&self, team_id: i32, catalog: &C) -> Result<Vec<Frame>, ResolveError>
    where
        C: SymbolCatalog<OrChunkId<ProguardRef>, FetchedMapping>,
    {
        // A frame without a map_id has no ProGuard mapping to demangle against, which is
        // the norm for unobfuscated JVM apps: server SDKs, and Android builds without
        // minification. javac keeps the real file, line and method names in the class
        // file, so the frame arrives already readable and there is nothing to resolve.
        // Short-circuit before `get_ref()` and the catalog lookup so these frames stop
        // being counted (and logged) as resolution failures.
        if self.map_id.is_none() {
            return Ok(vec![self.into()]);
        }

        let r = self.get_ref()?;
        let map: Arc<FetchedMapping> = catalog.lookup(team_id, r.clone()).await?;
        let cache = map.get_cache()?;

        let frame = match self.filename.as_ref() {
            Some(file) => StackFrame::with_file(
                &self.module,
                &self.function,
                self.lineno.unwrap_or_default(),
                file,
            ),
            None => StackFrame::new(
                &self.module,
                &self.function,
                self.lineno.unwrap_or_default(),
            ),
        };

        let res: Vec<Frame> = cache
            .remap_frame(&frame)
            .map(|re| (self, re).into())
            .collect();

        if res.is_empty() {
            warn!(
                "Failed to construct any remapped frames from the raw frame {} and chunk id {}",
                self.frame_id(),
                self.get_ref()?
            );
            Ok(vec![(self, ProguardError::NoOriginalFrames).into()])
        } else {
            Ok(res)
        }
    }

    pub fn handle_resolution_error(&self, error: ProguardError) -> Frame {
        (self, error).into()
    }

    pub fn symbol_set_ref(&self) -> Option<String> {
        self.get_ref().ok().map(|r| r.to_string())
    }

    pub fn get_ref(&self) -> Result<OrChunkId<ProguardRef>, ProguardError> {
        self.map_id
            .as_ref()
            .map(|id| OrChunkId::chunk_id(id.clone()))
            .ok_or(ProguardError::NoMapId)
    }

    pub async fn remap_class<C>(
        &self,
        team_id: i32,
        class: &str,
        catalog: &C,
    ) -> Result<Option<String>, ResolveError>
    where
        C: SymbolCatalog<OrChunkId<ProguardRef>, FetchedMapping>,
    {
        let r = self.get_ref()?;
        let map: Arc<FetchedMapping> = catalog.lookup(team_id, r.clone()).await?;
        Ok(map.remap_class(class)?)
    }

    // Android SDKs derive the proguard chunk id from build metadata as
    // `<applicationId>@<versionName>+<versionCode>`.
    fn application_id(&self) -> Option<&str> {
        let (app_id, _) = self.map_id.as_deref()?.split_once('@')?;
        (!app_id.is_empty()).then_some(app_id)
    }

    // The SDK classifies in_app at capture time by matching *runtime* class
    // names against its inAppIncludes, so on a minified build (obfuscated
    // names) nothing matches and every frame arrives as in_app: false. Once
    // proguard resolution recovers the real class name, reclassify frames
    // under the app's own package. We never demote: unminified builds (and
    // user-configured inAppIncludes) already classify correctly client-side.
    fn resolved_in_app(&self, resolved_class: &str) -> bool {
        if self.meta.in_app {
            return true;
        }
        self.application_id().is_some_and(|app_id| {
            resolved_class
                .strip_prefix(app_id)
                .is_some_and(|rest| rest.is_empty() || rest.starts_with('.'))
        })
    }
}

impl<'a> From<(&'a RawJavaFrame, StackFrame<'a>)> for Frame {
    fn from((raw, remapped): (&'a RawJavaFrame, StackFrame<'a>)) -> Self {
        let mut f = Frame {
            frame_id: FrameId::placeholder(),
            mangled_name: raw.function.clone(),
            line: Some(remapped.line() as u32),
            column: None,
            source: remapped.file().map(ToString::to_string),
            in_app: raw.resolved_in_app(remapped.class()),
            resolved_name: Some(remapped.method().to_string()),
            lang: "java".to_string(),
            resolved: true,
            resolve_failure: None,

            junk_drawer: None,
            code_variables: None,
            synthetic: raw.meta.synthetic,
            context: None,
            suspicious: false,
            module: Some(remapped.class().to_string()),
        };

        add_raw_to_junk(&mut f, raw);

        f
    }
}

// Pass-through conversion for a frame that arrived already readable, because it carries
// no map_id and so has no ProGuard mapping to demangle against. The client-provided
// module, method, file and line are the real ones, so we surface them as-is with
// `resolved: true` and no failure. This mirrors the direct `From<&RawX> for Frame`
// conversions used by the catalog-free languages (python, go, php, ruby).
//
// INVARIANT: `resolved_name` deliberately stays `None`, even though the frame is
// resolved. `update_frame` in `modes/processing/fingerprinting/mod.rs` branches on
// `resolved_name`: when it is `Some`, it hashes source + module + resolved_name and
// returns; when it is `None`, it hashes source + module + mangled_name (+ line under V1)
// + lang. Because `mangled_name`, `source`, `module` and `lang` here are identical to
// what the previous failure path produced, leaving `resolved_name` as `None` keeps the
// mangled branch selected, so the per-frame hash contribution is byte-identical.
// Populating it would silently re-key that traffic into new issues, so that flip is
// deferred to a `FingerprintVersion` bump, which is the mechanism that exists for
// intentional regrouping.
//
// That covers per-frame hashing, but not frame *selection*, and the two differ for one
// case. `FrameSelection::InAppResolvedElseAll` (the V1 default) keeps in-app frames, and
// restricts to resolved ones only when at least one frame in the exception resolved. For a
// stack where no frame carries a map_id, every frame flips to resolved together, so the
// selected set is unchanged and the fingerprint is stable. For a *mixed* stack, where some
// frames carry a map_id and some do not (see the ref-less-frame handling in
// `resolve_java_exception`), a ref-less in-app frame used to be excluded next to a
// successfully remapped one and is now included, which does change that issue's
// fingerprint. Obfuscated-android traffic is the only shape that hits this.
//
// The success metric is not emitted here: the `RawFrame` dispatcher in
// `symbolication/resolve.rs` already counts every frame that comes back with
// `resolved: true` toward `FRAME_RESOLVED`.
impl From<&RawJavaFrame> for Frame {
    fn from(raw: &RawJavaFrame) -> Self {
        let mut f = Frame {
            frame_id: FrameId::placeholder(),
            mangled_name: raw.function.clone(),
            line: raw.lineno.map(|ln| ln as u32),
            column: None,
            source: raw.filename.clone(),
            // No map_id means no applicationId to reclassify against, so `resolved_in_app`
            // would return the raw flag anyway. The client classified this build correctly
            // because its class names were never obfuscated.
            in_app: raw.meta.in_app,
            resolved_name: None,
            lang: "java".to_string(),
            resolved: true,
            resolve_failure: None,

            junk_drawer: None,
            code_variables: None,
            synthetic: raw.meta.synthetic,
            context: None,
            suspicious: false,
            module: Some(raw.module.clone()),
        };

        add_raw_to_junk(&mut f, raw);

        f
    }
}

impl From<(&RawJavaFrame, ProguardError)> for Frame {
    fn from((raw, error): (&RawJavaFrame, ProguardError)) -> Self {
        record_frame_resolution_failure("java", error.metric_reason(), &error);

        let resolve_failure = Some(error.to_string());

        let mut f = Frame {
            frame_id: FrameId::placeholder(),
            mangled_name: raw.function.clone(),
            line: raw.lineno.map(|ln| ln as u32),
            column: None,
            source: raw.filename.clone(),
            in_app: raw.meta.in_app,
            resolved_name: None,
            lang: "java".to_string(),
            resolved: false,
            resolve_failure,
            junk_drawer: None,
            code_variables: None,
            synthetic: raw.meta.synthetic,
            context: None,
            suspicious: false,
            module: Some(raw.module.clone()),
        };

        add_raw_to_junk(&mut f, raw);

        f
    }
}

#[cfg(test)]
mod tests {
    use sqlx::{postgres::PgConnectOptions, PgPool};

    use crate::{
        core::config::ResolverConfig,
        symbolication::symbol_store::{
            apple::AppleProvider, chunk_id::ChunkIdFetcher, hermesmap::HermesMapProvider,
            native::NativeProvider, proguard::ProguardProvider, sourcemap::SourcemapProvider,
            Catalog, MockS3Client,
        },
    };

    use super::*;

    const PROGUARD_MAP: &str =
        include_str!("../../../../tests/static/proguard/mapping_example.txt");

    fn raw_frame(module: &str, in_app: bool, map_id: Option<&str>) -> RawJavaFrame {
        RawJavaFrame {
            filename: Some("SourceFile".to_string()),
            function: "onClick".to_string(),
            lineno: Some(14),
            module: module.to_string(),
            map_id: map_id.map(ToString::to_string),
            method_synthetic: false,
            meta: CommonFrameMetadata {
                in_app,
                synthetic: false,
            },
        }
    }

    // A pool that never opens a connection. The pass-through path returns before any
    // query runs, so a lazy pool lets the catalog be built without a live Postgres.
    fn lazy_pool() -> PgPool {
        PgPool::connect_lazy_with(PgConnectOptions::new())
    }

    // A catalog whose S3 client has no mockall expectations set, so any attempt to fetch
    // a symbol set panics instead of returning a plausible-looking miss. That turns "the
    // pass-through path reached the symbol store" into a test failure.
    fn catalog_that_never_fetches(db: PgPool) -> Catalog {
        let mut config = ResolverConfig::init_with_defaults().unwrap();
        config.object_storage_bucket = "test-bucket".to_string();
        let client = Arc::new(MockS3Client::default());

        let bucket = config.object_storage_bucket.clone();
        let smp = ChunkIdFetcher::new(
            SourcemapProvider::new(&config),
            client.clone(),
            db.clone(),
            bucket.clone(),
        );
        let hmp = ChunkIdFetcher::new(
            HermesMapProvider {},
            client.clone(),
            db.clone(),
            bucket.clone(),
        );
        let pgp = ChunkIdFetcher::new(
            ProguardProvider {},
            client.clone(),
            db.clone(),
            bucket.clone(),
        );
        let apple =
            ChunkIdFetcher::new(AppleProvider {}, client.clone(), db.clone(), bucket.clone());
        let native = ChunkIdFetcher::new(NativeProvider {}, client.clone(), db.clone(), bucket);
        Catalog::new(smp, hmp, pgp, apple, native)
    }

    #[tokio::test]
    async fn map_id_less_frames_pass_through_without_lookup() {
        let catalog = catalog_that_never_fetches(lazy_pool());

        // An unobfuscated server-JVM stack: application classes plus a framework frame,
        // none of them carrying a map_id.
        let frames = [
            raw_frame("com.acme.billing.InvoiceService", true, None),
            raw_frame("java.lang.Thread", false, None),
        ];

        for raw in &frames {
            assert_eq!(raw.symbol_set_ref(), None);

            let resolved = raw.resolve_frame(1, &catalog).await.unwrap();
            assert_eq!(
                resolved.len(),
                1,
                "pass-through maps 1 raw frame to 1 frame"
            );
            let f = &resolved[0];

            assert!(f.resolved, "an unobfuscated frame is already resolved");
            assert_eq!(f.resolve_failure, None);
            assert_eq!(f.resolved_name, None, "see the fingerprint invariant");
            assert_eq!(f.mangled_name, raw.function);
            assert_eq!(f.module.as_deref(), Some(raw.module.as_str()));
            assert_eq!(f.source, raw.filename);
            assert_eq!(f.line, raw.lineno.map(|l| l as u32));
            assert_eq!(f.lang, "java");
            assert_eq!(f.in_app, raw.meta.in_app);
        }
    }

    // Guards the fingerprint-neutrality claim in the `From<&RawJavaFrame>` invariant
    // comment. Every field `update_frame` reads must match what the old failure path
    // produced, so flipping these frames to resolved cannot re-key existing issues.
    // If someone populates `resolved_name` on the pass-through path, this fails.
    #[test]
    fn pass_through_is_fingerprint_identical_to_the_old_failure_frame() {
        let raw = raw_frame("com.acme.billing.InvoiceService", true, None);

        let passed_through: Frame = (&raw).into();
        let legacy: Frame = (&raw, ProguardError::NoMapId).into();

        assert_eq!(passed_through.resolved_name, None);
        assert_eq!(legacy.resolved_name, None);

        // The inputs `update_frame` hashes, in both the resolved and unresolved branches.
        assert_eq!(passed_through.source, legacy.source);
        assert_eq!(passed_through.module, legacy.module);
        assert_eq!(passed_through.mangled_name, legacy.mangled_name);
        assert_eq!(passed_through.line, legacy.line);
        assert_eq!(passed_through.lang, legacy.lang);

        // The behavior that actually changed.
        assert!(passed_through.resolved);
        assert!(!legacy.resolved);
        assert_eq!(passed_through.resolve_failure, None);
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn map_id_with_missing_mapping_still_fails(db: PgPool) {
        // A map_id is present but no symbol set was ever uploaded. That is a real
        // resolution failure and must stay one, so the short-circuit above cannot be
        // widened to swallow obfuscated frames we genuinely failed to demangle.
        let catalog = catalog_that_never_fetches(db);
        let raw = raw_frame("a1.d", false, Some("com.posthog.android.sample@3.0+3"));

        let resolved = raw.resolve_frame(1, &catalog).await.unwrap();
        assert_eq!(resolved.len(), 1);
        let f = &resolved[0];
        assert!(!f.resolved);
        assert!(f.resolve_failure.is_some());
        assert_eq!(f.resolved_name, None);
    }

    #[test]
    fn map_id_changes_the_frame_id() {
        // The id is the cache key for stored frame results, so the same source location
        // captured with and without a mapping reference must not share one. Otherwise the
        // pass-through record, saved as resolved on the long TTL with no linked symbol set,
        // would be served to the obfuscated frame instead of it being remapped.
        let without = raw_frame("a1.d", false, None);
        let with = raw_frame("a1.d", false, Some("com.posthog.android.sample@3.0+3"));
        assert_ne!(without.frame_id(), with.frame_id());

        // The unversioned construction every stored java id was written with. The version
        // tag has to move both frame shapes off it, or a mixed-version fleet serves records
        // written for one shape to the other until they expire.
        let mut legacy = Sha512::new();
        legacy.update(without.filename.as_ref().unwrap().as_bytes());
        legacy.update(without.function.as_bytes());
        legacy.update(without.lineno.unwrap().to_be_bytes());
        legacy.update(without.module.as_bytes());
        let legacy = format!("{:x}", legacy.finalize());
        assert_ne!(without.frame_id(), legacy);
        assert_ne!(with.frame_id(), legacy);
    }

    #[test]
    fn bytes_cannot_shift_across_field_boundaries() {
        // Concatenating the fields raw made these two frames hash the same bytes, so one
        // could plant the stored record the other reads: a crafted pass-through frame keeps
        // the real obfuscated frame from being remapped for as long as the record lives.
        let mapped = raw_frame("a1.d", false, Some("release"));
        let shifted = raw_frame("a1.drelease", false, None);
        assert_ne!(mapped.frame_id(), shifted.frame_id());

        // The same bug in the presence bytes: an absent field must not encode like a present
        // empty or zero one. Both shapes reach us from untrusted capture payloads, and they
        // pass through to frames with different `source` and `line`.
        let mut no_filename = raw_frame("a1.d", false, None);
        no_filename.filename = None;
        let mut empty_filename = raw_frame("a1.d", false, None);
        empty_filename.filename = Some(String::new());
        assert_ne!(no_filename.frame_id(), empty_filename.frame_id());

        let mut no_lineno = raw_frame("a1.d", false, None);
        no_lineno.lineno = None;
        let mut zero_lineno = raw_frame("a1.d", false, None);
        zero_lineno.lineno = Some(0);
        assert_ne!(no_lineno.frame_id(), zero_lineno.frame_id());
    }

    #[test]
    fn frame_ids_are_tagged_outside_the_digest() {
        // Frame records are keyed by raw id per team, and the other languages' encoders emit
        // a bare digest over client-controlled strings, so one of those frames can be given
        // field values that reproduce this construction's hash input. The tag has to sit on
        // the key, where they cannot reach it, which also means a java id is never a plain
        // hex digest.
        let id = raw_frame("a1.d", false, Some("com.posthog.android.sample@3.0+3")).frame_id();

        assert!(id.starts_with("java-v2:"), "{id}");
        assert!(!id.chars().all(|c| c.is_ascii_hexdigit()), "{id}");
    }

    #[test]
    fn resolved_frames_under_application_id_promote_to_in_app() {
        let mapping = proguard::ProguardMapping::new(PROGUARD_MAP.as_bytes());
        let mut cache_bytes = Vec::new();
        proguard::ProguardCache::write(&mapping, &mut cache_bytes).unwrap();
        let cache = proguard::ProguardCache::parse(&cache_bytes).unwrap();

        let raw = raw_frame("a1.d", false, Some("com.posthog.android.sample@3.0+3"));
        let frame = StackFrame::with_file("a1.d", "onClick", 14, "SourceFile");
        let frames: Vec<Frame> = cache
            .remap_frame(&frame)
            .map(|re| (&raw, re).into())
            .collect();

        assert!(!frames.is_empty());
        assert!(frames.iter().all(|f| f.in_app
            && f.module
                .as_deref()
                .unwrap()
                .starts_with("com.posthog.android.sample.")));
    }

    #[test]
    fn resolved_in_app_classification() {
        let map_id = Some("com.posthog.android.sample@3.0+3");
        let cases = [
            // (raw in_app, map_id, resolved class, expected)
            (
                false,
                map_id,
                "com.posthog.android.sample.ErrorTrackingActivityKt",
                true,
            ),
            (
                false,
                map_id,
                "androidx.appcompat.app.AppCompatActivity",
                false,
            ),
            (false, map_id, "kotlin.jvm.internal.Intrinsics", false),
            (false, map_id, "okhttp3.RealCall", false),
            // prefix must end on a package boundary
            (false, map_id, "com.posthog.android.sampleother.Foo", false),
            // raw true is never downgraded, even outside the applicationId
            (
                true,
                map_id,
                "androidx.appcompat.app.AppCompatActivity",
                true,
            ),
            (true, None, "androidx.appcompat.app.AppCompatActivity", true),
            // map_id absent or not in <applicationId>@<version> form: keep raw flag
            (
                false,
                None,
                "com.posthog.android.sample.ErrorTrackingActivityKt",
                false,
            ),
            (
                false,
                Some("somechunkid"),
                "com.posthog.android.sample.ErrorTrackingActivityKt",
                false,
            ),
        ];

        for (raw_in_app, map_id, class, expected) in cases {
            let raw = raw_frame("a1.d", raw_in_app, map_id);
            assert_eq!(
                raw.resolved_in_app(class),
                expected,
                "raw={raw_in_app} map_id={map_id:?} class={class}"
            );
        }
    }

    #[test]
    fn unresolved_frames_keep_raw_in_app() {
        for raw_in_app in [false, true] {
            let raw = raw_frame("a1.d", raw_in_app, Some("com.posthog.android.sample@3.0+3"));
            let frame: Frame = (&raw, ProguardError::NoMapId).into();
            assert!(!frame.resolved);
            assert_eq!(frame.in_app, raw_in_app);
        }
    }
}
