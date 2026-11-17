//! Resolves the keys for one recorder flush, storing the new ones before anything is sealed with them.

use std::collections::{BTreeSet, HashMap};
use std::fmt;

use futures::stream::{self, StreamExt, TryStreamExt};
use rand::RngCore;

use super::kms::{CachedKms, KeyWrapper, KmsError};
use super::rows::{may_create_key, session_key_month, Row, TableKey};
use super::table::{KeyTable, PutOutcome, TableError};
use crate::seal::{open_session_key, seal_session_key, SealedKey, WrappingContext};

/// How many conditional puts or team month keys one flush resolves at once, as in v3. `AwsKms` bounds the KMS calls.
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
    /// The session's key row names a team month key that is gone, so nothing sealed for it can be opened.
    KeyLost,
    /// The session's key row, or the team month key it is sealed under, is stored but gives no key: the seal does not
    /// open, KMS refuses the wrapped key, or the row is malformed or expired. The row stays, so no new key replaces it.
    KeyUnusable,
    /// The session ID is not a UUIDv7.
    NoStartMonth,
    /// The session is new and started in a month that a flush on this day may not create a key for.
    StartMonthOutOfRange,
}

impl DropCause {
    /// The metric label.
    pub fn as_str(self) -> &'static str {
        match self {
            DropCause::Deleted => "deleted",
            DropCause::KeyLost => "key_lost",
            DropCause::KeyUnusable => "key_unusable",
            DropCause::NoStartMonth => "no_start_month",
            DropCause::StartMonthOutOfRange => "start_month_out_of_range",
        }
    }
}

#[derive(Clone, PartialEq, Eq)]
pub struct SessionKey {
    pub key: [u8; 32],
    /// The key row's month. Its team month key also seals the session's images, and the row expires five months later.
    pub key_month: String,
}

impl fmt::Debug for SessionKey {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("SessionKey")
            .field("key", &"<redacted>")
            .field("key_month", &self.key_month)
            .finish()
    }
}

/// The keys a flush seals with.
#[derive(Default)]
pub struct FlushKeys {
    pub sessions: HashMap<SessionId, SessionKey>,
    pub team_months: HashMap<(i64, String), [u8; 32]>,
    pub dropped: Vec<(SessionId, DropCause)>,
}

impl FlushKeys {
    pub fn team_month(&self, team_id: i64, key_month: &str) -> Option<&[u8; 32]> {
        self.team_months.get(&(team_id, key_month.to_owned()))
    }

    /// A session's key, and the team month key that seals both it and every image the session shows.
    pub fn session(&self, session: &SessionId) -> Option<(&SessionKey, &[u8; 32])> {
        let key = self.sessions.get(session)?;
        Some((key, self.team_month(session.team_id, &key.key_month)?))
    }
}

impl fmt::Debug for FlushKeys {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("FlushKeys")
            .field("sessions", &self.sessions)
            .field("team_months", &self.team_months.keys())
            .field("dropped", &self.dropped)
            .finish()
    }
}

enum TeamMonth {
    Key([u8; 32]),
    Deleted,
    Unavailable(DropCause),
}

type TeamMonths = HashMap<(i64, String), TeamMonth>;

pub struct KeyStore<T, W> {
    table: T,
    kms: CachedKms<W>,
}

impl<T: KeyTable, W: KeyWrapper> KeyStore<T, W> {
    pub fn new(table: T, kms: CachedKms<W>) -> Self {
        Self { table, kms }
    }

    /// Resolves a key for every session, storing the new ones. Call it before sealing anything for the flush: a key
    /// that is not stored yet cannot open what it sealed if this process dies. A new key takes its session's start
    /// month, as in v3, so that one team month key seals the session's blocks and images whatever day they are written.
    /// The flush writes on `write_day`, which bounds the months it may create keys for.
    pub async fn keys_for_flush(
        &self,
        sessions: &[SessionId],
        write_day: &str,
    ) -> Result<FlushKeys, KeyError> {
        let mut flush = FlushKeys::default();
        let mut started = Vec::with_capacity(sessions.len());
        for session in sessions {
            match session_key_month(&session.session_id) {
                Some(month) => {
                    let row_key = TableKey::session(session.team_id, &session.session_id);
                    started.push((session, month, row_key));
                }
                None => flush
                    .dropped
                    .push((session.clone(), DropCause::NoStartMonth)),
            }
        }
        let start_months: BTreeSet<(i64, &str)> = started
            .iter()
            .map(|(session, month, _)| (session.team_id, month.as_str()))
            .collect();
        let mut keys: Vec<TableKey> = start_months
            .iter()
            .map(|&(team, month)| TableKey::team_month(team, month))
            .collect();
        keys.extend(started.iter().map(|(_, _, row_key)| row_key.clone()));
        let rows = self.table.batch_get(&keys).await?;

        // Only a new session creates a team month key. Every other start month resolves from this read, so a flush of
        // sessions keyed by their start month reads the table once.
        let creates: BTreeSet<(i64, &str)> = started
            .iter()
            .filter(|(_, month, row_key)| {
                !rows.contains_key(row_key) && may_create_key(month, write_day)
            })
            .map(|(session, month, _)| (session.team_id, month.as_str()))
            .collect();
        // The futures are built before they enter the stream, which keeps the flush future `Send`.
        let first_read: Vec<_> = start_months
            .iter()
            .map(|&(team, month)| {
                let row = rows.get(&TableKey::team_month(team, month));
                let create = creates.contains(&(team, month));
                async move {
                    let team_month = if create {
                        self.team_month_or_new(team, month, row).await?
                    } else {
                        self.stored_team_month(team, month, row).await?
                    };
                    Ok::<_, KeyError>(((team, month.to_owned()), team_month))
                }
            })
            .collect();
        let mut team_months: TeamMonths = stream::iter(first_read)
            .buffer_unordered(PUT_CONCURRENCY)
            .try_collect()
            .await?;

        let stored_months: BTreeSet<(i64, String)> = rows
            .values()
            .filter_map(|row| match row {
                Row::Session {
                    team_id, key_month, ..
                } => Some((*team_id, key_month.clone())),
                _ => None,
            })
            .collect();
        self.resolve_team_months(stored_months, &mut team_months)
            .await?;

        let mut new_sessions = Vec::new();
        for (session, start_month, row_key) in started {
            match rows.get(&row_key) {
                Some(Row::Session {
                    key_month, sealed, ..
                }) => match open_stored(session, key_month, sealed, &team_months) {
                    Ok(key) => {
                        flush.sessions.insert(session.clone(), key);
                    }
                    Err(cause) => flush.dropped.push((session.clone(), cause)),
                },
                Some(Row::Deleted) => flush.dropped.push((session.clone(), DropCause::Deleted)),
                Some(_) => flush
                    .dropped
                    .push((session.clone(), DropCause::KeyUnusable)),
                None if !may_create_key(&start_month, write_day) => flush
                    .dropped
                    .push((session.clone(), DropCause::StartMonthOutOfRange)),
                None => match &team_months[&(session.team_id, start_month.clone())] {
                    TeamMonth::Key(team_key) => {
                        new_sessions.push((session.clone(), *team_key, start_month))
                    }
                    TeamMonth::Deleted => flush.dropped.push((session.clone(), DropCause::Deleted)),
                    TeamMonth::Unavailable(cause) => flush.dropped.push((session.clone(), *cause)),
                },
            }
        }

        let stored: Vec<_> = stream::iter(new_sessions)
            .map(|(session, team_key, key_month)| {
                self.store_new_session(session, team_key, key_month)
            })
            .buffer_unordered(PUT_CONCURRENCY)
            .try_collect()
            .await?;
        let winners: BTreeSet<(i64, String)> = stored
            .iter()
            .filter_map(|(session, outcome)| match outcome {
                NewSession::Winner(key_month, _) => Some((session.team_id, key_month.clone())),
                _ => None,
            })
            .collect();
        self.resolve_team_months(winners, &mut team_months).await?;
        for (session, outcome) in stored {
            match outcome {
                NewSession::Key(key) => {
                    flush.sessions.insert(session, key);
                }
                NewSession::Winner(key_month, sealed) => {
                    match open_stored(&session, &key_month, &sealed, &team_months) {
                        Ok(key) => {
                            flush.sessions.insert(session, key);
                        }
                        Err(cause) => flush.dropped.push((session, cause)),
                    }
                }
                NewSession::Dropped(cause) => flush.dropped.push((session, cause)),
            }
        }

        for (slot, team_month) in team_months {
            if let TeamMonth::Key(key) = team_month {
                flush.team_months.insert(slot, key);
            }
        }
        Ok(flush)
    }

    async fn team_month_or_new(
        &self,
        team: i64,
        key_month: &str,
        row: Option<&Row>,
    ) -> Result<TeamMonth, KeyError> {
        if let Some(row) = row {
            return self.stored_team_month(team, key_month, Some(row)).await;
        }
        let context = WrappingContext {
            team_id: team,
            key_month: key_month.to_owned(),
            session_id: None,
        };
        let generated = self.kms.generate(&context).await?;
        let candidate = Row::TeamMonth {
            team_id: team,
            key_month: key_month.to_owned(),
            wrapped_key: generated.wrapped.clone(),
        };
        match self
            .table
            .put_if_absent(&TableKey::team_month(team, key_month), &candidate)
            .await?
        {
            PutOutcome::Stored => {
                self.kms.remember(&context, &generated).await;
                Ok(TeamMonth::Key(generated.plaintext))
            }
            PutOutcome::Existing(winner) => {
                self.stored_team_month(team, key_month, Some(&winner)).await
            }
        }
    }

    async fn resolve_team_months(
        &self,
        slots: BTreeSet<(i64, String)>,
        team_months: &mut TeamMonths,
    ) -> Result<(), KeyError> {
        let slots: Vec<_> = slots
            .into_iter()
            .filter(|slot| !team_months.contains_key(slot))
            .collect();
        if slots.is_empty() {
            return Ok(());
        }
        let keys: Vec<_> = slots
            .iter()
            .map(|(team, month)| TableKey::team_month(*team, month))
            .collect();
        let rows = self.table.batch_get(&keys).await?;
        let unwraps: Vec<_> = slots
            .into_iter()
            .map(|(team, month)| {
                let row = rows.get(&TableKey::team_month(team, &month));
                async move {
                    let team_month = self.stored_team_month(team, &month, row).await?;
                    Ok::<_, KeyError>(((team, month), team_month))
                }
            })
            .collect();
        let resolved: Vec<_> = stream::iter(unwraps)
            .buffer_unordered(PUT_CONCURRENCY)
            .try_collect()
            .await?;
        team_months.extend(resolved);
        Ok(())
    }

    /// KMS refusing the blob drops that team month's sessions, and any other KMS failure fails the flush.
    async fn stored_team_month(
        &self,
        team: i64,
        key_month: &str,
        row: Option<&Row>,
    ) -> Result<TeamMonth, KeyError> {
        let wrapped = match row {
            Some(Row::TeamMonth { wrapped_key, .. }) => wrapped_key,
            Some(Row::Deleted) => return Ok(TeamMonth::Deleted),
            Some(_) => return Ok(TeamMonth::Unavailable(DropCause::KeyUnusable)),
            None => return Ok(TeamMonth::Unavailable(DropCause::KeyLost)),
        };
        let context = WrappingContext {
            team_id: team,
            key_month: key_month.to_owned(),
            session_id: None,
        };
        match self.kms.unwrap(&context, wrapped).await {
            Ok(key) => Ok(TeamMonth::Key(key)),
            Err(KmsError::Rejected(_) | KmsError::InvalidKey) => {
                Ok(TeamMonth::Unavailable(DropCause::KeyUnusable))
            }
            Err(error) => Err(error.into()),
        }
    }

    async fn store_new_session(
        &self,
        session: SessionId,
        team_key: [u8; 32],
        key_month: String,
    ) -> Result<(SessionId, NewSession), KeyError> {
        let mut key = [0u8; 32];
        rand::thread_rng().fill_bytes(&mut key);
        let context = WrappingContext {
            team_id: session.team_id,
            key_month: key_month.clone(),
            session_id: Some(session.session_id.clone()),
        };
        let row = Row::Session {
            team_id: session.team_id,
            key_month: key_month.clone(),
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
            PutOutcome::Stored => NewSession::Key(SessionKey { key, key_month }),
            PutOutcome::Existing(Row::Session {
                key_month, sealed, ..
            }) => NewSession::Winner(key_month, sealed),
            PutOutcome::Existing(Row::Deleted) => NewSession::Dropped(DropCause::Deleted),
            PutOutcome::Existing(_) => NewSession::Dropped(DropCause::KeyUnusable),
        };
        Ok((session, outcome))
    }
}

fn open_stored(
    session: &SessionId,
    key_month: &str,
    sealed: &SealedKey,
    team_months: &TeamMonths,
) -> Result<SessionKey, DropCause> {
    let team_key = match team_months.get(&(session.team_id, key_month.to_owned())) {
        Some(TeamMonth::Key(key)) => key,
        Some(TeamMonth::Deleted) => return Err(DropCause::Deleted),
        Some(TeamMonth::Unavailable(cause)) => return Err(*cause),
        None => return Err(DropCause::KeyLost),
    };
    let context = WrappingContext {
        team_id: session.team_id,
        key_month: key_month.to_owned(),
        session_id: Some(session.session_id.clone()),
    };
    // A seal opens under one team month key only, so a failure means the row and that key disagree.
    let key = open_session_key(team_key, &context, sealed).map_err(|_| DropCause::KeyUnusable)?;
    Ok(SessionKey {
        key,
        key_month: key_month.to_owned(),
    })
}

enum NewSession {
    Key(SessionKey),
    /// Another writer stored this session's key first, possibly in another month. The flush adopts it.
    Winner(String, SealedKey),
    /// The put met a tombstone or an unusable row, which it never writes over.
    Dropped(DropCause),
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::Ordering;
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

    const MID_AUGUST: &str = "01a0054b-0e00";
    const MID_OCTOBER: &str = "01a13f6e-fa00";
    const END_OF_OCTOBER: &str = "01a19467-e7ff";
    const START_OF_NOVEMBER: &str = "01a19467-e800";

    fn session_at(start: &str, team_id: i64, n: u32) -> SessionId {
        SessionId {
            team_id,
            session_id: format!("{start}-7000-8000-{n:012}"),
        }
    }

    fn session(team_id: i64, n: u32) -> SessionId {
        session_at(MID_OCTOBER, team_id, n)
    }

    /// Another pod: a fresh process that reads what the first one stored.
    fn rows_of(store: &KeyStore<MemoryTable, FakeKms>) -> MemoryTable {
        MemoryTable {
            rows: std::sync::Mutex::new(store.table.rows.lock().unwrap().clone()),
            ..Default::default()
        }
    }

    #[tokio::test]
    async fn a_session_keeps_the_month_it_started_in_for_its_key_and_images() {
        let first = store(MemoryTable::default());
        let a = session_at(END_OF_OCTOBER, 7, 1);
        let october = first
            .keys_for_flush(std::slice::from_ref(&a), "2026-10-31")
            .await
            .unwrap();
        let (key, october_team_key) = october.session(&a).unwrap();
        assert_eq!(key.key_month, "2026-10");
        let printed = format!("{october:?}");
        for secret in [key.key, *october_team_key] {
            assert!(!printed.contains(&format!("{secret:?}")[1..20]));
        }

        // Written in November, the October session still seals its images under October's key.
        let b = session_at(START_OF_NOVEMBER, 7, 2);
        let second = store(rows_of(&first));
        let november = second
            .keys_for_flush(&[a.clone(), b.clone()], "2026-11-02")
            .await
            .unwrap();
        assert_eq!(november.session(&a), Some((key, october_team_key)));
        let (b_key, b_team_key) = november.session(&b).unwrap();
        assert_eq!(b_key.key_month, "2026-11");
        assert_ne!(b_team_key, october_team_key);
        assert_eq!(second.table.reads.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn a_key_stored_under_another_month_seals_the_session_images_under_that_month() {
        let a = session(7, 1);
        let first = store(MemoryTable::default());
        let TeamMonth::Key(september) = first.team_month_or_new(7, "2026-09", None).await.unwrap()
        else {
            panic!("the team month key must be stored")
        };
        first
            .store_new_session(a.clone(), september, "2026-09".to_owned())
            .await
            .unwrap();

        let flush = store(rows_of(&first))
            .keys_for_flush(std::slice::from_ref(&a), "2026-10-15")
            .await
            .unwrap();
        let (key, team_key) = flush.session(&a).unwrap();
        assert_eq!((key.key_month.as_str(), *team_key), ("2026-09", september));
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
            .store_new_session(a.clone(), [9; 32], "2026-10".to_owned())
            .await
            .unwrap();
        let NewSession::Winner(key_month, sealed) = outcome else {
            panic!("the put must lose")
        };
        let mut team_months = HashMap::new();
        loser
            .resolve_team_months(BTreeSet::from([(7, key_month.clone())]), &mut team_months)
            .await
            .unwrap();
        let adopted = open_stored(&a, &key_month, &sealed, &team_months).unwrap();
        assert_eq!(adopted, winning.sessions[&a]);
    }

    #[tokio::test]
    async fn drops_tombstoned_sessions_and_new_ones_it_may_not_key() {
        let table = MemoryTable::default();
        let (deleted_session, deleted_team, kept) = (session(7, 1), session(8, 2), session(7, 3));
        let no_start = SessionId {
            team_id: 7,
            session_id: "session".to_owned(),
        };
        let too_early = session_at(MID_AUGUST, 7, 4);
        table.store(
            TableKey::session(7, &deleted_session.session_id),
            Row::Deleted,
        );
        table.store(TableKey::team_month(8, "2026-10"), Row::Deleted);
        let store = store(table);

        let flush = store
            .keys_for_flush(
                &[
                    deleted_session.clone(),
                    deleted_team.clone(),
                    kept.clone(),
                    no_start.clone(),
                    too_early.clone(),
                ],
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
                (too_early, DropCause::StartMonthOutOfRange),
                (deleted_session, DropCause::Deleted),
                (no_start, DropCause::NoStartMonth),
                (deleted_team, DropCause::Deleted),
            ]
        );
        assert!(flush.team_month(8, "2026-10").is_none());
    }

    #[tokio::test]
    async fn a_tombstoned_team_month_drops_the_sessions_sealed_under_it() {
        let first = store(MemoryTable::default());
        let (a, b) = (session(7, 1), session_at(START_OF_NOVEMBER, 7, 2));
        first
            .keys_for_flush(std::slice::from_ref(&a), "2026-10-15")
            .await
            .unwrap();
        let rows = rows_of(&first);
        let october = TableKey::team_month(7, "2026-10");
        rows.store(october.clone(), Row::Deleted);

        let second = store(rows);
        let flush = second
            .keys_for_flush(&[a.clone(), b.clone()], "2026-11-02")
            .await
            .unwrap();
        assert_eq!(flush.dropped, vec![(a, DropCause::Deleted)]);
        assert_eq!(flush.sessions.keys().collect::<Vec<_>>(), vec![&b]);
        assert_eq!(second.table.rows.lock().unwrap()[&october], Row::Deleted);
    }

    #[tokio::test]
    async fn a_put_that_meets_a_tombstone_drops_its_data_and_keeps_the_tombstone() {
        // A deletion lands between the flush's read and its conditional put.
        let a = session(7, 1);
        let (team_month, session_row) = (
            TableKey::team_month(8, "2026-10"),
            TableKey::session(7, &a.session_id),
        );
        let table = MemoryTable::default();
        table.store(team_month.clone(), Row::Deleted);
        table.store(session_row.clone(), Row::Deleted);
        let store = store(table);

        let (_, outcome) = store
            .store_new_session(a, [9; 32], "2026-10".to_owned())
            .await
            .unwrap();
        assert!(matches!(outcome, NewSession::Dropped(DropCause::Deleted)));
        let team = store.team_month_or_new(8, "2026-10", None).await.unwrap();
        assert!(matches!(team, TeamMonth::Deleted));
        let rows = store.table.rows.lock().unwrap();
        assert_eq!(rows[&team_month], Row::Deleted);
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
                key_month: "2026-10".to_owned(),
                sealed: SealedKey {
                    sealed: vec![1; 48],
                    nonce: [2; 12],
                },
            },
        );
        rows.store(
            TableKey::team_month(8, "2026-10"),
            Row::TeamMonth {
                team_id: 8,
                key_month: "2026-10".to_owned(),
                wrapped_key: vec![3; 40],
            },
        );
        let expired = Row::Unusable(Unusable::Expired);
        rows.store(TableKey::session(9, &c.session_id), expired.clone());

        let (d, e) = (
            session_at(START_OF_NOVEMBER, 7, 4),
            session_at(START_OF_NOVEMBER, 8, 5),
        );
        let second = store(rows);
        let all = [a.clone(), b.clone(), c.clone(), d.clone(), e.clone()];
        let flush = second.keys_for_flush(&all, "2026-11-02").await.unwrap();
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
            during_outage.keys_for_flush(&all, "2026-11-02").await,
            Err(KeyError::Kms(KmsError::Timeout))
        ));
    }
}
