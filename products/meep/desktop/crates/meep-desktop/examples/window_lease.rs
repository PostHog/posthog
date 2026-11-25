//! Run two window claims against the same temporary workspace.
#[cfg(unix)]
fn main() -> anyhow::Result<()> {
    use meep_desktop::instance::claim_ui;
    let dir = tempfile::tempdir()?;
    let first = claim_ui(dir.path())?.expect("first window owns the lease");
    anyhow::ensure!(claim_ui(dir.path())?.is_none());
    drop(first);
    anyhow::ensure!(claim_ui(dir.path())?.is_some());
    println!("A second window can open after the first releases the workspace.");
    Ok(())
}
#[cfg(not(unix))]
fn main() {
    println!("The window lease example uses Unix file locks.");
}
