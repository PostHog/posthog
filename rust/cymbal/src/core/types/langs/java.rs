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

impl RawJavaFrame {
    pub fn frame_id(&self) -> String {
        // We don't have version info for java frames, so we rely on
        // the module, function and line number to
        // uniquely identify a frame, with the intuition being that even
        // if two frames are from two different library versions, if the
        // files they're in are sufficiently similar we can consider
        // them to be the same frame
        let mut hasher = Sha512::new();
        if let Some(filename) = &self.filename {
            hasher.update(filename.as_bytes());
        }
        hasher.update(self.function.as_bytes());
        hasher.update(self.lineno.unwrap_or_default().to_be_bytes());
        hasher.update(self.module.as_bytes());
        format!("{:x}", hasher.finalize())
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
                warn!("Unexpected Proguard symbol resolution error: {:?}", e);
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
            release: None,
            synthetic: raw.meta.synthetic,
            context: None,
            suspicious: false,
            module: Some(remapped.class().to_string()),
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
            release: None,
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
