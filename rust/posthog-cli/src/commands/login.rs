use anyhow::Error;
use inquire::Text;
use tracing::info;

use crate::utils::auth::{token_validator, CredentialProvider, HomeDirProvider, Token};

pub fn login() -> Result<(), Error> {
    let env_id =
        Text::new("Enter your project ID (the number in your posthog homepage url)").prompt()?;

    let token = Text::new(
        "Enter your personal API token (see posthog.com/docs/api#private-endpoint-authentication)",
    )
    .with_validator(token_validator)
    .prompt()?;

    let token = Token { token, env_id };
    let provider = HomeDirProvider;
    provider.store_credentials(token)?;
    info!("Token saved to: {}", provider.report_location());
    Ok(())
}
