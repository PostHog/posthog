use crate::accounts::{Account, Accounts};
use anyhow::{Context, Result};

impl Accounts {
    pub(super) async fn refresh_token(&self, a: &Account) -> Result<()> {
        let guard = a.refresh_lock.clone().lock_owned().await;
        let current = self.get(&a.public.id).context("Account removed")?;
        if current.version != a.version {
            return Ok(());
        }
        let engine = self
            .engine
            .get()
            .and_then(|e| e.upgrade())
            .context("Server shutting down")?;
        let owner = self.owner.upgrade().context("Server shutting down")?;
        // Once an issuer rotates its refresh token, dropping the response loses the
        // replacement. Finish the exchange and persist it even if the requester leaves.
        self.jobs
            .spawn(async move {
                let _guard = guard;
                let project = current.project.as_ref().context("Connect PostHog")?;
                let values = project.refresh(&current.values).await?;
                let _write = owner.writes.lock();
                let latest = owner.get(&current.public.id).context("Account removed")?;
                if latest.version == current.version {
                    owner.persist(&engine, latest.public.clone(), values, Some(&latest))?;
                }
                Ok(())
            })
            .await
            .context("Credential refresh worker exited")?
    }
}
