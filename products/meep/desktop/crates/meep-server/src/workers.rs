use crate::Server;

use meep_topic::TopicId;
use std::{collections::BTreeSet, time::Duration};
use tokio::{task::JoinSet, time::sleep};
use tokio_util::sync::CancellationToken;

pub(super) async fn run(s: Server, stop: CancellationToken) {
    let mut topics = BTreeSet::new();
    let mut accounts = BTreeSet::new();
    let mut jobs = JoinSet::new();
    let mut changes = s.engine.subscribe();
    let mut connections = s.accounts.feed.subscribe();
    let mut maintenance = tokio::time::interval(Duration::from_secs(3600));
    maintenance.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    let mut new_topics = s.engine.topic_ids();
    let mut new_accounts: Vec<_> = s
        .accounts
        .all()
        .iter()
        .map(|a| a.public.id.clone())
        .collect();
    loop {
        while let Some(result) = jobs.try_join_next() {
            if let Err(e) = result {
                log::warn!("A server worker stopped: {e}");
            }
        }
        for id in new_topics.drain(..) {
            if topics.insert(id) {
                let engine = s.engine.clone();
                jobs.spawn(async move { engine.drive_topic(id).await });
                jobs.spawn(routines(s.clone(), id));
            }
        }
        for id in new_accounts.drain(..) {
            if accounts.insert(id.clone()) {
                jobs.spawn(connection(s.clone(), id));
            }
        }
        tokio::select! {
            biased;
            _ = stop.cancelled() => break,
            _=maintenance.tick()=>{
                if let Err(e)=s.engine.maintain_topics().await {log::warn!("Topic maintenance: {e}");}
                let accounts = s.accounts.clone();
                match tokio::task::spawn_blocking(move || accounts.store.maintain().and_then(|_|accounts.checkpoints.maintain())).await {
                    Ok(Ok(())) => {}
                    Ok(Err(e)) => log::warn!("Store maintenance: {e}"),
                    Err(e) => log::warn!("Store maintenance interrupted: {e}"),
                }
                if log::log_enabled!(log::Level::Info) {
                    for id in &topics {
                        if let Ok((messages, entries)) = s.engine.read_topic(*id, |s| (s.threads.iter().map(|t|t.messages.len()).sum::<usize>(),s.tasks.iter().map(|t|t.log.len()).sum::<usize>())) {
                            log::info!("Topic {id} hot snapshot: {messages} thread messages, {entries} task log entries");
                        }
                    }
                }
            }
            event = changes.recv() => match event {
                Ok(event) => {
                    if s.engine.read_topic(event.topic, |_| ()).is_ok() {
                        if !topics.contains(&event.topic) { new_topics.push(event.topic); }
                    } else { topics.remove(&event.topic); }
                }
                Err(tokio::sync::broadcast::error::RecvError::Lagged(_)) => {
                    new_topics = s.engine.topic_ids();
                    topics.retain(|id| new_topics.binary_search(id).is_ok());
                }
                Err(tokio::sync::broadcast::error::RecvError::Closed) => break,
            },
            event = connections.recv() => {
                match event {
                    Ok(c) => { if !accounts.contains(&c.id) && s.accounts.get(&c.id).is_some() { new_accounts.push(c.id); } }
                    Err(tokio::sync::broadcast::error::RecvError::Lagged(_)) => {
                        new_accounts = s.accounts.all().iter().map(|a| a.public.id.clone()).collect();
                    }
                    Err(tokio::sync::broadcast::error::RecvError::Closed) => break,
                }
                for id in &topics { s.engine.wake_topic(*id); }
            }
        }
    }
    jobs.shutdown().await;
}

async fn routines(s: Server, id: TopicId) {
    let engine = &s.engine;
    let mut changes = engine.subscribe();
    loop {
        let Ok((archived, bindings)) = engine.read_topic(id, |s| {
            (
                s.archived,
                s.topic
                    .routines
                    .iter()
                    .filter(|r| r.binding.backend == "posthog")
                    .map(|r| r.binding.clone())
                    .collect::<Vec<_>>(),
            )
        }) else {
            return;
        };
        for binding in bindings {
            if let Err(e) =
                crate::topic_workflows::reconcile_archive(&s, id, &binding, archived).await
            {
                log::warn!("Could not reconcile archived workflow for topic {id}: {e}");
            }
            if archived {
                continue;
            }
            if let Err(error) = engine.poll_routine_runs(id, &binding.id).await {
                log::warn!("Could not poll routine runs for topic {id}: {error:#}");
            }
            if let Err(error) = engine.routine_health(id, &binding.id).await {
                log::warn!("Could not update routine health for topic {id}: {error:#}");
            }
        }
        let timer = sleep(Duration::from_secs(30));
        tokio::pin!(timer);
        loop {
            tokio::select! {
                _=&mut timer=>break,
                change=changes.recv()=> {
                    if change.is_err() || change.is_ok_and(|c|c.topic==id && engine.topic_active(id)==archived){break;}
                }
            }
        }
    }
}

async fn connection(s: Server, id: String) {
    let mut backoff = Duration::from_secs(5);
    let mut notices = s.accounts.feed.subscribe();
    loop {
        let Some(account) = s.accounts.get(&id) else {
            if matches!(
                notices.recv().await,
                Err(tokio::sync::broadcast::error::RecvError::Closed)
            ) {
                return;
            }
            continue;
        };
        let delay = match s.accounts.poll(&s.engine, &account).await {
            Ok(()) => {
                backoff = Duration::from_secs(5);
                account.interval
            }
            Err(error) => {
                log::warn!("Could not poll connection {id}: {error:#}");
                let wait = backoff;
                backoff = (backoff * 2).min(Duration::from_secs(900));
                wait
            }
        };
        let timer = sleep(delay);
        tokio::pin!(timer);
        loop {
            tokio::select! { _=&mut timer=>break, _=notices.recv()=>{} }
            if s.accounts
                .get(&id)
                .is_none_or(|a| a.version != account.version)
            {
                break;
            }
        }
    }
}
