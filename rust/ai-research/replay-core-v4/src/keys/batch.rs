//! Resolves the keys for one recorder flush, storing the new ones before anything is sealed with them.

use std::collections::{BTreeSet, HashMap};
use std::fmt;

use futures::stream::{self, StreamExt, TryStreamExt};
use rand::RngCore;

use super::kms::{CachedKms, KeyWrapper, KmsError};
use super::rows::{Row, TableKey};
use super::table::{KeyTable, PutOutcome, TableError};
use crate::seal::{open_session_key, seal_session_key, SealedKey, WrappingContext};

/// How many conditional puts or team day keys one flush resolves at once, as in v3. `AwsKms` bounds the KMS calls.
const PUT_CONCURRENCY: usize = 32;

/// A failure that may pass on a retry, so the flush fails and runs again. A failure that one row causes drops only
/// that row's sessions instead.
#[derive(Debug, thiserror::Error)]
pub enum KeyError {
    #[error(transparent)]
    Table(#[from] TableError),
    #[error(transparent)]
    Kms(#[from] KmsError),
}

/// A session in a flush.
#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct SessionId {
    pub team_id: i64,
    pub session_id: String,
}

/// Why a flush leaves a session out.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DropCause {
    /// A deletion tombstoned the session or its team.
    Deleted,
    /// The session's key row names a team day key that is gone, so nothing sealed for it can be opened.
    KeyLost,
    /// The session's key row, or the team day key it is sealed under, is stored but gives no key: the seal does not
    /// open, KMS refuses the wrapped key, or the row is malformed or expired. The row stays, so no new key replaces it.
    KeyUnusable,
}

impl DropCause {
    /// The metric label.
    pub fn as_str(self) -> &'static str {
        match self {
            DropCause::Deleted => "deleted",
            DropCause::KeyLost => "key_lost",
            DropCause::KeyUnusable => "key_unusable",
        }
    }
}

#[derive(Clone, PartialEq, Eq)]
pub struct SessionKey {
    pub key: [u8; 32],
    /// The day the session key was first stored. Its row expires 90 days after that day.
    pub key_day: String,
}

impl fmt::Debug for SessionKey {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("SessionKey")
            .field("key", &"<redacted>")
            .field("key_day", &self.key_day)
            .finish()
    }
}

/// The keys a flush seals with.
#[derive(Default)]
pub struct FlushKeys {
    pub sessions: HashMap<SessionId, SessionKey>,
    /// Team day keys of the write day, for the flush's images.
    pub team_days: HashMap<i64, [u8; 32]>,
    pub dropped: Vec<(SessionId, DropCause)>,
}

impl fmt::Debug for FlushKeys {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("FlushKeys")
            .field("sessions", &self.sessions)
            .field("team_days", &self.team_days.keys())
            .field("dropped", &self.dropped)
            .finish()
    }
}

enum TeamDay {
    Key([u8; 32]),
    Deleted,
    Unavailable(DropCause),
}

type TeamDays = HashMap<(i64, String), TeamDay>;

pub struct KeyStore<T, W> {
    table: T,
    kms: CachedKms<W>,
}

impl<T: KeyTable, W: KeyWrapper> KeyStore<T, W> {
    pub fn new(table: T, kms: CachedKms<W>) -> Self {
        Self { table, kms }
    }

    /// Resolves a key for every session, storing the new ones. Call it before sealing anything for the flush: a key
    /// that is not stored yet cannot open what it sealed if this process dies.
    pub async fn keys_for_flush(
        &self,
        sessions: &[SessionId],
        write_day: &str,
    ) -> Result<FlushKeys, KeyError> {
        let teams: BTreeSet<i64> = sessions.iter().map(|s| s.team_id).collect();
        let mut keys: Vec<TableKey> = teams
            .iter()
            .map(|&team| TableKey::team_day(team, write_day))
            .collect();
        keys.extend(
            sessions
                .iter()
                .map(|s| TableKey::session(s.team_id, &s.session_id)),
        );
        let rows = self.table.batch_get(&keys).await?;

        // The futures are built before they enter the stream, which keeps the flush future `Send`.
        let write_days: Vec<_> = teams
            .iter()
            .map(|&team| {
                let row = rows.get(&TableKey::team_day(team, write_day));
                async move {
                    let team_day = self.write_day_key(team, write_day, row).await?;
                    Ok::<_, KeyError>(((team, write_day.to_owned()), team_day))
                }
            })
            .collect();
        let mut team_days: TeamDays = stream::iter(write_days)
            .buffer_unordered(PUT_CONCURRENCY)
            .try_collect()
            .await?;

        // A session stored on an earlier day is sealed under that day's team key, which the first read did not ask for.
        let earlier: BTreeSet<(i64, String)> = rows
            .values()
            .filter_map(|row| match row {
                Row::Session {
                    team_id, key_day, ..
                } => Some((*team_id, key_day.clone())),
                _ => None,
            })
            .collect();
        self.resolve_team_days(earlier, &mut team_days).await?;

        let mut flush = FlushKeys::default();
        let mut new_sessions = Vec::new();
        for session in sessions {
            match rows.get(&TableKey::session(session.team_id, &session.session_id)) {
                Some(Row::Session {
                    key_day, sealed, ..
                }) => match open_stored(session, key_day, sealed, &team_days) {
                    Ok(key) => {
                        flush.sessions.insert(session.clone(), key);
                    }
                    Err(cause) => flush.dropped.push((session.clone(), cause)),
                },
                Some(Row::Deleted) => flush.dropped.push((session.clone(), DropCause::Deleted)),
                Some(_) => flush
                    .dropped
                    .push((session.clone(), DropCause::KeyUnusable)),
                None => match &team_days[&(session.team_id, write_day.to_owned())] {
                    TeamDay::Key(team_key) => new_sessions.push((session.clone(), *team_key)),
                    TeamDay::Deleted => flush.dropped.push((session.clone(), DropCause::Deleted)),
                    TeamDay::Unavailable(cause) => flush.dropped.push((session.clone(), *cause)),
                },
            }
        }

        let stored: Vec<_> = stream::iter(new_sessions)
            .map(|(session, team_key)| self.store_new_session(session, team_key, write_day))
            .buffer_unordered(PUT_CONCURRENCY)
            .try_collect()
            .await?;
        let winners: BTreeSet<(i64, String)> = stored
            .iter()
            .filter_map(|(session, outcome)| match outcome {
                NewSession::Winner(key_day, _) => Some((session.team_id, key_day.clone())),
                _ => None,
            })
            .collect();
        self.resolve_team_days(winners, &mut team_days).await?;
        for (session, outcome) in stored {
            match outcome {
                NewSession::Key(key) => {
                    flush.sessions.insert(session, key);
                }
                NewSession::Winner(key_day, sealed) => {
                    match open_stored(&session, &key_day, &sealed, &team_days) {
                        Ok(key) => {
                            flush.sessions.insert(session, key);
                        }
                        Err(cause) => flush.dropped.push((session, cause)),
                    }
                }
                NewSession::Dropped(cause) => flush.dropped.push((session, cause)),
            }
        }

        for ((team, day), team_day) in team_days {
            if let (TeamDay::Key(key), true) = (team_day, day == write_day) {
                flush.team_days.insert(team, key);
            }
        }
        Ok(flush)
    }

    /// The team key of the write day: the stored one, or a new one stored now.
    async fn write_day_key(
        &self,
        team: i64,
        write_day: &str,
        row: Option<&Row>,
    ) -> Result<TeamDay, KeyError> {
        if let Some(row) = row {
            return self.stored_team_day(team, write_day, Some(row)).await;
        }
        let context = WrappingContext {
            team_id: team,
            key_day: write_day.to_owned(),
            session_id: None,
        };
        let generated = self.kms.generate(&context).await?;
        let candidate = Row::TeamDay {
            team_id: team,
            key_day: write_day.to_owned(),
            wrapped_key: generated.wrapped.clone(),
        };
        match self
            .table
            .put_if_absent(&TableKey::team_day(team, write_day), &candidate)
            .await?
        {
            PutOutcome::Stored => {
                self.kms.remember(&context, &generated).await;
                Ok(TeamDay::Key(generated.plaintext))
            }
            PutOutcome::Existing(winner) => {
                self.stored_team_day(team, write_day, Some(&winner)).await
            }
        }
    }

    async fn resolve_team_days(
        &self,
        slots: BTreeSet<(i64, String)>,
        team_days: &mut TeamDays,
    ) -> Result<(), KeyError> {
        let slots: Vec<_> = slots
            .into_iter()
            .filter(|slot| !team_days.contains_key(slot))
            .collect();
        if slots.is_empty() {
            return Ok(());
        }
        let keys: Vec<_> = slots
            .iter()
            .map(|(team, day)| TableKey::team_day(*team, day))
            .collect();
        let rows = self.table.batch_get(&keys).await?;
        let unwraps: Vec<_> = slots
            .into_iter()
            .map(|(team, day)| {
                let row = rows.get(&TableKey::team_day(team, &day));
                async move {
                    let team_day = self.stored_team_day(team, &day, row).await?;
                    Ok::<_, KeyError>(((team, day), team_day))
                }
            })
            .collect();
        let resolved: Vec<_> = stream::iter(unwraps)
            .buffer_unordered(PUT_CONCURRENCY)
            .try_collect()
            .await?;
        team_days.extend(resolved);
        Ok(())
    }

    /// KMS refusing the blob drops that team day's sessions, and any other KMS failure fails the flush.
    async fn stored_team_day(
        &self,
        team: i64,
        key_day: &str,
        row: Option<&Row>,
    ) -> Result<TeamDay, KeyError> {
        let wrapped = match row {
            Some(Row::TeamDay { wrapped_key, .. }) => wrapped_key,
            Some(Row::Deleted) => return Ok(TeamDay::Deleted),
            Some(_) => return Ok(TeamDay::Unavailable(DropCause::KeyUnusable)),
            None => return Ok(TeamDay::Unavailable(DropCause::KeyLost)),
        };
        let context = WrappingContext {
            team_id: team,
            key_day: key_day.to_owned(),
            session_id: None,
        };
        match self.kms.unwrap(&context, wrapped).await {
            Ok(key) => Ok(TeamDay::Key(key)),
            Err(KmsError::Rejected(_) | KmsError::InvalidKey) => {
                Ok(TeamDay::Unavailable(DropCause::KeyUnusable))
            }
            Err(error) => Err(error.into()),
        }
    }

    async fn store_new_session(
        &self,
        session: SessionId,
        team_key: [u8; 32],
        write_day: &str,
    ) -> Result<(SessionId, NewSession), KeyError> {
        let mut key = [0u8; 32];
        rand::thread_rng().fill_bytes(&mut key);
        let context = WrappingContext {
            team_id: session.team_id,
            key_day: write_day.to_owned(),
            session_id: Some(session.session_id.clone()),
        };
        let row = Row::Session {
            team_id: session.team_id,
            key_day: write_day.to_owned(),
            sealed: seal_session_key(&team_key, &context, &key),
        };
        let outcome = match self
            .table
            .put_if_absent(
                &TableKey::session(session.team_id, &session.session_id),
                &row,
            )
            .await?
        {
            PutOutcome::Stored => NewSession::Key(SessionKey {
                key,
                key_day: write_day.to_owned(),
            }),
            PutOutcome::Existing(Row::Session {
                key_day, sealed, ..
            }) => NewSession::Winner(key_day, sealed),
            PutOutcome::Existing(Row::Deleted) => NewSession::Dropped(DropCause::Deleted),
            PutOutcome::Existing(_) => NewSession::Dropped(DropCause::KeyUnusable),
        };
        Ok((session, outcome))
    }
}

fn open_stored(
    session: &SessionId,
    key_day: &str,
    sealed: &SealedKey,
    team_days: &TeamDays,
) -> Result<SessionKey, DropCause> {
    let team_key = match team_days.get(&(session.team_id, key_day.to_owned())) {
        Some(TeamDay::Key(key)) => key,
        Some(TeamDay::Deleted) => return Err(DropCause::Deleted),
        Some(TeamDay::Unavailable(cause)) => return Err(*cause),
        None => return Err(DropCause::KeyLost),
    };
    let context = WrappingContext {
        team_id: session.team_id,
        key_day: key_day.to_owned(),
        session_id: Some(session.session_id.clone()),
    };
    // A seal opens under one team day key only, so a failure means the row and that key disagree.
    let key = open_session_key(team_key, &context, sealed).map_err(|_| DropCause::KeyUnusable)?;
    Ok(SessionKey {
        key,
        key_day: key_day.to_owned(),
    })
}

enum NewSession {
    Key(SessionKey),
    /// Another writer stored this session's key first, possibly on another day. The flush adopts it.
    Winner(String, SealedKey),
    /// The put met a tombstone or an unusable row, which it never writes over.
    Dropped(DropCause),
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use async_trait::async_trait;

    use super::*;
    use crate::keys::kms::DataKey;
    use crate::keys::memory::MemoryTable;
    use crate::keys::rows::Unusable;

    /// Wraps a key by prefixing its context, so unwrapping under another context fails as KMS would.
    #[derive(Default)]
    struct FakeKms {
        /// Every unwrap times out, as in a KMS outage.
        outage: bool,
    }

    fn label(context: &WrappingContext) -> Vec<u8> {
        format!("{:?}", context.entries()).into_bytes()
    }

    #[async_trait]
    impl KeyWrapper for FakeKms {
        async fn generate(&self, context: &WrappingContext) -> Result<DataKey, KmsError> {
            let plaintext: [u8; 32] = rand::random();
            Ok(DataKey {
                plaintext,
                wrapped: [label(context), plaintext.to_vec()].concat(),
            })
        }

        async fn unwrap(
            &self,
            context: &WrappingContext,
            wrapped: &[u8],
        ) -> Result<[u8; 32], KmsError> {
            if self.outage {
                return Err(KmsError::Timeout);
            }
            let label = label(context);
            if !wrapped.starts_with(&label) {
                return Err(KmsError::Rejected("encryption context mismatch".to_owned()));
            }
            wrapped[label.len()..]
                .try_into()
                .map_err(|_| KmsError::InvalidKey)
        }
    }

    fn store(table: MemoryTable) -> KeyStore<MemoryTable, FakeKms> {
        store_with(table, FakeKms::default())
    }

    fn store_with(table: MemoryTable, kms: FakeKms) -> KeyStore<MemoryTable, FakeKms> {
        KeyStore::new(table, CachedKms::new(kms, 100, Duration::from_secs(60)))
    }

    fn session(team_id: i64, n: u32) -> SessionId {
        SessionId {
            team_id,
            session_id: format!("019a2f3e-8c00-7000-8000-{n:012}"),
        }
    }

    /// Another pod: a fresh process that reads what the first one stored.
    fn rows_of(store: &KeyStore<MemoryTable, FakeKms>) -> MemoryTable {
        MemoryTable {
            rows: std::sync::Mutex::new(store.table.rows.lock().unwrap().clone()),
            ..Default::default()
        }
    }

    #[tokio::test]
    async fn a_new_session_key_is_stored_and_found_again_on_a_later_day() {
        let first = store(MemoryTable::default());
        let a = session(7, 1);
        let day_one = first
            .keys_for_flush(std::slice::from_ref(&a), "2026-10-15")
            .await
            .unwrap();
        let key = day_one.sessions[&a].clone();
        assert_eq!(key.key_day, "2026-10-15");
        let printed = format!("{day_one:?}");
        for secret in [key.key, day_one.team_days[&7]] {
            assert!(!printed.contains(&format!("{secret:?}")[1..20]));
        }

        // The session keeps its first key across a new day, while the team gets that day's key for its images.
        let second = store(rows_of(&first));
        let day_two = second
            .keys_for_flush(std::slice::from_ref(&a), "2026-10-16")
            .await
            .unwrap();
        assert_eq!(day_two.sessions[&a], key);
        assert_ne!(day_two.team_days[&7], day_one.team_days[&7]);
    }

    #[tokio::test]
    async fn adopts_the_key_another_writer_stored_first() {
        let a = session(7, 1);
        let winner = store(MemoryTable::default());
        let winning = winner
            .keys_for_flush(std::slice::from_ref(&a), "2026-10-15")
            .await
            .unwrap();

        // The loser read before the winner wrote, so it reaches the conditional put with a candidate of its own.
        let loser = store(rows_of(&winner));
        let (_, outcome) = loser
            .store_new_session(a.clone(), [9; 32], "2026-10-15")
            .await
            .unwrap();
        let NewSession::Winner(key_day, sealed) = outcome else {
            panic!("the put must lose")
        };
        let mut team_days = HashMap::new();
        loser
            .resolve_team_days(BTreeSet::from([(7, key_day.clone())]), &mut team_days)
            .await
            .unwrap();
        let adopted = open_stored(&a, &key_day, &sealed, &team_days).unwrap();
        assert_eq!(adopted, winning.sessions[&a]);
    }

    #[tokio::test]
    async fn drops_sessions_a_deletion_tombstoned() {
        let table = MemoryTable::default();
        let (deleted_session, deleted_team, kept) = (session(7, 1), session(8, 2), session(7, 3));
        table.store(
            TableKey::session(7, &deleted_session.session_id),
            Row::Deleted,
        );
        table.store(TableKey::team_day(8, "2026-10-15"), Row::Deleted);
        let store = store(table);

        let flush = store
            .keys_for_flush(
                &[deleted_session.clone(), deleted_team.clone(), kept.clone()],
                "2026-10-15",
            )
            .await
            .unwrap();
        assert_eq!(flush.sessions.keys().collect::<Vec<_>>(), vec![&kept]);
        let mut dropped = flush.dropped.clone();
        dropped.sort_by(|a, b| a.0.cmp(&b.0));
        assert_eq!(
            dropped,
            vec![
                (deleted_session, DropCause::Deleted),
                (deleted_team, DropCause::Deleted)
            ]
        );
        assert!(!flush.team_days.contains_key(&8));
    }

    #[tokio::test]
    async fn a_tombstoned_team_day_drops_the_sessions_sealed_under_it_on_later_days() {
        let first = store(MemoryTable::default());
        let (a, b) = (session(7, 1), session(7, 2));
        first
            .keys_for_flush(std::slice::from_ref(&a), "2026-10-15")
            .await
            .unwrap();
        let rows = rows_of(&first);
        let day_one = TableKey::team_day(7, "2026-10-15");
        rows.store(day_one.clone(), Row::Deleted);

        let second = store(rows);
        let flush = second
            .keys_for_flush(&[a.clone(), b.clone()], "2026-10-16")
            .await
            .unwrap();
        assert_eq!(flush.dropped, vec![(a, DropCause::Deleted)]);
        assert_eq!(flush.sessions.keys().collect::<Vec<_>>(), vec![&b]);
        assert_eq!(second.table.rows.lock().unwrap()[&day_one], Row::Deleted);
    }

    #[tokio::test]
    async fn a_put_that_meets_a_tombstone_drops_its_data_and_keeps_the_tombstone() {
        // A deletion lands between the flush's read and its conditional put.
        let a = session(7, 1);
        let (team_day, session_row) = (
            TableKey::team_day(8, "2026-10-15"),
            TableKey::session(7, &a.session_id),
        );
        let table = MemoryTable::default();
        table.store(team_day.clone(), Row::Deleted);
        table.store(session_row.clone(), Row::Deleted);
        let store = store(table);

        let (_, outcome) = store
            .store_new_session(a, [9; 32], "2026-10-15")
            .await
            .unwrap();
        assert!(matches!(outcome, NewSession::Dropped(DropCause::Deleted)));
        let team = store.write_day_key(8, "2026-10-15", None).await.unwrap();
        assert!(matches!(team, TeamDay::Deleted));
        let rows = store.table.rows.lock().unwrap();
        assert_eq!(rows[&team_day], Row::Deleted);
        assert_eq!(rows[&session_row], Row::Deleted);
    }

    #[tokio::test]
    async fn an_unusable_key_row_drops_only_its_sessions_and_an_outage_fails_the_flush() {
        let (a, b, c) = (session(7, 1), session(8, 2), session(9, 3));
        let first = store(MemoryTable::default());
        first
            .keys_for_flush(&[a.clone(), b.clone(), c.clone()], "2026-10-15")
            .await
            .unwrap();
        let rows = rows_of(&first);
        // A seal that does not open, a wrapped key KMS refuses, and an expired row.
        rows.store(
            TableKey::session(7, &a.session_id),
            Row::Session {
                team_id: 7,
                key_day: "2026-10-15".to_owned(),
                sealed: SealedKey {
                    sealed: vec![1; 48],
                    nonce: [2; 12],
                },
            },
        );
        rows.store(
            TableKey::team_day(8, "2026-10-15"),
            Row::TeamDay {
                team_id: 8,
                key_day: "2026-10-15".to_owned(),
                wrapped_key: vec![3; 40],
            },
        );
        let expired = Row::Unusable(Unusable::Expired);
        rows.store(TableKey::session(9, &c.session_id), expired.clone());

        let (d, e) = (session(7, 4), session(8, 5));
        let second = store(rows);
        let all = [a.clone(), b.clone(), c.clone(), d.clone(), e.clone()];
        let flush = second.keys_for_flush(&all, "2026-10-16").await.unwrap();
        let mut dropped = flush.dropped.clone();
        dropped.sort_by(|x, y| x.0.cmp(&y.0));
        assert_eq!(
            dropped,
            [a, b, c.clone()].map(|s| (s, DropCause::KeyUnusable))
        );
        let mut kept: Vec<_> = flush.sessions.keys().cloned().collect();
        kept.sort();
        assert_eq!(kept, vec![d, e]);
        assert_eq!(
            second.table.rows.lock().unwrap()[&TableKey::session(9, &c.session_id)],
            expired
        );

        let during_outage = store_with(rows_of(&second), FakeKms { outage: true });
        assert!(matches!(
            during_outage.keys_for_flush(&all, "2026-10-16").await,
            Err(KeyError::Kms(KmsError::Timeout))
        ));
    }
}
