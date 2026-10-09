use std::mem::size_of;

use uuid::Uuid;

use super::codec::{PropertiesCodec, StoredProperties};
use super::persons::{CachedPerson, PersonCacheKey};

/// What foyer spends per record beyond the key and the value: the `Arc`
/// header around the record, its hash, weight, cache properties, LRU
/// links, reference count and flags, and the hash-table slot that points
/// at it.
const FOYER_RECORD_BOOKKEEPING_BYTES: usize = 96;

/// The form a person takes inside the cache. It sits inline in foyer's
/// record, so an entry is one allocation for the record plus one for the
/// properties. `CachedPerson` costs two more: its own `Arc` and the uuid
/// `String`. The properties box has no spare capacity, which a `Vec`
/// filled by a serializer usually does.
pub(super) struct StoredPerson {
    id: i64,
    team_id: i64,
    uuid: StoredUuid,
    properties: StoredProperties,
    created_at: i64,
    version: i64,
    last_seen_at: Option<i64>,
    is_identified: bool,
    is_deleted: bool,
}

impl StoredPerson {
    pub(super) fn new(person: CachedPerson, codec: &PropertiesCodec) -> Self {
        Self {
            id: person.id,
            team_id: person.team_id,
            uuid: StoredUuid::new(person.uuid),
            properties: codec.encode(person.properties),
            created_at: person.created_at,
            version: person.version,
            last_seen_at: person.last_seen_at,
            is_identified: person.is_identified,
            is_deleted: person.is_deleted,
        }
    }

    pub(super) fn to_cached(&self, codec: &PropertiesCodec) -> Result<CachedPerson, &'static str> {
        Ok(CachedPerson {
            id: self.id,
            uuid: self.uuid.to_owned_string(),
            team_id: self.team_id,
            properties: codec.decode(&self.properties)?,
            created_at: self.created_at,
            version: self.version,
            is_identified: self.is_identified,
            is_deleted: self.is_deleted,
            last_seen_at: self.last_seen_at,
        })
    }

    pub(super) fn properties(&self) -> &StoredProperties {
        &self.properties
    }

    /// The bytes this entry holds against the cache capacity: the key,
    /// this struct, foyer's bookkeeping, and the heap the struct owns.
    pub(super) fn weight(&self) -> usize {
        size_of::<PersonCacheKey>()
            + size_of::<Self>()
            + FOYER_RECORD_BOOKKEEPING_BYTES
            + self.properties.stored_len()
            + self.uuid.heap_len()
    }
}

/// A person's uuid. The canonical spelling (hyphenated, lowercase) packs
/// into 16 bytes. Every other spelling stays verbatim, so `get` returns
/// the exact string that `put` received.
enum StoredUuid {
    Hyphenated(Uuid),
    Verbatim(Box<str>),
}

impl StoredUuid {
    fn new(uuid: String) -> Self {
        if let Ok(parsed) = Uuid::try_parse(&uuid) {
            if *parsed.hyphenated().encode_lower(&mut Uuid::encode_buffer()) == *uuid {
                return Self::Hyphenated(parsed);
            }
        }
        Self::Verbatim(uuid.into_boxed_str())
    }

    fn to_owned_string(&self) -> String {
        match self {
            Self::Hyphenated(uuid) => uuid.hyphenated().to_string(),
            Self::Verbatim(uuid) => uuid.to_string(),
        }
    }

    fn heap_len(&self) -> usize {
        match self {
            Self::Hyphenated(_) => 0,
            Self::Verbatim(uuid) => uuid.len(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn uuid_spellings_survive_the_round_trip() {
        for spelling in [
            "0191c3a2-7b4e-7c4a-9f3e-2d1c0b9a8f7e",
            "0191C3A2-7B4E-7C4A-9F3E-2D1C0B9A8F7E",
            "0191c3a27b4e7c4a9f3e2d1c0b9a8f7e",
            "not-a-uuid",
        ] {
            assert_eq!(
                StoredUuid::new(spelling.to_string()).to_owned_string(),
                spelling
            );
        }
    }
}
