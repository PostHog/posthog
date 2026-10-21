//! The migration saga's store operations: requests, the saga record, seal acks and the flip.

use etcd_client::{Compare, CompareOp, DeleteOptions, Txn, TxnOp, WatchStream};

use super::{count_call, PersonhogStore, StoreKey};
use crate::error::Result;
use crate::types::{
    ChangelogConfig, Generation, MigrationPhase, MigrationRequest, MigrationState, SealAck,
};

impl PersonhogStore {
    pub async fn get_migration(&self) -> Result<Option<MigrationState>> {
        count_call("get_migration");
        let key = self.key(StoreKey::Migration);
        Ok(self.inner.get(&key).await?)
    }

    pub async fn get_migration_with_mod_revision(&self) -> Result<Option<(MigrationState, i64)>> {
        count_call("get_migration_with_mod_revision");
        let key = self.key(StoreKey::Migration);
        Ok(self.inner.get_with_mod_revision(&key).await?)
    }

    /// Writes the saga record directly, skipping the request and its quiet-fleet start.
    #[cfg(any(test, feature = "test-support"))]
    pub async fn create_migration(&self, migration: &MigrationState) -> Result<bool> {
        count_call("create_migration");
        let key = self.key(StoreKey::Migration);
        let txn = Txn::new()
            .when(vec![Compare::create_revision(
                key.clone(),
                CompareOp::Equal,
                0,
            )])
            .and_then(vec![TxnOp::put(key, serde_json::to_vec(migration)?, None)]);
        let resp = self.inner.txn(txn).await?;
        Ok(resp.succeeded())
    }

    pub async fn cas_migration_phase(
        &self,
        expected_id: &str,
        expected_mod_revision: i64,
        next: MigrationPhase,
    ) -> Result<bool> {
        count_call("cas_migration_phase");
        self.cas_phase(expected_id, expected_mod_revision, next, None)
            .await
    }

    /// Move the saga to Cancelling, recording why.
    pub async fn cancel_migration(
        &self,
        expected_id: &str,
        expected_mod_revision: i64,
        reason: &str,
    ) -> Result<bool> {
        count_call("cancel_migration");
        self.cas_phase(
            expected_id,
            expected_mod_revision,
            MigrationPhase::Cancelling,
            Some(reason),
        )
        .await
    }

    async fn cas_phase(
        &self,
        expected_id: &str,
        expected_mod_revision: i64,
        next: MigrationPhase,
        cancel_reason: Option<&str>,
    ) -> Result<bool> {
        let key = self.key(StoreKey::Migration);
        let Some((mut migration, mod_revision)) = self
            .inner
            .get_with_mod_revision::<MigrationState>(&key)
            .await?
        else {
            return Ok(false);
        };
        if migration.id != expected_id
            || mod_revision != expected_mod_revision
            || !migration.phase.may_transition_to(next)
        {
            return Ok(false);
        }
        migration.phase = next;
        migration.phase_entered_at_ms = assignment_coordination::util::now_millis();
        migration.blocking.clear();
        if let Some(reason) = cancel_reason {
            migration.cancel_reason = Some(reason.to_string());
        }
        let txn = Txn::new()
            .when(vec![Compare::mod_revision(
                key.clone(),
                CompareOp::Equal,
                mod_revision,
            )])
            .and_then(vec![TxnOp::put(key, serde_json::to_vec(&migration)?, None)]);
        Ok(self.inner.txn(txn).await?.succeeded())
    }

    pub async fn set_migration_blocking(
        &self,
        expected_mod_revision: i64,
        blocking: Vec<String>,
    ) -> Result<bool> {
        count_call("set_migration_blocking");
        let key = self.key(StoreKey::Migration);
        let Some((mut migration, mod_revision)) = self
            .inner
            .get_with_mod_revision::<MigrationState>(&key)
            .await?
        else {
            return Ok(false);
        };
        if mod_revision != expected_mod_revision {
            return Ok(false);
        }
        migration.blocking = blocking;
        let txn = Txn::new()
            .when(vec![Compare::mod_revision(
                key.clone(),
                CompareOp::Equal,
                mod_revision,
            )])
            .and_then(vec![TxnOp::put(key, serde_json::to_vec(&migration)?, None)]);
        Ok(self.inner.txn(txn).await?.succeeded())
    }

    pub async fn flip_changelog(
        &self,
        migration: &MigrationState,
        migration_mod_revision: i64,
        config: &ChangelogConfig,
        config_mod_revision: i64,
    ) -> Result<bool> {
        count_call("flip_changelog");
        let migration_key = self.key(StoreKey::Migration);
        let config_key = self.key(StoreKey::ChangelogConfig);
        let mut draining = config.draining.clone();
        draining.push(Generation {
            topic: migration.from.topic.clone(),
            partitions: migration.from.partitions,
            epoch: config.epoch,
        });
        let flipped = ChangelogConfig {
            topic: migration.to.topic.clone(),
            partitions: migration.to.partitions,
            epoch: config.epoch + 1,
            writer_group: config.writer_group.clone(),
            draining,
        };
        let mut record = migration.clone();
        record.phase = MigrationPhase::Resuming;
        record.phase_entered_at_ms = assignment_coordination::util::now_millis();
        record.blocking.clear();
        let txn = Txn::new()
            .when(vec![
                Compare::mod_revision(
                    migration_key.clone(),
                    CompareOp::Equal,
                    migration_mod_revision,
                ),
                Compare::mod_revision(config_key.clone(), CompareOp::Equal, config_mod_revision),
            ])
            .and_then(vec![
                TxnOp::put(config_key, serde_json::to_vec(&flipped)?, None),
                TxnOp::put(migration_key, serde_json::to_vec(&record)?, None),
            ]);
        Ok(self.inner.txn(txn).await?.succeeded())
    }

    pub async fn archive_migration(
        &self,
        migration: &MigrationState,
        mod_revision: i64,
        final_phase: MigrationPhase,
    ) -> Result<bool> {
        count_call("archive_migration");
        let key = self.key(StoreKey::Migration);
        let mut record = migration.clone();
        record.phase = final_phase;
        record.phase_entered_at_ms = assignment_coordination::util::now_millis();
        let txn = Txn::new()
            .when(vec![Compare::mod_revision(
                key.clone(),
                CompareOp::Equal,
                mod_revision,
            )])
            .and_then(vec![
                TxnOp::put(
                    self.key(StoreKey::MigrationHistory(&migration.id)),
                    serde_json::to_vec(&record)?,
                    None,
                ),
                TxnOp::delete(
                    self.key(StoreKey::SealAcksPrefix),
                    Some(DeleteOptions::new().with_prefix()),
                ),
                TxnOp::delete(key, None),
            ]);
        Ok(self.inner.txn(txn).await?.succeeded())
    }

    pub async fn list_migration_history(&self) -> Result<Vec<MigrationState>> {
        count_call("list_migration_history");
        let key = self.key(StoreKey::MigrationHistoryPrefix);
        Ok(self.inner.list(&key).await?)
    }

    pub async fn put_seal_ack(&self, ack: &SealAck) -> Result<()> {
        count_call("put_seal_ack");
        let key = self.key(StoreKey::SealAck(&ack.pod_name));
        Ok(self.inner.put(&key, ack, None).await?)
    }

    /// The mod revision of one pod's seal ack, to tell a rewrite from no write.
    #[cfg(any(test, feature = "test-support"))]
    pub async fn seal_ack_mod_revision(&self, pod_name: &str) -> Result<Option<i64>> {
        let key = self.key(StoreKey::SealAck(pod_name));
        Ok(self
            .inner
            .get_with_mod_revision::<SealAck>(&key)
            .await?
            .map(|(_, rev)| rev))
    }

    pub async fn list_seal_acks(&self) -> Result<Vec<SealAck>> {
        count_call("list_seal_acks");
        let key = self.key(StoreKey::SealAcksPrefix);
        Ok(self.inner.list(&key).await?)
    }

    /// Drop a drained generation from the config, guarded on its revision.
    pub async fn retire_changelog_topic(&self, topic: &str) -> Result<bool> {
        count_call("retire_changelog_topic");
        let Some((mut config, mod_revision)) =
            self.get_changelog_config_with_mod_revision().await?
        else {
            return Ok(false);
        };
        let before = config.draining.len();
        config.draining.retain(|g| g.topic != topic);
        if config.draining.len() == before {
            return Ok(false);
        }
        let key = self.key(StoreKey::ChangelogConfig);
        let txn = Txn::new()
            .when(vec![Compare::mod_revision(
                key.clone(),
                CompareOp::Equal,
                mod_revision,
            )])
            .and_then(vec![TxnOp::put(key, serde_json::to_vec(&config)?, None)]);
        Ok(self.inner.txn(txn).await?.succeeded())
    }

    /// Write a request, refused while another request or a saga exists.
    pub async fn create_migration_request(&self, request: &MigrationRequest) -> Result<bool> {
        count_call("create_migration_request");
        let key = self.key(StoreKey::MigrationRequest);
        let txn = Txn::new()
            .when(vec![
                Compare::create_revision(key.clone(), CompareOp::Equal, 0),
                Compare::create_revision(self.key(StoreKey::Migration), CompareOp::Equal, 0),
            ])
            .and_then(vec![TxnOp::put(key, serde_json::to_vec(request)?, None)]);
        Ok(self.inner.txn(txn).await?.succeeded())
    }

    pub async fn get_migration_request_with_mod_revision(
        &self,
    ) -> Result<Option<(MigrationRequest, i64)>> {
        count_call("get_migration_request_with_mod_revision");
        let key = self.key(StoreKey::MigrationRequest);
        Ok(self.inner.get_with_mod_revision(&key).await?)
    }

    /// Rewrite a waiting request (its first sighting or what it waits on), guarded on its revision.
    pub async fn update_migration_request(
        &self,
        record: &MigrationRequest,
        mod_revision: i64,
    ) -> Result<bool> {
        count_call("update_migration_request");
        let key = self.key(StoreKey::MigrationRequest);
        let txn = Txn::new()
            .when(vec![Compare::mod_revision(
                key.clone(),
                CompareOp::Equal,
                mod_revision,
            )])
            .and_then(vec![TxnOp::put(key, serde_json::to_vec(record)?, None)]);
        Ok(self.inner.txn(txn).await?.succeeded())
    }

    /// Start the saga from a request, only if no handoff record exists that was
    /// written after `handoffs_revision`; from an empty read, that is none at all.
    pub async fn start_migration(
        &self,
        request_mod_revision: i64,
        handoffs_revision: i64,
        migration: &MigrationState,
    ) -> Result<bool> {
        count_call("start_migration");
        let request_key = self.key(StoreKey::MigrationRequest);
        let migration_key = self.key(StoreKey::Migration);
        let txn = Txn::new()
            .when(vec![
                Compare::mod_revision(request_key.clone(), CompareOp::Equal, request_mod_revision),
                Compare::create_revision(migration_key.clone(), CompareOp::Equal, 0),
                Compare::mod_revision(
                    self.key(StoreKey::HandoffsPrefix),
                    CompareOp::Less,
                    handoffs_revision + 1,
                )
                .with_prefix(),
            ])
            .and_then(vec![
                TxnOp::put(migration_key, serde_json::to_vec(migration)?, None),
                TxnOp::delete(request_key, None),
            ]);
        Ok(self.inner.txn(txn).await?.succeeded())
    }

    /// Archive a request that will not start, with its reason, guarded on its revision.
    pub async fn reject_migration_request(
        &self,
        request: &MigrationRequest,
        mod_revision: i64,
        reason: &str,
    ) -> Result<bool> {
        count_call("reject_migration_request");
        let key = self.key(StoreKey::MigrationRequest);
        let record = request.rejected(reason, assignment_coordination::util::now_millis());
        let txn = Txn::new()
            .when(vec![Compare::mod_revision(
                key.clone(),
                CompareOp::Equal,
                mod_revision,
            )])
            .and_then(vec![
                TxnOp::put(
                    self.key(StoreKey::MigrationHistory(&request.id)),
                    serde_json::to_vec(&record)?,
                    None,
                ),
                TxnOp::delete(key, None),
            ]);
        Ok(self.inner.txn(txn).await?.succeeded())
    }

    pub async fn watch_migration_request_from(&self, start_revision: i64) -> Result<WatchStream> {
        count_call("watch_migration_request_from");
        let key = self.key(StoreKey::MigrationRequest);
        Ok(self.inner.watch_key_from(&key, start_revision).await?)
    }

    pub async fn watch_migration_from(&self, start_revision: i64) -> Result<WatchStream> {
        count_call("watch_migration_from");
        let key = self.key(StoreKey::Migration);
        Ok(self.inner.watch_key_from(&key, start_revision).await?)
    }

    pub async fn watch_seal_acks_from(&self, start_revision: i64) -> Result<WatchStream> {
        count_call("watch_seal_acks_from");
        let key = self.key(StoreKey::SealAcksPrefix);
        Ok(self.inner.watch_from(&key, start_revision).await?)
    }

    /// A shrunk partition's hold, acks and assignment go in one guarded transaction.
    pub async fn dissolve_partition(
        &self,
        partition: u32,
        handoff_mod_revision: i64,
    ) -> Result<bool> {
        count_call("dissolve_partition");
        let handoff_key = self.key(StoreKey::Handoff(partition));
        let prefix_delete = || Some(DeleteOptions::new().with_prefix());
        let txn = Txn::new()
            .when(vec![Compare::mod_revision(
                handoff_key.clone(),
                CompareOp::Equal,
                handoff_mod_revision,
            )])
            .and_then(vec![
                TxnOp::delete(
                    self.key(StoreKey::FreezeAcksForPartition(partition)),
                    prefix_delete(),
                ),
                TxnOp::delete(
                    self.key(StoreKey::DrainedAcksForPartition(partition)),
                    prefix_delete(),
                ),
                TxnOp::delete(
                    self.key(StoreKey::WarmedAcksForPartition(partition)),
                    prefix_delete(),
                ),
                TxnOp::delete(self.key(StoreKey::Assignment(partition)), None),
                TxnOp::delete(handoff_key, None),
            ]);
        Ok(self.inner.txn(txn).await?.succeeded())
    }
}
