//! A deleted person keeps its version, so an older replay cannot resurrect it.

use bytes::{BufMut, Bytes, BytesMut};

use crate::PropertyStoreError;

const FORMAT_V1: u8 = 1;
const FLAG_DELETED: u8 = 0b1;
const HEADER_LEN: usize = 18;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StoredProperties {
    pub version: i64,
    pub deleted: bool,
    /// Epoch milliseconds; a revival resets it, so an earlier value than the row's marks a previous incarnation.
    pub created_at: i64,
    pub properties: Bytes,
}

pub fn encode_key(team_id: i64, person_id: i64) -> [u8; 16] {
    let mut key = [0u8; 16];
    key[..8].copy_from_slice(&team_id.to_be_bytes());
    key[8..].copy_from_slice(&person_id.to_be_bytes());
    key
}

pub fn encode_value(value: &StoredProperties) -> Bytes {
    let mut buf = BytesMut::with_capacity(HEADER_LEN + value.properties.len());
    buf.put_u8(FORMAT_V1);
    buf.put_u8(if value.deleted { FLAG_DELETED } else { 0 });
    buf.put_i64(value.version);
    buf.put_i64(value.created_at);
    buf.put_slice(&value.properties);
    buf.freeze()
}

pub fn version_of(raw: &[u8]) -> Option<i64> {
    if raw.len() < HEADER_LEN || raw[0] != FORMAT_V1 {
        return None;
    }
    Some(i64::from_be_bytes(raw[2..10].try_into().ok()?))
}

pub fn decode_value(
    team_id: i64,
    person_id: i64,
    raw: Bytes,
) -> Result<StoredProperties, PropertyStoreError> {
    let malformed = |reason: String| PropertyStoreError::Malformed {
        team_id,
        person_id,
        reason,
    };
    if raw.len() < HEADER_LEN {
        return Err(malformed(format!(
            "{} bytes is shorter than the header",
            raw.len()
        )));
    }
    if raw[0] != FORMAT_V1 {
        return Err(malformed(format!("unknown format {}", raw[0])));
    }
    let version = i64::from_be_bytes(raw[2..10].try_into().expect("8-byte slice"));
    let created_at = i64::from_be_bytes(raw[10..HEADER_LEN].try_into().expect("8-byte slice"));
    Ok(StoredProperties {
        version,
        deleted: raw[1] & FLAG_DELETED != 0,
        created_at,
        properties: raw.slice(HEADER_LEN..),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_value_round_trips() {
        for deleted in [false, true] {
            let value = StoredProperties {
                version: 42,
                deleted,
                created_at: 1_700_000_000_000,
                properties: Bytes::from_static(br#"{"plan":"paid"}"#),
            };
            assert_eq!(decode_value(1, 2, encode_value(&value)).unwrap(), value);
        }
    }

    #[test]
    fn keys_of_one_team_sort_together() {
        assert!(encode_key(1, i64::MAX) < encode_key(2, 0));
    }

    #[test]
    fn a_truncated_or_unknown_value_is_malformed() {
        assert!(decode_value(1, 2, Bytes::from_static(&[1, 0, 0])).is_err());
        let mut unknown = encode_value(&StoredProperties {
            version: 1,
            deleted: false,
            created_at: 0,
            properties: Bytes::new(),
        })
        .to_vec();
        unknown[0] = 9;
        assert!(decode_value(1, 2, Bytes::from(unknown)).is_err());
    }
}
