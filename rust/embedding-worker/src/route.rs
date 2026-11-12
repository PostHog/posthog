use std::fmt::Write;

use anyhow::{bail, Result};
use common_types::embedding::EmbeddingModel;
use reqwest::{
    header::{HeaderMap, HeaderValue, AUTHORIZATION},
    Client, Request, Url,
};
use serde_json::{Map, Value};

use crate::metrics_utils::RequestLabels;

pub const AI_GATEWAY_PRODUCT: &str = "embedding_worker";

const OPENAI_BASE_URL: &str = "https://api.openai.com/v1";

#[derive(Clone, Copy)]
pub struct RouteSettings<'a> {
    pub openai_api_key: Option<&'a str>,
    pub ai_gateway_url: Option<&'a str>,
    pub ai_gateway_api_key: Option<&'a str>,
}

#[derive(Debug, Clone)]
pub struct EmbeddingRoute {
    endpoint: Url,
    headers: HeaderMap,
    via_ai_gateway: bool,
}

impl EmbeddingRoute {
    pub fn resolve(settings: RouteSettings) -> Result<Self> {
        let present = |value: Option<&str>| value.filter(|v| !v.is_empty()).map(str::to_string);

        let (base_url, api_key, via_ai_gateway) = match (
            present(settings.ai_gateway_url),
            present(settings.ai_gateway_api_key),
        ) {
            (Some(url), Some(api_key)) => (url, api_key, true),
            (None, None) => match present(settings.openai_api_key) {
                Some(api_key) => (OPENAI_BASE_URL.to_string(), api_key, false),
                None => bail!("Set AI_GATEWAY_URL and AI_GATEWAY_API_KEY, or OPENAI_API_KEY"),
            },
            _ => bail!("AI_GATEWAY_URL and AI_GATEWAY_API_KEY must be set together"),
        };

        let endpoint = Url::parse(&format!("{}/embeddings", base_url.trim_end_matches('/')))?;
        if !endpoint.path().ends_with("/v1/embeddings") {
            bail!("AI_GATEWAY_URL must end in /v1");
        }

        let mut authorization = HeaderValue::from_str(&format!("Bearer {api_key}"))?;
        authorization.set_sensitive(true);
        let mut headers = HeaderMap::new();
        headers.insert(AUTHORIZATION, authorization);
        if via_ai_gateway {
            headers.insert(
                "X-PostHog-Product",
                HeaderValue::from_static(AI_GATEWAY_PRODUCT),
            );
            headers.insert("X-PostHog-Billable", HeaderValue::from_static("false"));
            headers.insert("X-PostHog-Privacy-Mode", HeaderValue::from_static("true"));
        }

        Ok(Self {
            endpoint,
            headers,
            via_ai_gateway,
        })
    }

    pub fn construct_request(
        &self,
        content: &str,
        model: EmbeddingModel,
        labels: &RequestLabels,
        client: &Client,
    ) -> Request {
        let mut builder = client
            .post(self.endpoint.clone())
            .headers(self.headers.clone());
        if self.via_ai_gateway {
            builder = builder.header("X-PostHog-Properties", gateway_properties(labels));
        }

        builder
            .json(&model.construct_request_body(content))
            .build()
            .expect("we manage to build the request")
    }
}

fn gateway_properties(labels: &RequestLabels) -> String {
    let properties: Map<String, Value> = labels
        .render()
        .iter()
        .map(|(key, value)| (format!("embedding_{key}"), Value::String(value.clone())))
        .chain([(
            "ai_product".to_string(),
            Value::String(AI_GATEWAY_PRODUCT.to_string()),
        )])
        .collect();

    to_ascii_json(&Value::Object(properties))
}

fn to_ascii_json(value: &Value) -> String {
    let json = value.to_string();
    let mut ascii = String::with_capacity(json.len());
    for character in json.chars() {
        if character.is_ascii() && !character.is_ascii_control() {
            ascii.push(character);
        } else {
            for unit in character.encode_utf16(&mut [0; 2]) {
                write!(ascii, "\\u{unit:04x}").expect("writing to a String cannot fail");
            }
        }
    }
    ascii
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_resolve_requires_a_complete_route() {
        let cases = [
            (Some("sk"), Some("https://gw/v1"), None, false),
            (Some("sk"), None, Some("phs_x"), false),
            (None, None, None, false),
            (None, Some(""), Some("phs_x"), false),
            (None, Some("https://gw"), Some("phs_x"), false),
            (Some("sk"), None, None, true),
            (Some(""), Some("https://gw/v1/"), Some("phs_x"), true),
        ];

        for (openai_api_key, ai_gateway_url, ai_gateway_api_key, resolves) in cases {
            let route = EmbeddingRoute::resolve(RouteSettings {
                openai_api_key,
                ai_gateway_url,
                ai_gateway_api_key,
            });
            assert_eq!(
                route.is_ok(),
                resolves,
                "openai={openai_api_key:?} url={ai_gateway_url:?} key={ai_gateway_api_key:?}"
            );
        }
    }

    #[test]
    fn test_request_targets_the_resolved_route() {
        let labels = RequestLabels::default().and([("product", "llma"), ("rendering", "résumé")]);
        let gateway_properties = serde_json::json!({
            "ai_product": AI_GATEWAY_PRODUCT,
            "embedding_product": "llma",
            "embedding_rendering": "résumé",
        });
        let cases = [
            (
                Some("https://ai-gateway.example.com/v1/"),
                "https://ai-gateway.example.com/v1/embeddings",
                "Bearer phs_test",
                Some(gateway_properties),
            ),
            (
                None,
                "https://api.openai.com/v1/embeddings",
                "Bearer sk-direct",
                None,
            ),
        ];

        for (ai_gateway_url, url, authorization, properties) in cases {
            let route = EmbeddingRoute::resolve(RouteSettings {
                openai_api_key: Some("sk-direct"),
                ai_gateway_url,
                ai_gateway_api_key: ai_gateway_url.map(|_| "phs_test"),
            })
            .unwrap();

            let request = route.construct_request(
                "hello",
                EmbeddingModel::OpenAITextEmbeddingSmall,
                &labels,
                &Client::new(),
            );

            let header = |name: &str| {
                request
                    .headers()
                    .get(name)
                    .map(|value| value.to_str().unwrap())
            };
            assert_eq!(request.url().as_str(), url);
            assert_eq!(header("Authorization"), Some(authorization));
            assert_eq!(header("Content-Type"), Some("application/json"));
            match properties {
                Some(properties) => {
                    assert_eq!(header("X-PostHog-Product"), Some(AI_GATEWAY_PRODUCT));
                    assert_eq!(header("X-PostHog-Billable"), Some("false"));
                    assert_eq!(header("X-PostHog-Privacy-Mode"), Some("true"));
                    let sent: Value =
                        serde_json::from_str(header("X-PostHog-Properties").unwrap()).unwrap();
                    assert_eq!(sent, properties);
                }
                None => {
                    let posthog_headers = request
                        .headers()
                        .keys()
                        .filter(|name| name.as_str().starts_with("x-posthog-"))
                        .count();
                    assert_eq!(posthog_headers, 0);
                }
            }
        }
    }
}
