use anyhow::{Context, Result};
use meep_store::{self as store, Connection};
use meep_wire::{SearchHit, SearchResults};

pub(crate) fn search(db: &Connection, query: &str, limit: usize) -> Result<SearchResults> {
    let hits = store::search(db, query, limit)?
        .into_iter()
        .map(|hit| {
            let (topic, id) = hit
                .id
                .split_once('/')
                .context("invalid search document ID")?;
            Ok(SearchHit {
                topic: topic.parse()?,
                id: id.into(),
                kind: hit.kind,
                snippet: hit.snippet,
            })
        })
        .collect::<Result<_>>()?;
    Ok(SearchResults { hits })
}
