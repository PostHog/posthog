use crate::{Connection, Health, TopicId};
use anyhow::{Result, ensure};
use meep_store::{self as store, Connection as Database};
use std::collections::HashSet;

const KIND: &str = "connection";

/// Durable service metadata and topic grants in a host-provided database.
pub struct Registry {
    db: Database,
}

impl Registry {
    /// Initialize the registry on an open SQLite connection.
    pub fn new(db: Database) -> Result<Self> {
        store::initialize(&db)?;
        Ok(Self { db })
    }

    /// Register an account. A duplicate live ID is an error. Repeated grants count once.
    pub fn add(&mut self, mut connection: Connection) -> Result<()> {
        let mut seen = HashSet::new();
        connection.grants.retain(|topic| seen.insert(*topic));
        store::transaction(&mut self.db, |db| {
            let id = &connection.id;
            ensure!(
                store::get::<Connection>(db, KIND, id)?.is_none(),
                "connection {id} already exists"
            );
            store::put(db, KIND, id, &connection)
        })
    }

    /// Remove a connection and its grants. Returns whether a live connection was removed.
    pub fn remove(&mut self, id: &str) -> Result<bool> {
        store::remove(&self.db, KIND, id)
    }

    /// List live accounts in ascending ID order.
    pub fn list(&self) -> Result<Vec<Connection>> {
        Ok(store::list(&self.db, KIND)?
            .into_iter()
            .map(|(_, connection)| connection)
            .collect())
    }

    /// Look up a live account by its stable ID.
    pub fn get(&self, id: &str) -> Result<Option<Connection>> {
        store::get(&self.db, KIND, id)
    }

    /// Replace the health observation for an existing account.
    pub fn set_health(&mut self, id: &str, health: Health) -> Result<()> {
        store::transaction(&mut self.db, |db| {
            update(db, id, |connection| connection.health = health)
        })
    }

    /// Allow a topic to use an existing account. Repeating a grant has no effect.
    pub fn grant(&mut self, id: &str, topic: &TopicId) -> Result<()> {
        store::transaction(&mut self.db, |db| {
            update(db, id, |connection| {
                if !connection.grants.contains(topic) {
                    connection.grants.push(*topic);
                }
            })
        })
    }

    /// Withdraw a topic's grant on an existing account. An absent grant has no effect.
    pub fn revoke(&mut self, id: &str, topic: &TopicId) -> Result<()> {
        store::transaction(&mut self.db, |db| {
            update(db, id, |connection| {
                connection.grants.retain(|granted| granted != topic)
            })
        })
    }

    /// Whether this topic has a grant on a live account, independent of service health.
    pub fn can_use(&self, topic: &TopicId, connection: &str) -> Result<bool> {
        Ok(self
            .get(connection)?
            .is_some_and(|connection| connection.grants.contains(topic)))
    }
}

// Call within a write transaction so edits from other database handles are preserved.
fn update(db: &Database, id: &str, edit: impl FnOnce(&mut Connection)) -> Result<()> {
    let Some(mut connection) = store::get::<Connection>(db, KIND, id)? else {
        anyhow::bail!("unknown connection {id}");
    };
    edit(&mut connection);
    store::put(db, KIND, id, &connection)
}

/// Supplies the host's current health observation for a service account.
pub trait HealthChecker {
    /// Inspect an account and report success, expiry, or failure with its timestamp.
    fn check(&self, connection: &Connection) -> Health;
}

/// Check each listed account outside the database transaction, then save all observations
/// together. A storage error (including a removed account) rolls back the batch.
pub fn check_all(registry: &mut Registry, checker: &dyn HealthChecker) -> Result<()> {
    let observations: Vec<_> = registry
        .list()?
        .into_iter()
        .map(|connection| {
            let health = checker.check(&connection);
            (connection.id, health)
        })
        .collect();
    store::transaction(&mut registry.db, |db| {
        for (id, health) in observations {
            update(db, &id, |connection| connection.health = health)?;
        }
        Ok(())
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::DateTime;
    use std::cell::RefCell;

    fn healthy() -> Health {
        Health::Ok {
            checked_at: DateTime::UNIX_EPOCH,
        }
    }

    fn expired() -> Health {
        Health::Expired {
            since: DateTime::UNIX_EPOCH,
            detail: "Sign in to Slack again".into(),
        }
    }

    fn failing() -> Health {
        Health::Failing {
            since: DateTime::UNIX_EPOCH,
            detail: "Can't see Slack".into(),
        }
    }

    fn account(id: &str) -> Connection {
        Connection {
            unrouted: 0,
            id: id.into(),
            kind: "slack".into(),
            label: "Slack".into(),
            account: "design-team".into(),
            health: healthy(),
            grants: vec![],
        }
    }

    #[test]
    fn health_summary_has_a_readable_status_even_without_a_detail() {
        assert_eq!(healthy().summary(), "Connected");
        assert_eq!(expired().summary(), "Sign in to Slack again");
        assert_eq!(failing().summary(), "Can't see Slack");
        let since = DateTime::UNIX_EPOCH;
        assert_eq!(
            Health::Expired {
                since,
                detail: String::new()
            }
            .summary(),
            "Sign in again"
        );
        assert_eq!(
            Health::Failing {
                since,
                detail: " ".into()
            }
            .summary(),
            "Can't reach the service"
        );
    }

    #[test]
    fn adding_a_duplicate_preserves_the_original_account_and_grants() -> Result<()> {
        let mut registry = Registry::new(Database::open_in_memory()?)?;
        let topic = "00000000-0000-0000-0000-000000000002".parse::<TopicId>()?;
        let mut original = account("team");
        original.grants = vec![topic, topic];
        registry.add(original.clone())?;
        assert!(registry.add(account("team")).is_err());
        original.grants = vec![topic];
        assert_eq!(registry.get("team")?, Some(original));
        Ok(())
    }

    #[test]
    fn list_orders_live_connections_by_id_and_removal_discards_their_grants() -> Result<()> {
        let mut registry = Registry::new(Database::open_in_memory()?)?;
        let topic = "00000000-0000-0000-0000-000000000002".parse::<TopicId>()?;
        registry.add(account("z"))?;
        registry.add(account("a"))?;
        assert_eq!(registry.list()?, [account("a"), account("z")]);
        registry.grant("a", &topic)?;
        assert!(registry.remove("a")?);
        assert!(!registry.remove("a")?);
        assert!(registry.get("a")?.is_none());
        assert_eq!(registry.list()?, [account("z")]);
        assert!(!registry.can_use(&topic, "a")?);
        registry.add(account("a"))?;
        assert!(!registry.can_use(&topic, "a")?);
        Ok(())
    }

    #[test]
    fn grants_and_health_survive_reopening_and_are_scoped_to_one_account() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let file = dir.path().join("accounts.sqlite");
        let owner = "00000000-0000-0000-0000-000000000003".parse::<TopicId>()?;
        let guest = "00000000-0000-0000-0000-000000000004".parse::<TopicId>()?;
        {
            let mut registry = Registry::new(Database::open(&file)?)?;
            registry.add(account("work"))?;
            registry.add(account("home"))?;
            registry.grant("work", &owner)?;
            registry.grant("work", &owner)?;
            registry.grant("work", &guest)?;
            registry.set_health("work", expired())?;
        }
        let mut registry = Registry::new(Database::open(&file)?)?;
        assert!(registry.can_use(&owner, "work")?);
        assert!(!registry.can_use(&owner, "home")?);
        let saved = registry.get("work")?.expect("registered work account");
        assert_eq!(saved.grants, [owner, guest]);
        assert_eq!(saved.health, expired());
        registry.revoke("work", &owner)?;
        registry.revoke("work", &owner)?;
        drop(registry);
        let registry = Registry::new(Database::open(file)?)?;
        assert!(!registry.can_use(&owner, "work")?);
        assert!(registry.can_use(&guest, "work")?);
        Ok(())
    }

    #[test]
    fn mutations_on_an_unknown_id_never_create_a_connection() -> Result<()> {
        let mut registry = Registry::new(Database::open_in_memory()?)?;
        let topic = "00000000-0000-0000-0000-000000000002".parse::<TopicId>()?;
        assert!(registry.set_health("unknown", healthy()).is_err());
        assert!(registry.grant("unknown", &topic).is_err());
        assert!(registry.revoke("unknown", &topic).is_err());
        assert!(registry.list()?.is_empty());
        Ok(())
    }

    struct Checker<F>(F);
    impl<F: Fn(&Connection) -> Health> HealthChecker for Checker<F> {
        fn check(&self, connection: &Connection) -> Health {
            self.0(connection)
        }
    }

    #[test]
    fn checking_accounts_saves_each_result_and_preserves_grants_made_during_the_check() -> Result<()>
    {
        let dir = tempfile::tempdir()?;
        let file = dir.path().join("accounts.sqlite");
        let mut registry = Registry::new(Database::open(&file)?)?;
        let other = RefCell::new(Registry::new(Database::open(&file)?)?);
        let owner = "00000000-0000-0000-0000-000000000003".parse::<TopicId>()?;
        for id in ["a", "b", "c"] {
            registry.add(account(id))?;
        }
        let checked = RefCell::new(Vec::new());
        let checker = Checker(|c: &Connection| {
            checked.borrow_mut().push(c.id.clone());
            other
                .borrow_mut()
                .grant(&c.id, &owner)
                .expect("independent grant during check");
            match c.id.as_str() {
                "a" => failing(),
                "b" => expired(),
                _ => healthy(),
            }
        });
        check_all(&mut registry, &checker)?;
        assert_eq!(checked.into_inner(), ["a", "b", "c"]);
        for (c, expected) in
            other
                .borrow()
                .list()?
                .into_iter()
                .zip([failing(), expired(), healthy()])
        {
            assert_eq!(c.health, expected);
            assert_eq!(c.grants, std::slice::from_ref(&owner));
        }
        Ok(())
    }

    #[test]
    fn a_removed_account_rolls_back_the_health_batch() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let file = dir.path().join("accounts.sqlite");
        let mut registry = Registry::new(Database::open(&file)?)?;
        let other = RefCell::new(Registry::new(Database::open(&file)?)?);
        registry.add(account("a"))?;
        registry.add(account("b"))?;
        let checker = Checker(|c: &Connection| {
            if c.id == "b" {
                other
                    .borrow_mut()
                    .remove("b")
                    .expect("remove account during check");
            }
            failing()
        });
        assert!(check_all(&mut registry, &checker).is_err());
        assert_eq!(registry.list()?, [account("a")]);
        Ok(())
    }
}
