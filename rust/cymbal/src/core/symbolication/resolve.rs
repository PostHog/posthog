use reqwest::Url;

use crate::core::frames::Frame;
use crate::core::symbolication::langs::apple::RawAppleFrame;
use crate::core::symbolication::langs::hermes::{HermesRef, RawHermesFrame};
use crate::core::symbolication::langs::java::RawJavaFrame;
use crate::core::symbolication::langs::js::RawJSFrame;
use crate::core::symbolication::langs::native::DebugImage;
use crate::core::symbolication::langs::node::RawNodeFrame;
use crate::core::symbolication::symbol_store::apple::AppleRef;
use crate::core::symbolication::symbol_store::chunk_id::OrChunkId;
use crate::core::symbolication::symbol_store::hermesmap::ParsedHermesMap;
use crate::core::symbolication::symbol_store::native::ParsedNativeSymbols;
use crate::core::symbolication::symbol_store::proguard::{FetchedMapping, ProguardRef};
use crate::core::symbolication::symbol_store::sourcemap::OwnedSourceMapCache;
use crate::core::symbolication::symbol_store::SymbolCatalog;
use crate::error::UnhandledError;

/// Resolution capability for raw stack frames.
///
/// Implemented by the catalog-backed raw frame types (`RawJSFrame`,
/// `RawNodeFrame`, `RawHermesFrame`, `RawJavaFrame`, `RawAppleFrame`) and by the
/// `RawFrame` dispatcher (see `crate::core::frames`). Catalog-free frames
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
    ) -> Result<Vec<Frame>, UnhandledError> {
        self.resolve_frame(team_id, catalog).await.map(|f| vec![f])
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
    ) -> Result<Vec<Frame>, UnhandledError> {
        self.resolve_frame(team_id, catalog).await.map(|f| vec![f])
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
    ) -> Result<Vec<Frame>, UnhandledError> {
        self.resolve_frame(team_id, catalog).await.map(|f| vec![f])
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
    ) -> Result<Vec<Frame>, UnhandledError> {
        self.resolve_frame(team_id, catalog, debug_images).await
    }
}
