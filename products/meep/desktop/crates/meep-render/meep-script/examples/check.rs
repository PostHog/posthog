//! Validate a file or the bundled notes view and report its design grade.
use anyhow::{Context, Result};
use meep_script::{builtins, script};
use serde_json::json;

fn main() -> Result<()> {
    let source = match std::env::args_os().nth(1) {
        Some(path) => std::fs::read_to_string(path)?,
        None => builtins::source("notes")
            .context("Missing notes example")?
            .to_owned(),
    };
    let report = script::validate(&source, &json!({})).map_err(anyhow::Error::msg)?;
    println!("{}", report["design_grade"]);
    Ok(())
}
