use crate::{Server, accounts::info};
use anyhow::Result;
use meep_connections::Health;
use meep_topic::Ref;
use meep_wire::{NeedsYou, SearchHit, SearchResults};

pub(super) fn needs_you(s: &Server) -> Result<NeedsYou> {
    let connections = s.engine.connections()?.into_iter().filter_map(|c| {
        let since = match c.health {
            Health::Ok { .. } => return None,
            Health::Expired { since, .. } | Health::Failing { since, .. } => since,
        };
        Some((info(&c), since))
    });
    Ok(s.engine
        .read_topics(|topics| NeedsYou::from_states(topics.iter().copied(), connections)))
}

pub(super) fn search(s: &Server, q: &str, limit: usize) -> Result<SearchResults> {
    let mut hits = vec![];
    for h in s.accounts.store.search(q, limit)? {
        let (kind, id) = match h.subject {
            Ref::Topic => ("topic", h.topic.to_string()),
            Ref::Task(id) => ("task", id.to_string()),
            Ref::Thread(id) => ("thread", id.to_string()),
            Ref::Fact(id) => ("fact", id.to_string()),
            _ => continue,
        };
        hits.push(SearchHit {
            topic: h.topic,
            kind: kind.into(),
            id,
            snippet: h.snippet,
        });
    }
    Ok(SearchResults { hits })
}
