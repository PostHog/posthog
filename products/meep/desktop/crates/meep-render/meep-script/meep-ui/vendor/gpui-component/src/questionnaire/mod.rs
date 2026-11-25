//! Composable questionnaire controls.
//!
//! The behavior — answers, validation, navigation, focus and shortcuts — lives
//! in [`gpui_base::questionnaire`]; this module is its skin. The public path
//! stays `gpui_component::questionnaire::*` for both halves.

mod components;

pub use components::*;
pub use gpui_base::questionnaire::{
    QuestionnaireAnswer, QuestionnaireAnswerChange, QuestionnaireAnswers,
    QuestionnaireChoiceDefinition, QuestionnaireChoiceState, QuestionnaireEvent,
    QuestionnaireInputDefinition, QuestionnaireItemDefinition, QuestionnaireItemState,
    QuestionnaireItemStatus, QuestionnaireNavigationState, QuestionnaireProgressState,
    QuestionnaireSchemaError, QuestionnaireShortcutMode, QuestionnaireState,
    QuestionnaireSubmission, QuestionnaireSubmissionItem, QuestionnaireValidationContext,
    QuestionnaireValidationError, QuestionnaireValidator,
};

pub(crate) fn init(_: &mut gpui::App) {}
