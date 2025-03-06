use anyhow::Error;

use super::auth::load_token;

pub enum UploadType {
    SourceMap,
}

pub fn upload(host: &str, directory: &str, build_id: &Option<String>) -> Result<(), Error> {
    let token = load_token()?;

    todo!();
    let client = reqwest::blocking::Client::new();

    let url = format!("{}/api/projects/{}/error_tracking/symbol_sets", host);

    Ok(())
}
