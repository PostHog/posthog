//! View replication shares the sync cycle, SQLite transaction boundary and rejection feed.
use super::*;
use meep_wire::views::{View, ViewCommand, ViewEnvelope};
use std::collections::BTreeMap;

fn pending(db: &Connection) -> Result<Vec<ViewEnvelope>> {
    let mut stmt = db.prepare("SELECT envelope FROM client_view_outbox ORDER BY seq")?;
    stmt.query_map([], |r| r.get::<_, String>(0))?
        .map(|r| Ok(serde_json::from_str(&r?)?))
        .collect()
}

fn projected(db: &Connection) -> Result<BTreeMap<Uuid, View>> {
    let mut views: BTreeMap<Uuid, View> =
        meep_store::get(db, "client/meta", "views")?.unwrap_or_default();
    for envelope in pending(db)? {
        let mut state = views.remove(&envelope.view);
        let _ = envelope.apply(&mut state);
        if let Some(v) = state {
            views.insert(v.id, v);
        }
    }
    Ok(views)
}

impl Client {
    /// Read locally visible workspace views including unpublished edits.
    pub fn views(&self) -> Result<Vec<View>> {
        let mut reader = self.0.reader.lock();
        let tx = reader.transaction()?;
        Ok(projected(&tx)?
            .into_values()
            .filter(|v| !v.deleted)
            .collect())
    }

    /// Queue a view edit durably before waking synchronization.
    pub fn issue_view(&self, view: Uuid, command: ViewCommand) -> Result<Uuid> {
        let e = ViewEnvelope {
            id: Uuid::new_v4(),
            view,
            at: Utc::now(),
            command,
        };
        meep_store::transaction(&mut self.0.db.lock(), |tx| {
            let mut state = projected(tx)?.remove(&view);
            e.apply(&mut state)?;
            tx.execute(
                "INSERT INTO client_view_outbox(id,envelope) VALUES(?1,?2)",
                [e.id.to_string(), serde_json::to_string(&e)?],
            )?;
            Ok(())
        })?;
        self.added_pending();
        self.emit(Event::ViewsChanged);
        self.sync_now();
        Ok(e.id)
    }
    pub(super) async fn sync_views(&self, cycle: &sync::Cycle) -> Result<()> {
        let commands = self.local((), |c| pending(&c.0.reader.lock())).await?;
        let mut failed_creates = std::collections::BTreeSet::new();
        for e in commands {
            if failed_creates.contains(&e.view) {
                continue;
            }
            let result = self.0.transport.push_view(&e).await;
            let mut error = None;
            match result {
                Ok(v) if v.id == e.view => {
                    self.local(cycle.clone(), move |c| {
                        meep_store::transaction(&mut c.0.db.lock(), |tx| {
                            let mut base: BTreeMap<Uuid, View> =
                                meep_store::get(tx, "client/meta", "views")?.unwrap_or_default();
                            base.insert(v.id, v);
                            meep_store::put(tx, "client/meta", "views", &base)?;
                            tx.execute(
                                "DELETE FROM client_view_outbox WHERE id=?1",
                                [e.id.to_string()],
                            )?;
                            Ok(())
                        })
                    })
                    .await?;
                }
                Ok(_) => anyhow::bail!("Wrong view command receipt"),
                Err(TransportError::Api {
                    status: 400 | 409,
                    message,
                    ..
                }) => {
                    error = Some(message);
                }
                Err(e) => return Err(e.into()),
            }
            if let Some(reason) = error {
                let create = matches!(e.command, ViewCommand::Create { .. });
                if create {
                    failed_creates.insert(e.view);
                }
                let rejected = self
                    .local(cycle.clone(), move |c| {
                        meep_store::transaction(&mut c.0.db.lock(), |tx| {
                            let mut rejected = vec![(e.id, reason.clone())];
                            if create {
                                for edit in pending(tx)?
                                    .into_iter()
                                    .filter(|edit| edit.view == e.view && edit.id != e.id)
                                {
                                    rejected.push((
                                        edit.id,
                                        format!("View creation was rejected: {reason}"),
                                    ));
                                }
                            }
                            for (id, detail) in &rejected {
                                meep_store::put(tx, "client/rejected", &id.to_string(), detail)?;
                                tx.execute(
                                    "DELETE FROM client_view_outbox WHERE id=?1",
                                    [id.to_string()],
                                )?;
                            }
                            Ok(rejected)
                        })
                    })
                    .await?;
                for (id, reason) in rejected {
                    self.emit(Event::Rejected {
                        command: id.into(),
                        reason,
                    });
                }
            }
            self.emit(Event::ViewsChanged);
        }
        self.pull_views(cycle).await
    }
    pub(super) async fn pull_views(&self, cycle: &sync::Cycle) -> Result<()> {
        let base: BTreeMap<_, _> = self
            .0
            .transport
            .views()
            .await?
            .into_iter()
            .map(|v| (v.id, v))
            .collect();
        self.local(cycle.clone(), move |c| {
            let db = c.0.db.lock();
            let prior: BTreeMap<Uuid, View> =
                meep_store::get(&db, "client/meta", "views")?.unwrap_or_default();
            if base != prior {
                meep_store::put(&db, "client/meta", "views", &base)?;
                c.emit(Event::ViewsChanged);
            }
            Ok(())
        })
        .await
    }

    /// Read a live PostHog source through the Meep server.
    pub async fn view_source(
        &self,
        id: Uuid,
        params: serde_json::Value,
    ) -> Result<serde_json::Value> {
        Ok(self.0.transport.view_source(id, params).await?)
    }
}
