use std::fmt::{Debug, Display};

use sha2::{Digest, Sha512};

pub enum OrChunkId<R> {
    Inner(R),
    ChunkId(String),
    Both { inner: R, id: String },
}

impl<R> OrChunkId<R> {
    pub fn inner(inner: R) -> Self {
        Self::Inner(inner)
    }

    pub fn chunk_id(id: impl Into<String>) -> Self {
        Self::ChunkId(id.into())
    }

    pub fn both(inner: R, id: impl Into<String>) -> Self {
        Self::Both {
            inner,
            id: id.into(),
        }
    }
}

impl<Ref> Debug for OrChunkId<Ref>
where
    Ref: Debug,
{
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            OrChunkId::Inner(inner) => write!(f, "Inner({inner:?})"),
            OrChunkId::ChunkId(id) => write!(f, "ChunkId({id})"),
            OrChunkId::Both { inner, id } => write!(f, "Both {{ inner: {inner:?}, id: {id} }}"),
        }
    }
}

impl<Ref> Clone for OrChunkId<Ref>
where
    Ref: Clone,
{
    fn clone(&self) -> Self {
        match self {
            OrChunkId::Inner(inner) => OrChunkId::Inner(inner.clone()),
            OrChunkId::ChunkId(id) => OrChunkId::ChunkId(id.clone()),
            OrChunkId::Both { inner, id } => OrChunkId::Both {
                inner: inner.clone(),
                id: id.clone(),
            },
        }
    }
}

// `Display` is the human-readable identity of a ref, used by log lines and resolved frame
// metadata. For Both, we surface the chunk id because it's the more meaningful identifier
// across frames carrying both a URL and a chunk id.
//
// The persistence and caching layers do NOT use this — see `SymbolSetKey` and
// `SymbolSetCacheKey` for why.
impl<R> Display for OrChunkId<R>
where
    R: Display,
{
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            OrChunkId::Inner(inner) => inner.fmt(f),
            OrChunkId::ChunkId(id) => write!(f, "{id}"),
            OrChunkId::Both { inner: _, id } => write!(f, "{id}"),
        }
    }
}

// `SymbolSetCacheKey` is the in-memory cache / concurrency identity. Unlike `Display`, it
// must keep `Both(id, inner)` distinct from bare `ChunkId(id)`: a `Both` lookup may fall back
// to fetching attacker-controlled URL data when the chunk id is missing, and caching that under
// the bare chunk-id key would transiently poison future chunk-id-only lookups.
pub trait SymbolSetCacheKey {
    fn symbol_set_cache_key(&self) -> String;
}

fn hashed_symbol_set_cache_key(prefix: &str, parts: &[&str]) -> String {
    let mut hasher = Sha512::new();
    for part in parts {
        hasher.update(part.len().to_be_bytes());
        hasher.update(part.as_bytes());
    }
    format!("{}:{:x}", prefix, hasher.finalize())
}

impl<R> SymbolSetCacheKey for OrChunkId<R>
where
    R: Display,
{
    fn symbol_set_cache_key(&self) -> String {
        match self {
            OrChunkId::Inner(inner) => hashed_symbol_set_cache_key("inner", &[&inner.to_string()]),
            OrChunkId::ChunkId(id) => hashed_symbol_set_cache_key("chunk-id", &[id]),
            OrChunkId::Both { inner, id } => {
                hashed_symbol_set_cache_key("both", &[id, &inner.to_string()])
            }
        }
    }
}

impl SymbolSetCacheKey for reqwest::Url {
    fn symbol_set_cache_key(&self) -> String {
        hashed_symbol_set_cache_key("inner", &[self.as_str()])
    }
}

// `SymbolSetKey` separates the DB lookup keys from the DB save key.
//
// The capture pipeline can receive a frame carrying both an attacker-controlled URL and an
// arbitrary chunk id. Persisting that fetch under the chunk id namespace would let the
// capture path squat rows that the authenticated upload API (which always keys by chunk id)
// would later want to write — letting unauthenticated capture traffic pre-empt or be
// confused with authenticated uploads.
//
// To prevent that, capture-driven writes are keyed by the URL the bytes were fetched from,
// while upload-driven writes stay keyed by chunk id. The two writers can no longer target
// the same row. Lookups still try the chunk id first (so an upload-API row keyed by chunk
// id is preferred over a capture-cached row keyed by URL), then fall back to the URL.
//
// `save_ref` is `None` for a bare `ChunkId` ref — there is no URL to fetch from, so there's
// nothing meaningful to persist, and we refuse to write a row keyed by a chunk id we never
// fetched data for.
pub trait SymbolSetKey {
    fn lookup_refs(&self) -> Vec<String>;
    fn save_ref(&self) -> Option<String>;
}

impl<R> SymbolSetKey for OrChunkId<R>
where
    R: Display,
{
    fn lookup_refs(&self) -> Vec<String> {
        match self {
            OrChunkId::Inner(inner) => vec![inner.to_string()],
            OrChunkId::ChunkId(id) => vec![id.clone()],
            OrChunkId::Both { inner, id } => vec![id.clone(), inner.to_string()],
        }
    }

    fn save_ref(&self) -> Option<String> {
        match self {
            OrChunkId::Inner(inner) => Some(inner.to_string()),
            OrChunkId::Both { inner, .. } => Some(inner.to_string()),
            OrChunkId::ChunkId(_) => None,
        }
    }
}

// `Url` standalone behaves exactly like `OrChunkId::Inner(url)` — a single self-keyed ref
// with no chunk-id alternative. Used directly by unit tests that wrap `SourcemapProvider`
// in `Saving` without an intervening `ChunkIdFetcher`.
impl SymbolSetKey for reqwest::Url {
    fn lookup_refs(&self) -> Vec<String> {
        vec![self.to_string()]
    }

    fn save_ref(&self) -> Option<String> {
        Some(self.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn symbol_set_key_prefers_chunk_id_for_lookup_but_url_for_save() {
        let url = reqwest::Url::parse("https://example.com/static/chunk.js").unwrap();
        let key = OrChunkId::both(url.clone(), "uploaded-chunk-id");

        assert_eq!(
            key.lookup_refs(),
            vec!["uploaded-chunk-id".to_string(), url.to_string()]
        );
        assert_eq!(key.save_ref(), Some(url.to_string()));
    }

    #[test]
    fn bare_chunk_id_has_no_capture_save_target() {
        let key = OrChunkId::<reqwest::Url>::chunk_id("uploaded-chunk-id");

        assert_eq!(key.lookup_refs(), vec!["uploaded-chunk-id".to_string()]);
        assert_eq!(key.save_ref(), None);
    }
}
