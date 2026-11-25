//! Select the replica before exposing cached state or replaying the outbox.
use super::*;
use meep_connections::SecretStore;
use sha2::{Digest, Sha256};

/// Result of pairing a device with an owner on a hosted server.
pub struct Pairing {
    /// Replica for this server and owner.
    pub client: Client,
    /// Authenticated owner of the replica.
    pub owner_id: meep_wire::OwnerId,
    /// Namespace for this owner's local provider credentials.
    pub credential_namespace: String,
}

#[derive(Serialize, Deserialize)]
struct Identity {
    owner: Uuid,
    implicit: bool,
}

impl Client {
    /// Pair with an authenticated server. A previously paired token can reopen its
    /// own replica offline. New credentials must establish ownership first.
    pub async fn pair(
        root: &Path,
        server: &str,
        supplied: Option<&str>,
        secrets: &mut impl SecretStore,
    ) -> Result<Pairing> {
        let url = reqwest::Url::parse(server)?;
        let server = url.as_str().trim_end_matches('/');
        let saved = secrets.get(server, "device-token")?;
        let token = supplied
            .or(saved.as_deref())
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .context("Set MEEP_DEVICE_TOKEN to pair with this server")?;
        let transport = Arc::new(HttpTransport::new(server, token)?);
        let binding = format!("device-owner-{:x}", Sha256::digest(token));
        let identity: Identity = match transport.health().await {
            Ok(health) => Identity {
                owner: health.owner_id,
                implicit: health.implicit_owner,
            },
            Err(TransportError::Unavailable(e)) => serde_json::from_str(
                &secrets
                    .get(server, &binding)?
                    .with_context(|| format!("Pairing requires a reachable server: {e}"))?,
            )?,
            Err(e) => return Err(e.into()),
        };
        let server_hash = Sha256::digest(server);
        let scoped = root.join(format!(
            "replica-hosted-{server_hash:x}-{}.sqlite",
            identity.owner
        ));
        let mut path = scoped.clone();
        if identity.implicit && !scoped.try_exists()? {
            // The old URL-only replica (including its WAL) belongs to the implicit owner.
            // Claim it transactionally, so replacing a server at its old URL cannot inherit it.
            let legacy = root.join(format!("replica-hosted-{server_hash:x}.sqlite"));
            let mut candidates = Vec::new();
            if let Some(name) = secrets.get(server, &format!("replica-{}", identity.owner))? {
                anyhow::ensure!(
                    Path::new(&name).file_name() == Some(name.as_ref()),
                    "Invalid stored replica name"
                );
                candidates.push(root.join(name));
            }
            candidates.push(legacy);
            for previous in [Some(token), saved.as_deref()].into_iter().flatten() {
                let hash = Sha256::digest(format!("{server}\n{previous}"));
                candidates.push(root.join(format!("replica-{hash:x}.sqlite")));
            }
            for candidate in candidates {
                if !candidate.try_exists()? {
                    continue;
                }
                let mut db = replica::open(&candidate)?;
                let claimed = meep_store::transaction(&mut db, |tx| {
                    match meep_store::get::<Uuid>(tx, "pairing", "owner")? {
                        Some(id) => Ok(id == identity.owner),
                        None => {
                            meep_store::put(tx, "pairing", "owner", &identity.owner)?;
                            Ok(true)
                        }
                    }
                })?;
                if claimed {
                    path = candidate;
                    break;
                }
            }
        }
        let client = Client::open(&path, transport)?;
        if path != scoped {
            let name = path
                .file_name()
                .and_then(|s| s.to_str())
                .context("Invalid replica name")?;
            secrets.set(server, &format!("replica-{}", identity.owner), name)?;
        }
        secrets.set(server, &binding, &serde_json::to_string(&identity)?)?;
        secrets.set(server, "device-token", token)?;
        let credential_namespace = if identity.implicit {
            server.to_owned()
        } else {
            format!("{server}/owners/{}", identity.owner)
        };
        Ok(Pairing {
            client,
            owner_id: identity.owner,
            credential_namespace,
        })
    }
}
