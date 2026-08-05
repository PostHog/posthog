use reqwest::Url;

use crate::core::metric_consts::{FRAME_RESOLVED, LEGACY_JS_FRAME_RESOLVED, PER_FRAME_TIME};
use crate::core::symbolication::symbol_store::apple::AppleRef;
use crate::core::symbolication::symbol_store::chunk_id::OrChunkId;
use crate::core::symbolication::symbol_store::hermesmap::ParsedHermesMap;
use crate::core::symbolication::symbol_store::native::ParsedNativeSymbols;
use crate::core::symbolication::symbol_store::proguard::{FetchedMapping, ProguardRef};
use crate::core::symbolication::symbol_store::sourcemap::OwnedSourceMapCache;
use crate::core::symbolication::symbol_store::Catalog;
use crate::core::symbolication::symbol_store::SymbolCatalog;
use crate::core::types::frames::{Frame, RawFrame};
use crate::core::types::langs::apple::RawAppleFrame;
use crate::core::types::langs::hermes::{HermesRef, RawHermesFrame};
use crate::core::types::langs::java::RawJavaFrame;
use crate::core::types::langs::js::RawJSFrame;
use crate::core::types::langs::native::DebugImage;
use crate::core::types::langs::node::RawNodeFrame;
use crate::error::UnhandledError;

/// Resolution capability for raw stack frames.
///
/// Implemented by the catalog-backed raw frame types (`RawJSFrame`,
/// `RawNodeFrame`, `RawHermesFrame`, `RawJavaFrame`, `RawAppleFrame`) and by the
/// `RawFrame` dispatcher (see `crate::core::types::frames`). Catalog-free frames
/// (python, ruby, go, …) carry no symbol-resolution behavior — they convert
/// directly via `From<&RawX> for Frame`.
///
/// `C` is the symbol-catalog capability the implementor needs, e.g.
/// `SymbolCatalog<OrChunkId<Url>, OwnedSourceMapCache>` for JavaScript. The
/// concrete `Catalog` implements every such capability, so `RawFrame`
/// dispatches with `C = Catalog`.
#[allow(async_fn_in_trait)] // only used in-crate; mirrors the inherent async resolvers
pub trait Resolve<C> {
    async fn resolve(
        &self,
        team_id: i32,
        catalog: &C,
        debug_images: &[DebugImage],
        context_lines: usize,
    ) -> Result<Vec<Frame>, UnhandledError>;
}

impl<C> Resolve<C> for RawJSFrame
where
    C: SymbolCatalog<OrChunkId<Url>, OwnedSourceMapCache>,
{
    async fn resolve(
        &self,
        team_id: i32,
        catalog: &C,
        _debug_images: &[DebugImage],
        context_lines: usize,
    ) -> Result<Vec<Frame>, UnhandledError> {
        self.resolve_frame(team_id, catalog, context_lines)
            .await
            .map(|f| vec![f])
    }
}

impl<C> Resolve<C> for RawNodeFrame
where
    C: SymbolCatalog<OrChunkId<Url>, OwnedSourceMapCache>,
{
    async fn resolve(
        &self,
        team_id: i32,
        catalog: &C,
        _debug_images: &[DebugImage],
        context_lines: usize,
    ) -> Result<Vec<Frame>, UnhandledError> {
        self.resolve_frame(team_id, catalog, context_lines)
            .await
            .map(|f| vec![f])
    }
}

impl<C> Resolve<C> for RawHermesFrame
where
    C: SymbolCatalog<OrChunkId<HermesRef>, ParsedHermesMap>,
{
    async fn resolve(
        &self,
        team_id: i32,
        catalog: &C,
        _debug_images: &[DebugImage],
        context_lines: usize,
    ) -> Result<Vec<Frame>, UnhandledError> {
        self.resolve_frame(team_id, catalog, context_lines)
            .await
            .map(|f| vec![f])
    }
}

impl<C> Resolve<C> for RawJavaFrame
where
    C: SymbolCatalog<OrChunkId<ProguardRef>, FetchedMapping>,
{
    async fn resolve(
        &self,
        team_id: i32,
        catalog: &C,
        _debug_images: &[DebugImage],
        _context_lines: usize, // Java frames have no source context to bound
    ) -> Result<Vec<Frame>, UnhandledError> {
        self.resolve_frame(team_id, catalog).await
    }
}

impl<C> Resolve<C> for RawAppleFrame
where
    C: SymbolCatalog<OrChunkId<AppleRef>, ParsedNativeSymbols>,
{
    async fn resolve(
        &self,
        team_id: i32,
        catalog: &C,
        debug_images: &[DebugImage],
        context_lines: usize,
    ) -> Result<Vec<Frame>, UnhandledError> {
        self.resolve_frame(team_id, catalog, debug_images, context_lines)
            .await
    }
}

impl Resolve<Catalog> for RawFrame {
    async fn resolve(
        &self,
        team_id: i32,
        catalog: &Catalog,
        debug_images: &[DebugImage],
        context_lines: usize,
    ) -> Result<Vec<Frame>, UnhandledError> {
        let frame_resolve_time = common_metrics::timing_guard(PER_FRAME_TIME, &[]);
        // Catalog-backed frames resolve via `Resolve`; catalog-free frames convert
        // directly with `From<&RawX> for Frame` (no symbol resolution needed).
        let (res, lang_tag): (Result<Vec<Frame>, UnhandledError>, &str) = match self {
            RawFrame::JavaScriptWeb(frame) => (
                frame
                    .resolve(team_id, catalog, debug_images, context_lines)
                    .await,
                "javascript",
            ),
            RawFrame::LegacyJS(frame) => {
                // TODO: monitor this metric and remove the legacy frame type when it hits 0
                metrics::counter!(LEGACY_JS_FRAME_RESOLVED).increment(1);
                (
                    frame
                        .resolve(team_id, catalog, debug_images, context_lines)
                        .await,
                    "javascript",
                )
            }
            RawFrame::JavaScriptNode(frame) => (
                frame
                    .resolve(team_id, catalog, debug_images, context_lines)
                    .await,
                "javascript",
            ),

            RawFrame::Dart(frame) => (Ok(vec![frame.into()]), "dart"),
            RawFrame::Apple(frame) => (
                frame
                    .resolve(team_id, catalog, debug_images, context_lines)
                    .await,
                "apple",
            ),
            RawFrame::Php(frame) => (Ok(vec![frame.into()]), "php"),
            RawFrame::Python(frame) => (Ok(vec![frame.into()]), "python"),
            RawFrame::Ruby(frame) => (Ok(vec![frame.into()]), "ruby"),
            RawFrame::Native(frame) => (
                frame
                    .resolve(team_id, catalog, debug_images, context_lines)
                    .await,
                "native",
            ),
            RawFrame::Custom(frame) => (Ok(vec![frame.into()]), "custom"),
            RawFrame::Go(frame) => (Ok(vec![frame.into()]), "go"),
            RawFrame::Hermes(frame) => (
                frame
                    .resolve(team_id, catalog, debug_images, context_lines)
                    .await,
                "hermes",
            ),
            RawFrame::Java(frame) => (
                frame
                    .resolve(team_id, catalog, debug_images, context_lines)
                    .await,
                "java",
            ),
        };

        // The raw id of the frame is set after it's resolved.
        let res = res.map(|mut fs| {
            fs.iter_mut()
                .enumerate()
                .for_each(|(index, f)| f.frame_id = self.frame_id(team_id, index, debug_images));
            fs
        });

        if res.is_err() {
            frame_resolve_time.label("outcome", "failed")
        } else {
            frame_resolve_time.label("outcome", "success")
        }
        .label("lang", lang_tag)
        .fin();

        if let Ok(frames) = &res {
            for frame in frames {
                if frame.resolved {
                    metrics::counter!(FRAME_RESOLVED, "lang" => lang_tag).increment(1);
                }
                // Failure metrics are emitted by the language-specific `From` impls in
                // `langs/*.rs` at the moment of frame construction, where the typed error
                // is in scope (so we can call `metric_reason()` directly). This avoids
                // having to carry the typed error on the `Frame` struct just to recover
                // the metric label, which previously required a custom serializer plus
                // `skip_deserializing` and silently dropped failure reasons on PG round-trip.
            }
        }

        res
    }
}
