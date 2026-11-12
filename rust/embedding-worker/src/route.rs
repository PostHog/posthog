use std::fmt::Write;

use anyhow::{bail, Result};
use common_types::embedding::EmbeddingModel;
use reqwest::{Client, Method, Request, RequestBuilder, Url};
use serde_json::{Map, Value};

use crate::metrics_utils::RequestLabels;

pub const AI_GATEWAY_PRODUCT: &str = "embedding_worker";

#[derive(Debug, Clone, Copy, Default)]
pub struct RouteSettings<'a> {
    pub openai_api_key: Option<&'a str>,
    pub ai_gateway_url: Option<&'a str>,
    pub ai_gateway_api_key: Option<&'a str>,
}

#[derive(Debug, Clone)]
pub enum EmbeddingRoute {
    OpenAI { api_key: String },
    AIGateway { endpoint: Url, api_key: String },
}

impl EmbeddingRoute {
    pub fn resolve(settings: RouteSettings) -> Result<Self> {
        let present = |value: Option<&str>| value.filter(|v| !v.is_empty()).map(str::to_string);
        let openai_api_key = present(settings.openai_api_key);
        let ai_gateway_url = present(settings.ai_gateway_url);
        let ai_gateway_api_key = present(settings.ai_gateway_api_key);

        match (ai_gateway_url, ai_gateway_api_key) {
            (Some(url), Some(api_key)) => {
                let endpoint = Url::parse(&format!("{}/embeddings", url.trim_end_matches('/')))?;
                Ok(Self::AIGateway { endpoint, api_key })
            }
            (None, None) => match openai_api_key {
                Some(api_key) => Ok(Self::OpenAI { api_key }),
                None => bail!("Set AI_GATEWAY_URL and AI_GATEWAY_API_KEY, or OPENAI_API_KEY"),
            },
            _ => bail!("AI_GATEWAY_URL and AI_GATEWAY_API_KEY must be set together"),
        }
    }

    pub fn construct_request(
        &self,
        content: &str,
        model: EmbeddingModel,
        labels: &RequestLabels,
        client: Client,
    ) -> Request {
        let builder = match self {
            Self::OpenAI { api_key } => {
                let url = model
                    .model_url()
                    .parse()
                    .expect("The models enum only produces valid urls");
                RequestBuilder::from_parts(client, Request::new(Method::POST, url))
                    .header("Authorization", format!("Bearer {api_key}"))
            }
            Self::AIGateway { endpoint, api_key } => {
                RequestBuilder::from_parts(client, Request::new(Method::POST, endpoint.clone()))
                    .header("Authorization", format!("Bearer {api_key}"))
                    .header("X-PostHog-Product", AI_GATEWAY_PRODUCT)
                    .header("X-PostHog-Billable", "false")
                    .header("X-PostHog-Privacy-Mode", "true")
                    .header("X-PostHog-Properties", gateway_properties(labels))
            }
        };

        builder
            .header("Content-Type", "application/json")
            .json(&model.construct_request_body(content))
            .build()
            .expect("we manage to build the request")
    }
}

fn gateway_properties(labels: &RequestLabels) -> String {
    let mut properties = Map::new();
    properties.insert(
        "ai_product".to_string(),
        Value::String(AI_GATEWAY_PRODUCT.to_string()),
    );
    for (key, value) in labels.render() {
        properties.insert(format!("embedding_{key}"), Value::String(value.clone()));
    }

    let json = Value::Object(properties).to_string();
    let mut header = String::with_capacity(json.len());
    for character in json.chars() {
        if character.is_ascii() && !character.is_ascii_control() {
            header.push(character);
        } else {
            for unit in character.encode_utf16(&mut [0; 2]) {
                write!(header, "\\u{unit:04x}").expect("writing to a String cannot fail");
            }
        }
    }
    header
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
    fn test_gateway_request_is_private_unbilled_and_attributed() {
        let route = EmbeddingRoute::resolve(RouteSettings {
            openai_api_key: Some("sk-direct"),
            ai_gateway_url: Some("https://ai-gateway.example.com/v1/"),
            ai_gateway_api_key: Some("phs_test"),
        })
        .unwrap();
        let labels = RequestLabels::default().and([("product", "llma"), ("rendering", "résumé")]);

        let request = route.construct_request(
            "hello",
            EmbeddingModel::OpenAITextEmbeddingSmall,
            &labels,
            Client::new(),
        );

        let header = |name: &str| request.headers().get(name).unwrap().to_str().unwrap();
        assert_eq!(
            request.url().as_str(),
            "https://ai-gateway.example.com/v1/embeddings"
        );
        assert_eq!(header("Authorization"), "Bearer phs_test");
        assert_eq!(header("X-PostHog-Product"), AI_GATEWAY_PRODUCT);
        assert_eq!(header("X-PostHog-Billable"), "false");
        assert_eq!(header("X-PostHog-Privacy-Mode"), "true");
        let properties: Value = serde_json::from_str(header("X-PostHog-Properties")).unwrap();
        assert_eq!(
            properties,
            serde_json::json!({
                "ai_product": AI_GATEWAY_PRODUCT,
                "embedding_product": "llma",
                "embedding_rendering": "résumé",
            })
        );
    }
}
