use anyhow::{Context, Result, ensure};
use base64::{Engine as _, engine::general_purpose::URL_SAFE_NO_PAD};
use percent_encoding::{NON_ALPHANUMERIC, utf8_percent_encode};
use std::{
    collections::HashMap,
    io::Write,
    process::{Command, Output, Stdio},
};

/// Named secret values scoped to a single connection ID.
pub trait SecretStore {
    /// Look up a secret. An absent value returns `None`.
    fn get(&self, connection: &str, name: &str) -> Result<Option<String>>;
    /// Insert or replace a secret.
    fn set(&mut self, connection: &str, name: &str, value: &str) -> Result<()>;
    /// Delete a secret if present.
    fn delete(&mut self, connection: &str, name: &str) -> Result<()>;
}

/// An ephemeral secret store for fixtures and tests.
#[derive(Default)]
pub struct MemorySecrets {
    values: HashMap<(String, String), String>,
}

impl SecretStore for MemorySecrets {
    fn get(&self, connection: &str, name: &str) -> Result<Option<String>> {
        Ok(self.values.get(&(connection.into(), name.into())).cloned())
    }

    fn set(&mut self, connection: &str, name: &str, value: &str) -> Result<()> {
        self.values
            .insert((connection.into(), name.into()), value.into());
        Ok(())
    }

    fn delete(&mut self, connection: &str, name: &str) -> Result<()> {
        self.values.remove(&(connection.into(), name.into()));
        Ok(())
    }
}

/// Stores generic-password items using the macOS `security` command.
/// Each app chooses a service prefix. Writes use a private pipe and must fit
/// in the command's 4096-byte interactive input buffer after encoding.
pub struct KeychainSecrets {
    prefix: String,
}

fn component(value: &str) -> String {
    const ESCAPE: &percent_encoding::AsciiSet =
        &NON_ALPHANUMERIC.remove(b'.').remove(b'-').remove(b'_');
    utf8_percent_encode(value, ESCAPE).to_string()
}

impl KeychainSecrets {
    /// Use this application's namespace in the default macOS keychain.
    pub fn new(service_prefix: impl Into<String>) -> Self {
        Self {
            prefix: service_prefix.into(),
        }
    }

    fn keys(&self, connection: &str, name: &str) -> (String, String) {
        (
            format!("{}:{}", component(&self.prefix), component(connection)),
            format!("name:{}", component(name)),
        )
    }

    fn lookup_or_delete(
        &self,
        operation: &str,
        flags: &[&str],
        connection: &str,
        name: &str,
    ) -> Result<Option<Output>> {
        let (service, account) = self.keys(connection, name);
        let output = Command::new("/usr/bin/security")
            .arg(operation)
            .args(flags)
            .args(["-s", &service, "-a", &account])
            .stdin(Stdio::null())
            .output()
            .context("running the macOS keychain command")?;
        // errSecItemNotFound (-25300) reduced to an 8-bit process exit status.
        if output.status.code() == Some(44) {
            return Ok(None);
        }
        ensure!(
            output.status.success(),
            "keychain {operation} failed ({})",
            output.status
        );
        Ok(Some(output))
    }

    fn write_command(&self, connection: &str, name: &str, value: &str) -> Result<String> {
        let (service, account) = self.keys(connection, name);
        // Printable data round-trips through find-generic-password -w even for UTF-8,
        // control characters and trailing newlines. The marker also represents empty values.
        let encoded = URL_SAFE_NO_PAD.encode(value);
        let line = format!("add-generic-password -U -s {service} -a {account} -w v1.{encoded}\n");
        ensure!(
            line.len() < 4096,
            "encoded keychain item exceeds the security command's input limit"
        );
        Ok(line)
    }
}

impl SecretStore for KeychainSecrets {
    fn get(&self, connection: &str, name: &str) -> Result<Option<String>> {
        let Some(output) =
            self.lookup_or_delete("find-generic-password", &["-w"], connection, name)?
        else {
            return Ok(None);
        };
        let encoded = output
            .stdout
            .strip_suffix(b"\n")
            .and_then(|line| line.strip_prefix(b"v1."))
            .context("unrecognized keychain value format")?;
        let bytes = URL_SAFE_NO_PAD
            .decode(encoded)
            .context("invalid keychain value encoding")?;
        Ok(Some(std::str::from_utf8(&bytes)?.to_owned()))
    }

    fn set(&mut self, connection: &str, name: &str, value: &str) -> Result<()> {
        let line = self.write_command(connection, name, value)?;
        let mut child = Command::new("/usr/bin/security")
            .args(["-i", "-q"])
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .context("starting the macOS keychain command")?;
        let mut stdin = child.stdin.take().context("missing security input pipe")?;
        let written = stdin.write_all(line.as_bytes());
        drop(stdin);
        let status = child.wait()?;
        written.context("writing the keychain command")?;
        ensure!(
            status.success(),
            "keychain add-generic-password failed ({status})"
        );
        Ok(())
    }

    fn delete(&mut self, connection: &str, name: &str) -> Result<()> {
        self.lookup_or_delete("delete-generic-password", &[], connection, name)?;
        Ok(())
    }
}

#[cfg(all(test, target_os = "macos"))]
mod tests {
    use super::*;

    #[test]
    #[ignore = "writes fixture credentials to the user's macOS keychain"]
    fn keychain_secrets_round_trip_replace_and_delete_a_namespaced_item() -> Result<()> {
        let dir = tempfile::tempdir()?;
        struct Fixture(KeychainSecrets);
        impl Drop for Fixture {
            fn drop(&mut self) {
                let _ = self.0.delete("team fixture", "t:oken");
            }
        }
        let mut fixture = Fixture(KeychainSecrets::new(format!(
            "meep-connections-test.{}",
            dir.path().display()
        )));
        let secrets = &mut fixture.0;
        assert_eq!(secrets.get("team fixture", "t:oken")?, None);
        for value in ["", " leading \"quotes\"\nsecond line 🔑\n"] {
            secrets.set("team fixture", "t:oken", value)?;
            assert_eq!(
                secrets.get("team fixture", "t:oken")?.as_deref(),
                Some(value)
            );
        }
        secrets.delete("team fixture", "t:oken")?;
        secrets.delete("team fixture", "t:oken")?;
        assert_eq!(secrets.get("team fixture", "t:oken")?, None);
        Ok(())
    }
}
