use anyhow::{Context, Result};
use meep_connections::SecretStore;
use std::collections::BTreeMap;
use uuid::Uuid;

pub(crate) type Secrets = BTreeMap<String, String>;
type Backend = dyn SecretStore + Send;

// Keychain's interactive command has a 4096 byte line limit after encoding.
// An immutable generation can span items. Only a committed generation is read.
pub(crate) struct Vault(pub Box<Backend>);
impl Vault {
    pub fn save(&mut self, id: &str, generation: Uuid, values: &Secrets) -> Result<()> {
        let data = serde_json::to_string(values)?;
        let mut rest = data.as_str();
        let mut index = 0;
        while !rest.is_empty() {
            let end = rest.floor_char_boundary(1800.min(rest.len()));
            let key = format!("{generation}.{index}");
            if let Err(error) = self.0.set(id, &key, &rest[..end]) {
                self.remove_parts(id, generation, index);
                return Err(error);
            }
            index += 1;
            rest = &rest[end..];
        }
        if let Err(error) = self.0.set(id, &generation.to_string(), &index.to_string()) {
            self.remove_parts(id, generation, index);
            return Err(error);
        }
        Ok(())
    }
    fn count(&self, id: &str, generation: Uuid) -> Result<usize> {
        Ok(self
            .0
            .get(id, &generation.to_string())?
            .context("Missing connection credentials")?
            .parse()?)
    }
    pub fn read(&self, id: &str, generation: Uuid) -> Result<Secrets> {
        let mut data = String::new();
        for index in 0..self.count(id, generation)? {
            data.push_str(
                &self
                    .0
                    .get(id, &format!("{generation}.{index}"))?
                    .context("Incomplete connection credentials")?,
            );
        }
        Ok(serde_json::from_str(&data)?)
    }
    fn remove_parts(&mut self, id: &str, generation: Uuid, count: usize) {
        for index in 0..count {
            if let Err(error) = self.0.delete(id, &format!("{generation}.{index}")) {
                log::warn!("Could not remove a superseded credential part: {error:#}");
            }
        }
    }
    pub fn revoke(&mut self, id: &str, generation: Uuid) -> Result<()> {
        let key = generation.to_string();
        if let Some(raw) = self.0.get(id, &key)? {
            for i in 0..raw.parse::<usize>()? {
                self.0.delete(id, &format!("{generation}.{i}"))?;
            }
            self.0.delete(id, &key)?;
        }
        Ok(())
    }
    pub fn remove(&mut self, id: &str, generation: Uuid) {
        if let Err(error) = self.revoke(id, generation) {
            log::warn!("Could not remove superseded connection credentials: {error:#}");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use meep_connections::MemorySecrets;

    #[test]
    fn long_multibyte_credentials_round_trip_across_chunks_and_generations() -> Result<()> {
        let mut vault = Vault(Box::new(MemorySecrets::default()));
        let first = Uuid::new_v4();
        let second = Uuid::new_v4();
        let before = Secrets::from([("access_token".into(), "🔑".repeat(1802))]);
        let after = Secrets::from([("access_token".into(), "new".into())]);
        vault.save("team", first, &before)?;
        vault.save("team", second, &after)?;
        assert_eq!(vault.read("team", first)?, before);
        assert_eq!(vault.read("team", second)?, after);
        vault.remove("team", first);
        assert!(vault.read("team", first).is_err());
        assert_eq!(vault.read("team", second)?, after);
        Ok(())
    }
}
