use meep_protocol::sessions::{ElementReference, MessageAttachment};
pub use meep_ui::composer::*;

/// An unsent message and the references and attachments collected with it.
pub struct DraftMessage {
    /// Draft text from the composer.
    pub prompt: String,
    /// Elements selected for inclusion as context.
    pub references: Vec<ElementReference>,
    /// Files attached to the draft.
    pub attachments: Vec<MessageAttachment>,
}

impl DraftMessage {
    /// Restore the draft ahead of any current prompt and return its attachments.
    pub fn restore(
        self,
        key: &str,
        current: &str,
        prompts: &mut std::collections::HashMap<String, String>,
        references: &mut std::collections::HashMap<String, Vec<ElementReference>>,
    ) -> Vec<MessageAttachment> {
        let value = if current.trim().is_empty() {
            self.prompt
        } else {
            format!("{}\n\n{current}", self.prompt)
        };
        prompts.insert(key.to_owned(), value);
        references
            .entry(key.to_owned())
            .or_default()
            .extend(self.references);
        self.attachments
    }
}

/// Low-level combobox data for embedded forms. The full composer selector lives in
/// [`crate::model_picker::ModelPicker`].
pub use models::{ModelItem, ModelPicker};
mod models {
    use crate::{label, row, text};
    use gpui_kit::{
        component::{
            combobox::ComboboxState,
            searchable_list::{SearchableListItem, SearchableVec},
        },
        prelude::FluentBuilder,
        *,
    };
    use meep_ui::agent_marks::{self, AgentMark};
    /// A searchable model option in an embedded combobox.
    #[derive(Clone)]
    pub struct ModelItem {
        /// Backend identifier sent when this model is chosen.
        pub id: String,
        /// Display name shown in the menu.
        pub name: String,
        /// Optional provider mark shown beside the model.
        pub mark: Option<&'static AgentMark>,
    }
    impl ModelItem {
        /// Build an option and resolve its mark from the runtime and model ID.
        pub fn new(id: String, name: String, runtime: Option<&str>) -> Self {
            let mark = agent_marks::for_model(runtime, &id);
            Self { id, name, mark }
        }
    }
    impl SearchableListItem for ModelItem {
        type Value = String;
        fn title(&self) -> SharedString {
            self.name.clone().into()
        }
        fn value(&self) -> &String {
            &self.id
        }
        fn render(&self, _: &mut Window, _: &mut App) -> impl IntoElement {
            // SearchableVec uses uniform rows: every item, including the default,
            // must have exactly the same height. Never stack a raw ID under a name.
            let name = self
                .name
                .split_once('/')
                .map_or(self.name.as_str(), |(_, n)| n);
            let provider = self
                .id
                .split_once('/')
                .map(|(provider, _)| provider.to_owned());
            row()
                .w_full()
                .min_w_0()
                .h(px(24.))
                .gap(px(10.))
                .child(agent_marks::icon(self.mark, 16.))
                .child(
                    text(name.to_owned())
                        .text_size(px(12.))
                        .truncate()
                        .flex_1()
                        .min_w_0(),
                )
                .when_some(provider, |el, provider| {
                    el.child(
                        label(provider)
                            .text_size(px(10.))
                            .flex_shrink_0()
                            .max_w(px(74.))
                            .truncate(),
                    )
                })
        }

        fn matches(&self, query: &str) -> bool {
            let q = query.to_lowercase();
            self.name.to_lowercase().contains(&q)
                || self.id.to_lowercase().contains(&q)
                || self.mark.is_some_and(|mark| mark.name.contains(&q))
        }
    }
    /// State of an embedded, searchable model combobox.
    pub type ModelPicker = ComboboxState<SearchableVec<ModelItem>>;
}
