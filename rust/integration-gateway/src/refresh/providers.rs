use crate::config::Config;

/// Resolved OAuth provider config for a refreshable integration kind.
pub struct Provider {
    pub token_url: String,
    pub client_id: String,
    pub client_secret: String,
}

/// Resolve the OAuth provider for `kind`, or `None` when the kind isn't a gateway-supported OAuth2
/// provider or its client credentials aren't configured.
///
/// Initial supported set is the generic `grant_type=refresh_token` providers (client id/secret in
/// the form body). Providers with non-standard refresh flows — Slack (DB-sourced creds), the
/// HTTP-Basic ones (reddit/pinterest/stripe), TikTok (different host + `client_key`), Bing (resends
/// scope), Jira (rotates refresh tokens), Meta (long-lived exchange), and the service-account /
/// GitHub kinds — stay on the Django beat for now.
///
/// `config.refresh_token_url_override`, when set, replaces the provider URL for every kind (local
/// e2e against a mock token endpoint).
pub fn provider_for(kind: &str, config: &Config) -> Option<Provider> {
    let (default_url, client_id, client_secret): (&str, &str, &str) = match kind {
        "hubspot" => (
            "https://api.hubapi.com/oauth/v1/token",
            config.hubspot_client_id.as_str(),
            config.hubspot_client_secret.as_str(),
        ),
        "salesforce" => (
            "https://login.salesforce.com/services/oauth2/token",
            config.salesforce_client_id.as_str(),
            config.salesforce_client_secret.as_str(),
        ),
        "google-ads" => (
            "https://oauth2.googleapis.com/token",
            config.google_ads_client_id.as_str(),
            config.google_ads_client_secret.as_str(),
        ),
        "google-analytics" => (
            "https://oauth2.googleapis.com/token",
            config.google_analytics_client_id.as_str(),
            config.google_analytics_client_secret.as_str(),
        ),
        "google-search-console" => (
            "https://oauth2.googleapis.com/token",
            config.google_search_console_client_id.as_str(),
            config.google_search_console_client_secret.as_str(),
        ),
        "google-sheets" => (
            "https://oauth2.googleapis.com/token",
            config.google_sheets_client_id.as_str(),
            config.google_sheets_client_secret.as_str(),
        ),
        _ => return None,
    };

    if client_id.is_empty() || client_secret.is_empty() {
        return None;
    }

    let token_url = if config.refresh_token_url_override.is_empty() {
        default_url.to_string()
    } else {
        config.refresh_token_url_override.clone()
    };

    Some(Provider {
        token_url,
        client_id: client_id.to_string(),
        client_secret: client_secret.to_string(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use envconfig::Envconfig;

    // A Config with all defaults, credential fields explicitly cleared so ambient env can't leak in.
    // Fields are pub, so tests set exactly what they exercise — no process-env mutation (race-free).
    fn base() -> Config {
        let mut c = Config::init_from_env().unwrap();
        c.hubspot_client_id = String::new();
        c.hubspot_client_secret = String::new();
        c.refresh_token_url_override = String::new();
        c
    }

    #[test]
    fn unknown_kind_has_no_provider() {
        let config = base();
        assert!(provider_for("slack", &config).is_none());
        assert!(provider_for("github", &config).is_none());
    }

    #[test]
    fn kind_without_credentials_is_skipped() {
        assert!(provider_for("hubspot", &base()).is_none());
    }

    #[test]
    fn configured_kind_resolves_and_override_applies() {
        let mut config = base();
        config.hubspot_client_id = "cid".to_string();
        config.hubspot_client_secret = "secret".to_string();
        config.refresh_token_url_override = "http://localhost:9999/token".to_string();

        let provider = provider_for("hubspot", &config).expect("provider");
        assert_eq!(provider.client_id, "cid");
        assert_eq!(provider.client_secret, "secret");
        assert_eq!(provider.token_url, "http://localhost:9999/token");
    }
}
