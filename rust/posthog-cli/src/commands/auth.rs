use anyhow::{Context, Error};
use inquire::{validator::Validation, CustomUserError, Text};
use tracing::info;

use crate::{
    types::Token,
    utils::{ensure_homdir_exists, posthog_home_dir},
};

pub trait CredentialProvider {
    fn get_credentials(&self) -> Result<Token, Error>;
    fn store_credentials(&self, token: Token) -> Result<(), Error>;
    fn report_location(&self) -> String;
}

pub struct HomeDirProvider;

impl CredentialProvider for HomeDirProvider {
    fn get_credentials(&self) -> Result<Token, Error> {
        let home = posthog_home_dir();
        let file = home.join("credentials.json");
        let token = std::fs::read_to_string(file.clone()).context(format!(
            "While trying to read credentials from file {:?}",
            file
        ))?;
        let token = serde_json::from_str(&token).context("While trying to parse token")?;
        Ok(token)
    }

    fn store_credentials(&self, token: Token) -> Result<(), Error> {
        let home = posthog_home_dir();
        ensure_homdir_exists()?;
        let file = home.join("credentials.json");
        let token = serde_json::to_string(&token).context("While trying to serialize token")?;
        std::fs::write(file.clone(), token).context(format!(
            "While trying to write credentials to file {:?}",
            file
        ))?;
        Ok(())
    }

    fn report_location(&self) -> String {
        posthog_home_dir()
            .join("credentials.json")
            .to_string_lossy()
            .to_string()
    }
}

/// Tries to read the token from the env var `POSTHOG_CLI_TOKEN`
pub struct EnvVarProvider;

impl CredentialProvider for EnvVarProvider {
    fn get_credentials(&self) -> Result<Token, Error> {
        let token = std::env::var("POSTHOG_CLI_TOKEN").context("While trying to read env var")?;
        Ok(Token { token })
    }

    fn store_credentials(&self, _token: Token) -> Result<(), Error> {
        Ok(())
    }

    fn report_location(&self) -> String {
        unimplemented!("We should never try to save a credential to the env");
    }
}

fn token_validator(token: &str) -> Result<Validation, CustomUserError> {
    if token.is_empty() {
        return Ok(Validation::Invalid("Token cannot be empty".into()));
    };

    if !token.starts_with("phx_") {
        return Ok(Validation::Invalid(
            "Token looks wrong, must start with 'phx_'".into(),
        ));
    }

    Ok(Validation::Valid)
}

pub fn login() -> Result<(), Error> {
    let token = Text::new(
        "Enter your personal API token (see posthog.com/docs/api#private-endpoint-authentication)",
    )
    .with_validator(token_validator)
    .prompt()?;
    let token = Token { token };
    let provider = HomeDirProvider;
    provider.store_credentials(token)?;
    info!("Token saved to: {}", provider.report_location());
    Ok(())
}
