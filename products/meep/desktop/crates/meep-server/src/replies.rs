//! Durable handoff from an accepted reply to the originating topic's inbox.
use crate::Server;
use meep_engine::Error;
use meep_topic::{CommandId, MessageId, Source, TopicId};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeSet;

const JOURNAL: &str = "\0topics/reply-in-flight";
const RECEIPTS: &str = "\0topics/delivered-replies";

#[derive(Serialize, Deserialize)]
struct Delivery {
    command: CommandId,
    from: TopicId,
    to: TopicId,
    text: String,
    previous: BTreeSet<MessageId>,
}

impl Delivery {
    fn received(&self, server: &Server) -> Result<BTreeSet<MessageId>, Error> {
        Ok(server
            .engine
            .topic(self.to)?
            .threads
            .into_iter()
            .flat_map(|thread| thread.messages)
            .filter(|m| m.reply_target() == Some(Source::Topic(self.from)) && m.text == self.text)
            .map(|m| m.id)
            .collect())
    }
}

impl Server {
    // Resume before accepting another inter-topic send and before serving after a restart.
    pub(super) async fn resume_reply(&self) -> Result<(), Error> {
        let checkpoint = &self.accounts.checkpoints;
        let Some(saved) = checkpoint.load(JOURNAL)?.filter(|v| !v.is_null()) else {
            return Ok(());
        };
        let delivery: Delivery = serde_json::from_value(saved.clone())?;
        let id = delivery.command.to_string();
        if !self.accounts.store.seen(RECEIPTS, &id)? {
            if delivery.received(self)?.is_subset(&delivery.previous) {
                self.engine
                    .send_to_topic(delivery.from, delivery.to, &delivery.text, 1)
                    .await?;
            }
            self.accounts.store.record_seen(RECEIPTS, &id)?;
        }
        checkpoint.commit(JOURNAL, Some(&saved), &Value::Null)?;
        Ok(())
    }
}
