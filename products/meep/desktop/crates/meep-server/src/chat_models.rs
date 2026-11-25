//! The model a topic's chat answers with, chosen from its PostHog account's catalogue.
use crate::accounts::Accounts;
use anyhow::Result;
use meep_topic::TopicId;
use meep_wire::ChatModelChoice;
use meep_wire::{ChatModel, ChatModels};

/// Choices live beside connector checkpoints, which already survive restarts.
fn key(topic: TopicId) -> String {
    format!("chat-model/{topic}")
}

#[derive(Debug)]
pub(super) struct MissingTopicGrant;
impl std::fmt::Display for MissingTopicGrant {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("This topic needs access to the connected PostHog account.")
    }
}

/// A caller chose a model or billing combination the catalogue does not offer.
#[derive(Debug)]
pub(super) struct InvalidChoice(&'static str);
impl std::fmt::Display for InvalidChoice {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.0)
    }
}
impl std::error::Error for InvalidChoice {}

impl Accounts {
    /// Every catalogue model and the tools available to it on this host.
    pub(crate) async fn chat_models(&self, topic: TopicId) -> Result<ChatModels> {
        let (_, p) = self.project(topic).map_err(|error| {
            if self.get("posthog").is_some_and(|a| {
                a.project.is_some() && a.project_ready.load(std::sync::atomic::Ordering::Acquire)
            }) && !self
                .all()
                .iter()
                .any(|a| a.project.is_some() && a.public.grants.contains(&topic))
            {
                return error.context(MissingTopicGrant);
            }
            error
        })?;
        let tools = self.public_base.read().is_some();
        let tasks = meep_posthog::tasks::Tasks::new(&p.origin, p.project)?;
        let defaults = tasks.run_defaults(&p.token).await?;
        let models: Vec<_> = tasks
            .models(&p.token)
            .await?
            .into_iter()
            .map(|m| ChatModel {
                meep_tools: tools && m.supports_imported_mcp(),
                supported_efforts: m.supported_efforts,
                id: m.model,
                name: m.display_name,
                runtime: m.runtime_adapter,
            })
            .collect();
        let default_model = defaults.model.as_ref().map(|id| {
            let mut model = models
                .iter()
                .find(|m| &m.id == id)
                .cloned()
                .unwrap_or_else(|| ChatModel {
                    id: id.clone(),
                    name: id.clone(),
                    runtime: defaults.runtime_adapter.clone(),
                    meep_tools: false,
                    supported_efforts: vec![],
                });
            if defaults.runtime == "pi" {
                model.runtime = Some("pi".to_owned());
                model.meep_tools = false;
            }
            model
        });
        let choice = self.chat_choice(topic)?;
        let selected = choice.model.filter(|id| models.iter().any(|m| m.id == *id));
        let billing = selected.as_ref().and(choice.billing);
        Ok(ChatModels {
            models,
            selected,
            billing,
            default_model,
            default_effort: defaults.reasoning_effort,
        })
    }

    /// Models a view can be built with. Building talks to the view through an
    /// imported MCP server, so only models that import it are offered.
    pub(crate) async fn view_models(&self) -> Result<ChatModels> {
        let p = self
            .get("posthog")
            .filter(|a| a.project_ready.load(std::sync::atomic::Ordering::Acquire))
            .and_then(|a| a.project.clone())
            .ok_or_else(|| anyhow::anyhow!("Connect PostHog to build views."))?;
        let models = meep_posthog::tasks::Tasks::new(&p.origin, p.project)?
            .models(&p.token)
            .await?
            .into_iter()
            .filter(|m| m.supports_imported_mcp())
            .map(|m| ChatModel {
                meep_tools: true,
                supported_efforts: m.supported_efforts,
                id: m.model,
                name: m.display_name,
                runtime: m.runtime_adapter,
            })
            .collect();
        Ok(ChatModels {
            models,
            selected: None,
            billing: None,
            default_model: None,
            default_effort: None,
        })
    }

    /// The model chosen for the topic's chat answers, if any.
    #[cfg(test)]
    pub(crate) fn chat_model(&self, topic: TopicId) -> Result<Option<String>> {
        Ok(self.chat_choice(topic)?.model)
    }

    pub(crate) fn chat_choice(&self, topic: TopicId) -> Result<ChatModelChoice> {
        let value = self
            .checkpoints
            .load(&key(topic))
            .map_err(meep_engine::Error::from)?
            .unwrap_or_default();
        if value.is_object() {
            return Ok(serde_json::from_value(value)?);
        }
        Ok(ChatModelChoice {
            model: value.as_str().map(str::to_owned),
            billing: None,
        })
    }

    /// Choose a model the account offers, or restore the default with `None`.
    pub(crate) async fn set_chat_model(
        &self,
        topic: TopicId,
        choice: ChatModelChoice,
    ) -> Result<ChatModels> {
        let mut catalogue = self.chat_models(topic).await?;
        if let Some(id) = &choice.model
            && !catalogue.models.iter().any(|m| m.id == *id)
        {
            return Err(InvalidChoice(
                "This PostHog account doesn't offer that model for this topic",
            )
            .into());
        }
        if let Some(access) = choice.billing.as_deref()
            && !(matches!(access, "own-subscription" | "posthog-gateway")
                && catalogue.models.iter().any(|m| {
                    Some(&m.id) == choice.model.as_ref() && m.runtime.as_deref() == Some("codex")
                }))
        {
            return Err(
                InvalidChoice("Choose a Codex model and a supported billing option").into(),
            );
        }
        let key = key(topic);
        let previous = self
            .checkpoints
            .load(&key)
            .map_err(meep_engine::Error::from)?;
        self.checkpoints
            .commit(&key, previous.as_ref(), &serde_json::to_value(&choice)?)
            .map_err(meep_engine::Error::from)?;
        catalogue.selected = choice.model;
        catalogue.billing = choice.billing;
        Ok(catalogue)
    }
}
