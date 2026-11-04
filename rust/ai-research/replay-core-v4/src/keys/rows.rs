//! The rows of the v4 key table and their DynamoDB encoding.

use std::collections::HashMap;

use aws_sdk_dynamodb::primitives::Blob;
use aws_sdk_dynamodb::types::AttributeValue;
use chrono::{DateTime, Months, NaiveDate, Utc};
use sha2::{Digest, Sha256};

use crate::envelope::NONCE_BYTES;
use crate::seal::SealedKey;

/// v3 spreads a team's sessions over 32 partitions so one large team cannot overload one partition. v4 keeps this.
pub const SESSION_SHARDS: u32 = 32;
/// A session keeps the key of the month it was first stored and writes at most about 15 days past that month. Raw
/// objects live 90 days and fetched images 98, so five months covers them and leaves room to raise that window a little.
const ROW_LIFETIME_MONTHS: u32 = 5;
/// The attributes that hold key material. A deletion removes all of them.
pub const KEY_MATERIAL: [&str; 3] = ["wrapped_key", "sealed_key", "key_nonce"];

pub type Item = HashMap<String, AttributeValue>;

#[derive(Debug, Clone, thiserror::Error, PartialEq, Eq)]
pub enum RowError {
    #[error("key row has no {0}")]
    Missing(&'static str),
    #[error("key row has a malformed {0}")]
    Malformed(&'static str),
    #[error("an unusable key row cannot be written")]
    NotWritable,
}

/// A primary key in the table.
#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct TableKey {
    pub pk: String,
    pub sk: String,
}

impl TableKey {
    pub fn team_month(team_id: i64, key_month: &str) -> Self {
        Self {
            pk: format!("team:{team_id}"),
            sk: format!("month:{key_month}"),
        }
    }

    pub fn session(team_id: i64, session_id: &str) -> Self {
        Self {
            pk: format!("team:{team_id}:shard:{}", session_shard(session_id)),
            sk: format!("session:{session_id}"),
        }
    }

    pub fn to_item(&self) -> Item {
        HashMap::from([
            ("pk".to_owned(), AttributeValue::S(self.pk.clone())),
            ("sk".to_owned(), AttributeValue::S(self.sk.clone())),
        ])
    }

    pub fn from_item(item: &Item) -> Result<Self, RowError> {
        Ok(Self {
            pk: string(item, "pk")?,
            sk: string(item, "sk")?,
        })
    }
}

/// The v3 shard: the first 8 hex digits of `sha256(session_id)` as an integer, modulo 32.
pub fn session_shard(session_id: &str) -> u32 {
    let digest = Sha256::digest(session_id.as_bytes());
    u32::from_be_bytes([digest[0], digest[1], digest[2], digest[3]]) % SESSION_SHARDS
}

/// The UTC day of an instant, as the object partitions name it. A flush writes on this day.
pub fn write_day(at: DateTime<Utc>) -> String {
    at.format("%Y-%m-%d").to_string()
}

/// The key month of a UTC day `YYYY-MM-DD`, as `key_month` stores it.
pub fn key_month(day: &str) -> &str {
    day.get(..7).unwrap_or(day)
}

/// The start of the month `key_month + 5`, in epoch seconds: when DynamoDB TTL may remove the row.
pub fn expires_at(key_month: &str) -> Result<i64, RowError> {
    let malformed = || RowError::Malformed("key_month");
    let start = NaiveDate::parse_from_str(&format!("{key_month}-01"), "%Y-%m-%d")
        .map_err(|_| malformed())?;
    if start.format("%Y-%m").to_string() != key_month {
        return Err(malformed());
    }
    let end = start
        .checked_add_months(Months::new(ROW_LIFETIME_MONTHS))
        .ok_or_else(malformed)?;
    Ok(end
        .and_hms_opt(0, 0, 0)
        .expect("midnight exists")
        .and_utc()
        .timestamp())
}

/// What the table holds at one key.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Row {
    /// A team month key, wrapped by KMS.
    TeamMonth {
        team_id: i64,
        key_month: String,
        wrapped_key: Vec<u8>,
    },
    /// A session key, sealed under the team month key of `key_month`.
    Session {
        team_id: i64,
        key_month: String,
        sealed: SealedKey,
    },
    /// A deletion replaced the key material. A writer that meets one drops the data it was about to store.
    Deleted,
    /// A row that holds no key a writer can use and no tombstone. A writer drops the data, and never writes over it.
    Unusable(Unusable),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Unusable {
    Malformed(&'static str),
    /// The row is past `expires_at`, and DynamoDB TTL has not removed it yet.
    Expired,
}

impl Row {
    /// The full item for a conditional put. `key_month` sets the row's expiry.
    pub fn to_item(&self, key: &TableKey) -> Result<Item, RowError> {
        let mut item = key.to_item();
        match self {
            Row::TeamMonth {
                team_id,
                key_month,
                wrapped_key,
            } => {
                insert_common(&mut item, *team_id, key_month)?;
                item.insert(
                    "wrapped_key".to_owned(),
                    AttributeValue::B(Blob::new(wrapped_key.clone())),
                );
            }
            Row::Session {
                team_id,
                key_month,
                sealed,
            } => {
                insert_common(&mut item, *team_id, key_month)?;
                item.insert(
                    "sealed_key".to_owned(),
                    AttributeValue::B(Blob::new(sealed.sealed.clone())),
                );
                item.insert(
                    "key_nonce".to_owned(),
                    AttributeValue::B(Blob::new(sealed.nonce.to_vec())),
                );
            }
            Row::Deleted => {
                item.insert("deleted".to_owned(), AttributeValue::Bool(true));
            }
            Row::Unusable(_) => return Err(RowError::NotWritable),
        }
        Ok(item)
    }

    /// Reads a stored item at `now`, in epoch seconds. A row that cannot give a key reads as `Unusable`, so one bad row
    /// drops only its own data.
    pub fn read(item: &Item, now: i64) -> Self {
        if is_tombstone(item) {
            return Row::Deleted;
        }
        let expires_at = match item.get("expires_at") {
            Some(AttributeValue::N(at)) => at.parse::<i64>().ok(),
            Some(_) => None,
            // Every row this crate writes has an expiry, but a row without one is never removed, so it stays usable.
            None => Some(i64::MAX),
        };
        match (expires_at, Row::from_item(item)) {
            (None, _) => Row::Unusable(Unusable::Malformed("expires_at")),
            // An expired row must not seal new data, because TTL can remove its key at any moment.
            (Some(at), _) if at <= now => Row::Unusable(Unusable::Expired),
            (_, Ok(row)) => row,
            (_, Err(RowError::Missing(name) | RowError::Malformed(name))) => {
                Row::Unusable(Unusable::Malformed(name))
            }
            (_, Err(RowError::NotWritable)) => Row::Unusable(Unusable::Malformed("row")),
        }
    }

    pub fn from_item(item: &Item) -> Result<Self, RowError> {
        if is_tombstone(item) {
            return Ok(Row::Deleted);
        }
        let team_id = string_number(item, "team_id")?;
        let key_month = string(item, "key_month")?;
        if let Some(wrapped) = item.get("wrapped_key") {
            return Ok(Row::TeamMonth {
                team_id,
                key_month,
                wrapped_key: blob(wrapped, "wrapped_key")?,
            });
        }
        let sealed = blob(
            item.get("sealed_key")
                .ok_or(RowError::Missing("sealed_key"))?,
            "sealed_key",
        )?;
        let nonce = blob(
            item.get("key_nonce")
                .ok_or(RowError::Missing("key_nonce"))?,
            "key_nonce",
        )?;
        let nonce: [u8; NONCE_BYTES] = nonce
            .try_into()
            .map_err(|_| RowError::Malformed("key_nonce"))?;
        Ok(Row::Session {
            team_id,
            key_month,
            sealed: SealedKey { sealed, nonce },
        })
    }
}

fn is_tombstone(item: &Item) -> bool {
    matches!(item.get("deleted"), Some(AttributeValue::Bool(true)))
}

/// The DynamoDB update expression and its values for a deletion. It sets the tombstone and removes the key material in
/// one write, and it keeps `expires_at`, so TTL removes the tombstone after every session that could open the key is
/// too old to be admitted.
pub fn tombstone_update() -> (String, Item) {
    (
        format!("SET deleted = :deleted REMOVE {}", KEY_MATERIAL.join(", ")),
        HashMap::from([(":deleted".to_owned(), AttributeValue::Bool(true))]),
    )
}

/// The item `tombstone_update` leaves in place of `item`.
pub fn tombstoned(item: &Item) -> Item {
    let mut item = item.clone();
    for name in KEY_MATERIAL {
        item.remove(name);
    }
    item.insert("deleted".to_owned(), AttributeValue::Bool(true));
    item
}

fn insert_common(item: &mut Item, team_id: i64, key_month: &str) -> Result<(), RowError> {
    item.insert("team_id".to_owned(), AttributeValue::N(team_id.to_string()));
    item.insert(
        "key_month".to_owned(),
        AttributeValue::S(key_month.to_owned()),
    );
    item.insert(
        "expires_at".to_owned(),
        AttributeValue::N(expires_at(key_month)?.to_string()),
    );
    Ok(())
}

fn string(item: &Item, name: &'static str) -> Result<String, RowError> {
    match item.get(name) {
        Some(AttributeValue::S(value)) => Ok(value.clone()),
        Some(_) => Err(RowError::Malformed(name)),
        None => Err(RowError::Missing(name)),
    }
}

fn string_number(item: &Item, name: &'static str) -> Result<i64, RowError> {
    match item.get(name) {
        Some(AttributeValue::N(value)) => value.parse().map_err(|_| RowError::Malformed(name)),
        Some(_) => Err(RowError::Malformed(name)),
        None => Err(RowError::Missing(name)),
    }
}

fn blob(value: &AttributeValue, name: &'static str) -> Result<Vec<u8>, RowError> {
    match value {
        AttributeValue::B(blob) => Ok(blob.as_ref().to_vec()),
        _ => Err(RowError::Malformed(name)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn keys_sessions_on_the_shards_the_v3_deletion_code_reads() {
        // Shard numbers from the Node `sessionShard`, which the Python deletion store mirrors.
        let cases = [
            ("019a2f3e-8c00-7000-8000-000000000007", 9),
            ("019a2f3e-8c00-7000-8000-000000000008", 11),
            ("00000000-0000-7000-8000-000000000000", 20),
            ("019a2f3e-8c00-7000-8000-00000000ffff", 31),
        ];
        for (session_id, shard) in cases {
            assert_eq!(
                TableKey::session(7, session_id).pk,
                format!("team:7:shard:{shard}")
            );
        }
    }

    fn session_row() -> Row {
        Row::Session {
            team_id: 7,
            key_month: "2026-10".to_owned(),
            sealed: SealedKey {
                sealed: vec![4; 48],
                nonce: [5; NONCE_BYTES],
            },
        }
    }

    fn team_month_row() -> Row {
        Row::TeamMonth {
            team_id: 7,
            key_month: "2026-10".to_owned(),
            wrapped_key: vec![1, 2, 3],
        }
    }

    #[test]
    fn rows_round_trip_and_expire_five_months_after_key_month() {
        let session = TableKey::session(7, "019a2f3e-8c00-7000-8000-000000000007");
        for row in [team_month_row(), session_row(), Row::Deleted] {
            let item = row.to_item(&session).unwrap();
            assert_eq!(Row::from_item(&item).unwrap(), row);
            assert_eq!(TableKey::from_item(&item).unwrap(), session);
        }
        let item = team_month_row()
            .to_item(&TableKey::team_month(7, "2026-10"))
            .unwrap();
        // 2027-03-01T00:00:00Z
        assert_eq!(
            item.get("expires_at"),
            Some(&AttributeValue::N("1803859200".to_owned()))
        );
        // 2027-05-01T00:00:00Z: the lifetime crosses the year.
        assert_eq!(expires_at("2026-12"), Ok(1_809_129_600));
        assert_eq!(
            expires_at("2026-10-15"),
            Err(RowError::Malformed("key_month"))
        );
        assert_eq!(key_month("2026-10-15"), "2026-10");
        assert_eq!(
            Row::from_item(&session.to_item()),
            Err(RowError::Missing("team_id"))
        );
    }

    #[test]
    fn reads_a_row_that_gives_no_key_as_unusable() {
        let key = TableKey::session(7, "019a2f3e-8c00-7000-8000-000000000007");
        let item = session_row().to_item(&key).unwrap();
        let expiry = 1_803_859_200;
        assert_eq!(Row::read(&item, expiry - 1), session_row());
        assert_eq!(Row::read(&item, expiry), Row::Unusable(Unusable::Expired));
        assert_eq!(Row::read(&tombstoned(&item), expiry + 1), Row::Deleted);

        let mut truncated = item.clone();
        truncated.insert(
            "key_nonce".to_owned(),
            AttributeValue::B(Blob::new(vec![5; 4])),
        );
        assert_eq!(
            Row::read(&truncated, 0),
            Row::Unusable(Unusable::Malformed("key_nonce"))
        );
        assert_eq!(
            Row::Unusable(Unusable::Expired).to_item(&key),
            Err(RowError::NotWritable)
        );
    }

    #[test]
    fn a_deletion_update_leaves_a_tombstone_with_no_key_material() {
        let (expression, values) = tombstone_update();
        assert_eq!(
            expression,
            "SET deleted = :deleted REMOVE wrapped_key, sealed_key, key_nonce"
        );
        assert_eq!(values[":deleted"], AttributeValue::Bool(true));
        for (key, row) in [
            (TableKey::team_month(7, "2026-10"), team_month_row()),
            (
                TableKey::session(7, "019a2f3e-8c00-7000-8000-000000000007"),
                session_row(),
            ),
        ] {
            let item = tombstoned(&row.to_item(&key).unwrap());
            assert_eq!(Row::from_item(&item), Ok(Row::Deleted));
            assert!(KEY_MATERIAL.iter().all(|name| !item.contains_key(*name)));
        }
    }
}
