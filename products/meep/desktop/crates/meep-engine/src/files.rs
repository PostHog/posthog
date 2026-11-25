//! File writes and the inbox decisions which select between immutable revisions.
use super::*;

fn choices(path: &str, current: u64, candidate: u64) -> Vec<Suggestion> {
    [false, true]
        .into_iter()
        .map(|use_candidate| Suggestion::ChooseFileRevision {
            path: path.into(),
            current,
            candidate,
            use_candidate,
        })
        .collect()
}

fn describe(blob: &Blob) -> String {
    use sha2::{Digest, Sha256};
    let preview = std::str::from_utf8(&blob.bytes)
        .ok()
        .filter(|s| !s.contains('\0'))
        .map(|s| s.chars().take(320).collect::<String>())
        .unwrap_or_default();
    format!(
        "Revision {} · {} bytes · SHA-256 {:x}\n{}",
        blob.revision,
        blob.bytes.len(),
        Sha256::digest(&blob.bytes),
        preview
    )
}

fn review_file(
    state: &mut TopicState,
    head: &Blob,
    candidate: &Blob,
    now: DateTime<Utc>,
) -> Result<Changes> {
    let path = &head.name;
    let group = format!("file-review/{}/{path}", candidate.revision);
    if state.threads.iter().any(|t| t.key == group) {
        return Ok(vec![]);
    }
    let thread = id();
    let message = Message {
        id: id(),
        producer: Producer::System,
        origin: Some(Source::Topic(state.topic.id).into_origin("File sync".into(), now, None)),
        author: "File sync".into(),
        at: now,
        external_id: None,
        text: format!(
            "Conflicting edits to {path}\n\nCurrent when reviewed\n{}\n\nOffline edit\n{}",
            describe(head),
            describe(candidate)
        ),
    };
    let mut changes = state.receive(message, group, thread, now)?;
    changes.extend(state.sort(
        thread,
        Decision::Ask {
            summary: format!("Choose the current revision of {path}."),
            reason: "Both revisions are saved. Choose which contents to use.".into(),
            suggestions: choices(path, head.revision, candidate.revision),
        },
        now,
    )?);
    Ok(changes)
}

impl Engine {
    /// A crash can interrupt the interval between the durable blob append and its
    /// SQLite review. Reconcile immutable alternatives before accepting commands.
    pub(super) async fn recover_file_reviews(&self, topic: TopicId) -> Result<()> {
        let slot = self.slot(topic)?;
        // Startup recovery runs before the engine is exposed or workers are started.
        let mut next = slot.draft();
        let now = self.0.clock.now();
        let blobs = self.0.blobs.clone();
        let (next, changes, files_changed) = tokio::task::spawn_blocking(move || -> Result<_> {
            let mut changes = vec![];
            let deleted = blobs.deleted_heads(topic)?;
            let files_changed = deleted != next.state.deleted_files;
            if files_changed {
                for path in deleted.keys() {
                    next.state.close_file_reviews(path, now);
                }
                next.state.deleted_files = deleted;
            }
            for (path, revisions) in blobs.alternatives(topic)? {
                let mut outstanding = vec![];
                let mut open = false;
                for revision in revisions {
                    let key = format!("file-review/{revision}/{path}");
                    match next.state.threads.iter().find(|t| t.key == key) {
                        Some(t) => open |= matches!(t.state, ThreadState::NeedsYou { .. }),
                        None => outstanding.push(revision),
                    }
                }
                if !open && outstanding.is_empty() {
                    continue;
                }
                let head = blobs
                    .get(topic, &path, None)?
                    .context("Missing file head during review recovery")?;
                changes.extend(next.state.refresh_file_reviews(&path, head.revision, now));
                for revision in outstanding {
                    let candidate = blobs
                        .get(topic, &path, Some(revision))?
                        .context("Missing competing revision")?;
                    changes.extend(review_file(&mut next.state, &head, &candidate, now)?);
                }
            }
            Ok((next, changes, files_changed))
        })
        .await
        .context("File review recovery interrupted")??;
        if files_changed || !changes.is_empty() {
            let guard = slot.edit.clone().lock_owned().await;
            self.commit(slot.clone(), guard, next, changes, &Default::default())
                .await?;
        }
        Ok(())
    }

    /// Store a device edit. Divergent revisions keep their bytes and open a shared inbox decision.
    pub async fn write_file(
        &self,
        topic: TopicId,
        path: String,
        bytes: Vec<u8>,
        key: Uuid,
        base: Option<u64>,
    ) -> Result<FileWrite> {
        let file = self.slot(topic)?.files.clone().lock_owned().await;
        let engine = self.clone();
        self.0
            .tasks
            .spawn(async move {
                let _file = file;
                engine.append_file(topic, path, bytes, key, base).await
            })
            .await
            .context("file write interrupted")?
    }

    async fn append_file(
        &self,
        topic: TopicId,
        path: String,
        bytes: Vec<u8>,
        key: Uuid,
        base: Option<u64>,
    ) -> Result<FileWrite> {
        let slot = self.slot(topic)?;
        let blobs = self.0.blobs.clone();
        if slot.saved.read().state.deleted {
            return Err(Error::UnknownTopic(topic));
        }
        let name = path.clone();
        let write = tokio::task::spawn_blocking(move || -> anyhow::Result<_> {
            match base {
                Some(base) => blobs.put_based(topic, &name, &bytes, key, base),
                None => Ok(FileWrite {
                    revision: blobs.put_once(topic, &name, &bytes, key)?,
                    competing_with: None,
                }),
            }
        })
        .await
        .context("file write interrupted")??;
        {
            let saved = slot.saved.read();
            if write.competing_with.is_none() && !saved.state.deleted_files.contains_key(&path)
                && !saved.state.threads.iter().any(|thread| matches!(&thread.state,
                    ThreadState::NeedsYou { suggestions, .. } if suggestions.iter().any(|s| matches!(s,
                        Suggestion::ChooseFileRevision { path: target, .. } if target == &path)))) {
                return Ok(write);
            }
        }
        let blobs = self.0.blobs.clone();
        let name = path.clone();
        let Some(head) = tokio::task::spawn_blocking(move || blobs.get(topic, &name, None))
            .await
            .context("file head lookup interrupted")??
        else {
            return Ok(write);
        };
        let guard = slot.edit.clone().lock_owned().await;
        let mut next = slot.draft();
        let now = self.0.clock.now();
        let mut changes = next.state.refresh_file_reviews(&path, head.revision, now);
        if write.competing_with.is_some() {
            changes.extend(review_file(&mut next.state, &head, &write.revision, now)?);
        }
        let recreated = next
            .state
            .deleted_files
            .get(&path)
            .is_some_and(|rev| head.revision > *rev);
        if recreated {
            next.state.deleted_files.remove(&path);
        }
        if recreated || !changes.is_empty() {
            self.commit(slot.clone(), guard, next, changes, &Default::default())
                .await?;
        }
        Ok(write)
    }

    /// The inbox transition validates the offered pair before this copy is made.
    pub(super) async fn select_file(
        &self,
        topic: TopicId,
        path: String,
        current: u64,
        selected: u64,
        key: Uuid,
    ) -> Result<u64> {
        let blobs = self.0.blobs.clone();
        Ok(tokio::task::spawn_blocking(move || -> anyhow::Result<_> {
            let chosen = blobs
                .get(topic, &path, Some(selected))?
                .context("missing selected file revision")?;
            let head = blobs
                .get(topic, &path, None)?
                .context("missing current file revision")?;
            if head.revision == current && selected == current {
                return Ok(current);
            }
            // An interrupted command may already have published its copy. Its stable
            // receipt precedes the base check, so retrying cannot publish a second copy.
            Ok(blobs
                .publish_choice(topic, &path, &chosen.bytes, key, current)?
                .revision)
        })
        .await
        .context("file choice interrupted")??)
    }
}
