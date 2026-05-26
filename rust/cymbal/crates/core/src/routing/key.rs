//! Routing keys and extractors used to assign items to endpoints.
//!
//! Keys describe affinity intent only. They do not know about endpoint
//! identity, transport, or capacity; those concerns live in sibling modules.

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum RoutingCacheKeyKind {
    DebugImageId,
    SymbolSetRef,
    ReleaseSource,
    StageSpecific(String),
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum RoutingKey {
    TeamId(i64),
    StageCache {
        kind: RoutingCacheKeyKind,
        value: String,
    },
    NoAffinity,
}

impl RoutingKey {
    pub fn new(value: impl Into<String>) -> Self {
        Self::StageCache {
            kind: RoutingCacheKeyKind::StageSpecific("generic".to_string()),
            value: value.into(),
        }
    }

    pub fn team_id(team_id: i64) -> Self {
        Self::TeamId(team_id)
    }

    pub fn debug_image_id(team_id: i64, debug_image_id: impl Into<String>) -> Self {
        Self::StageCache {
            kind: RoutingCacheKeyKind::DebugImageId,
            value: scoped_value(team_id, debug_image_id),
        }
    }

    pub fn symbol_set_ref(team_id: i64, symbol_set_ref: impl Into<String>) -> Self {
        Self::StageCache {
            kind: RoutingCacheKeyKind::SymbolSetRef,
            value: scoped_value(team_id, symbol_set_ref),
        }
    }

    pub fn release_source(team_id: i64, release_source: impl Into<String>) -> Self {
        Self::StageCache {
            kind: RoutingCacheKeyKind::ReleaseSource,
            value: scoped_value(team_id, release_source),
        }
    }

    pub fn no_affinity() -> Self {
        Self::NoAffinity
    }

    pub fn has_affinity(&self) -> bool {
        !matches!(self, Self::NoAffinity)
    }
}

fn scoped_value(team_id: i64, value: impl Into<String>) -> String {
    format!("team_id:{team_id}:{}", value.into())
}

impl From<&str> for RoutingKey {
    fn from(value: &str) -> Self {
        Self::new(value)
    }
}

impl From<String> for RoutingKey {
    fn from(value: String) -> Self {
        Self::new(value)
    }
}

pub trait RoutingKeyExtractor<Item> {
    fn routing_key(&self, item: &Item) -> RoutingKey;
}

impl<Item, Extractor> RoutingKeyExtractor<Item> for Extractor
where
    Extractor: Fn(&Item) -> RoutingKey,
{
    fn routing_key(&self, item: &Item) -> RoutingKey {
        self(item)
    }
}
