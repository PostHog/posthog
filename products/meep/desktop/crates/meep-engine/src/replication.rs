use super::*;

impl Engine {
    /// Register a receiving replica before exposing the snapshot. Registration and
    /// deletion share the topic lock so an in-flight pull cannot miss its tombstone.
    pub async fn replica_snapshot(&self, topic: TopicId, replica: Uuid) -> Result<TopicSnapshot> {
        let slot = self
            .0
            .topics
            .read()
            .get(&topic)
            .cloned()
            .ok_or(Error::UnknownTopic(topic))?;
        let guard = slot.edit.clone().lock_owned().await;
        let current = slot.saved.read().clone();
        if !current.state.deleted && !current.replicas.contains(&replica) {
            let mut next = current.as_ref().clone();
            next.replicas.insert(replica);
            self.save_replica_metadata(slot, guard, next).await?;
        } else {
            drop(guard);
        }
        Ok(TopicSnapshot {
            revision: current.revision,
            state: current.state.clone(),
        })
    }

    /// Collect retired state and file history once every known replica has durably
    /// applied this tombstone. Repeating an acknowledgement after a crash is safe.
    pub async fn acknowledge_deletion(
        &self,
        topic: TopicId,
        revision: u64,
        replica: Uuid,
    ) -> Result<()> {
        let slot = self
            .0
            .topics
            .read()
            .get(&topic)
            .cloned()
            .ok_or(Error::UnknownTopic(topic))?;
        let file = slot.files.clone().lock_owned().await;
        let engine = self.clone();
        self.0
            .tasks
            .spawn(async move {
                let _file = file;
                let mut saved = {
                    let saved = slot.saved.read();
                    if !saved.state.deleted || saved.revision != revision {
                        return Err(TopicError::InactiveTopic.into());
                    }
                    if !saved.replicas.contains(&replica) {
                        return Ok(());
                    }
                    saved.as_ref().clone()
                };
                saved.replicas.remove(&replica);
                if saved.replicas.is_empty() {
                    engine.purge_files(topic).await?;
                    saved.retired_state = None;
                }
                let guard = slot.edit.clone().lock_owned().await;
                engine
                    .save_replica_metadata(slot.clone(), guard, saved)
                    .await?;
                Ok(())
            })
            .await
            .context("Acknowledging deletion interrupted")?
    }

    async fn save_replica_metadata(
        &self,
        slot: Arc<Slot>,
        guard: tokio::sync::OwnedMutexGuard<()>,
        saved: StoredTopic,
    ) -> Result<()> {
        let store = self.0.store.clone();
        self.0
            .tasks
            .spawn_blocking(move || {
                let _guard = guard;
                store.save(saved.revision, &saved, None, &[])?;
                *slot.saved.write() = Arc::new(saved);
                Ok(())
            })
            .await
            .context("Saving replica membership interrupted")?
    }

    pub(super) async fn purge_files(&self, topic: TopicId) -> Result<()> {
        let blobs = self.0.blobs.clone();
        tokio::task::spawn_blocking(move || blobs.purge(topic))
            .await
            .context("File collection interrupted")??;
        Ok(())
    }
}
