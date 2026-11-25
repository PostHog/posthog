use anyhow::Result;
use meep_connections::SecretStore;
use meep_server::{Auth, DeviceTokens, FileSecrets};
use std::{fs, process::Command};

#[test]
fn concurrent_first_opens_share_one_desktop_token_and_new_tokens_work_without_restart() -> Result<()>
{
    let dir = tempfile::tempdir()?;
    std::thread::scope(|scope| {
        let readers = (0..8)
            .map(|_| scope.spawn(|| DeviceTokens::open(dir.path())))
            .collect::<Vec<_>>();
        for reader in readers {
            reader.join().expect("open device directory")?;
        }
        anyhow::Ok(())
    })?;
    let tokens = DeviceTokens::open(dir.path())?;
    let desktop = fs::read_to_string(dir.path().join("device-token"))?;
    assert_eq!(tokens.list()?.len(), 1);
    assert!(tokens.accepts(&desktop)?);
    let cli = |command| {
        Command::new(env!("CARGO_BIN_EXE_meep-server"))
            .arg("--data-dir")
            .arg(dir.path())
            .args(["token", command])
            .output()
    };
    let created = cli("create")?;
    assert!(created.status.success());
    let new = String::from_utf8(created.stdout)?;
    assert_ne!(new.trim(), desktop);
    assert!(tokens.accepts(new.trim())?);
    assert!(!tokens.accepts("")?);
    let listed = cli("list")?;
    assert!(listed.status.success());
    let ids = String::from_utf8(listed.stdout)?;
    assert_eq!(ids.lines().count(), 2);
    assert!(!ids.contains(new.trim()) && !ids.contains(&desktop));
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(
            fs::metadata(dir.path().join("device-token"))?
                .permissions()
                .mode()
                & 0o777,
            0o600
        );
    }
    Ok(())
}

#[test]
fn file_credentials_round_trip_unicode_and_isolate_names_without_using_them_as_paths() -> Result<()>
{
    let dir = tempfile::tempdir()?;
    let mut store = FileSecrets::open(dir.path())?;
    store.set("../account", "/api", "鍵\n")?;
    store.set("other", "/api", "other")?;
    drop(store);
    let mut store = FileSecrets::open(dir.path())?;
    assert_eq!(store.get("../account", "/api")?.as_deref(), Some("鍵\n"));
    store.delete("../account", "/api")?;
    assert_eq!(store.get("../account", "/api")?, None);
    assert_eq!(store.get("other", "/api")?.as_deref(), Some("other"));
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        for entry in fs::read_dir(dir.path())? {
            assert_eq!(entry?.metadata()?.permissions().mode() & 0o777, 0o600);
        }
    }
    Ok(())
}

#[test]
fn revoking_the_bootstrap_fingerprint_disables_that_token_after_reopen() -> Result<()> {
    let dir = tempfile::tempdir()?;
    let tokens = DeviceTokens::open(dir.path())?;
    let desktop = fs::read_to_string(dir.path().join("device-token"))?;
    let fingerprint = tokens.list()?.remove(0);
    let other = tokens.create()?;
    let status = Command::new(env!("CARGO_BIN_EXE_meep-server"))
        .arg("--data-dir")
        .arg(dir.path())
        .args(["token", "revoke", &fingerprint])
        .status()?;
    assert!(status.success());
    assert!(!tokens.accepts(&desktop)?);
    let reopened = DeviceTokens::open(dir.path())?;
    assert!(!reopened.accepts(&desktop)?);
    assert!(reopened.accepts(&other)?);
    Ok(())
}
