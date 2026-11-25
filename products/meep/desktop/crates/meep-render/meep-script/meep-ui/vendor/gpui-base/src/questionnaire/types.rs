use std::{error::Error, fmt, rc::Rc};

use gpui::{Entity, SharedString};

use crate::input::InputState;

/// Validates one questionnaire item against the current questionnaire answers.
pub type QuestionnaireValidator =
    Rc<dyn Fn(&QuestionnaireValidationContext) -> Result<(), SharedString> + 'static>;

/// Describes one selectable answer.
#[derive(Clone, Debug)]
pub struct QuestionnaireChoiceDefinition {
    value: SharedString,
    accessibility_label: SharedString,
    description: Option<SharedString>,
    disabled: bool,
    default_selected: bool,
}

impl QuestionnaireChoiceDefinition {
    pub fn new(
        value: impl Into<SharedString>,
        accessibility_label: impl Into<SharedString>,
    ) -> Self {
        Self {
            value: value.into(),
            accessibility_label: accessibility_label.into(),
            description: None,
            disabled: false,
            default_selected: false,
        }
    }

    pub fn with_description(mut self, description: impl Into<SharedString>) -> Self {
        self.description = Some(description.into());
        self
    }

    pub fn with_disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    pub fn with_default_selected(mut self, selected: bool) -> Self {
        self.default_selected = selected;
        self
    }

    pub fn value(&self) -> &SharedString {
        &self.value
    }

    pub fn accessibility_label(&self) -> &SharedString {
        &self.accessibility_label
    }

    pub fn description(&self) -> Option<&SharedString> {
        self.description.as_ref()
    }

    pub fn is_disabled(&self) -> bool {
        self.disabled
    }

    pub fn is_default_selected(&self) -> bool {
        self.default_selected
    }
}

/// Describes the optional freeform answer owned by an item.
#[derive(Clone, Debug)]
pub struct QuestionnaireInputDefinition {
    state: Entity<InputState>,
    accessibility_label: SharedString,
    disabled: bool,
}

impl QuestionnaireInputDefinition {
    pub fn new(state: Entity<InputState>, accessibility_label: impl Into<SharedString>) -> Self {
        Self {
            state,
            accessibility_label: accessibility_label.into(),
            disabled: false,
        }
    }

    pub fn with_disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    pub fn state(&self) -> &Entity<InputState> {
        &self.state
    }

    pub fn accessibility_label(&self) -> &SharedString {
        &self.accessibility_label
    }

    pub fn is_disabled(&self) -> bool {
        self.disabled
    }
}

/// Describes one ordered questionnaire item.
#[derive(Clone)]
pub struct QuestionnaireItemDefinition {
    name: SharedString,
    accessibility_label: SharedString,
    description: Option<SharedString>,
    required: bool,
    multiple: bool,
    disabled: bool,
    choices: Vec<QuestionnaireChoiceDefinition>,
    input: Option<QuestionnaireInputDefinition>,
    validator: Option<QuestionnaireValidator>,
}

impl fmt::Debug for QuestionnaireItemDefinition {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("QuestionnaireItemDefinition")
            .field("name", &self.name)
            .field("accessibility_label", &self.accessibility_label)
            .field("description", &self.description)
            .field("required", &self.required)
            .field("multiple", &self.multiple)
            .field("disabled", &self.disabled)
            .field("choices", &self.choices)
            .field("input", &self.input)
            .field("validator", &self.validator.as_ref().map(|_| "<validator>"))
            .finish()
    }
}

impl QuestionnaireItemDefinition {
    pub fn new(
        name: impl Into<SharedString>,
        accessibility_label: impl Into<SharedString>,
    ) -> Self {
        Self {
            name: name.into(),
            accessibility_label: accessibility_label.into(),
            description: None,
            required: false,
            multiple: false,
            disabled: false,
            choices: Vec::new(),
            input: None,
            validator: None,
        }
    }

    pub fn with_description(mut self, description: impl Into<SharedString>) -> Self {
        self.description = Some(description.into());
        self
    }

    pub fn with_required(mut self, required: bool) -> Self {
        self.required = required;
        self
    }

    pub fn with_multiple(mut self, multiple: bool) -> Self {
        self.multiple = multiple;
        self
    }

    pub fn with_disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    pub fn with_choices(
        mut self,
        choices: impl IntoIterator<Item = QuestionnaireChoiceDefinition>,
    ) -> Self {
        self.choices = choices.into_iter().collect();
        self
    }

    pub fn with_choice(mut self, choice: QuestionnaireChoiceDefinition) -> Self {
        self.choices.push(choice);
        self
    }

    pub fn with_input(mut self, input: QuestionnaireInputDefinition) -> Self {
        self.input = Some(input);
        self
    }

    pub fn with_validator(
        mut self,
        validator: impl Fn(&QuestionnaireValidationContext) -> Result<(), SharedString> + 'static,
    ) -> Self {
        self.validator = Some(Rc::new(validator));
        self
    }

    pub fn name(&self) -> &SharedString {
        &self.name
    }

    pub fn accessibility_label(&self) -> &SharedString {
        &self.accessibility_label
    }

    pub fn description(&self) -> Option<&SharedString> {
        self.description.as_ref()
    }

    pub fn is_required(&self) -> bool {
        self.required
    }

    pub fn is_multiple(&self) -> bool {
        self.multiple
    }

    pub fn is_disabled(&self) -> bool {
        self.disabled
    }

    pub fn choices(&self) -> &[QuestionnaireChoiceDefinition] {
        &self.choices
    }

    pub fn input(&self) -> Option<&QuestionnaireInputDefinition> {
        self.input.as_ref()
    }

    pub fn validator(&self) -> Option<&QuestionnaireValidator> {
        self.validator.as_ref()
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum QuestionnaireItemStatus {
    #[default]
    Unanswered,
    Answered,
    Skipped,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum QuestionnaireShortcutMode {
    Letters,
    Numbers,
}

/// A serializable-in-spirit answer snapshot. Input drafts are deliberately excluded.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct QuestionnaireAnswer {
    pub(crate) choices: Vec<SharedString>,
    pub(crate) freeform: Option<SharedString>,
}

impl QuestionnaireAnswer {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_choices(
        mut self,
        choices: impl IntoIterator<Item = impl Into<SharedString>>,
    ) -> Self {
        self.choices.clear();
        for choice in choices.into_iter().map(Into::into) {
            if !self.choices.contains(&choice) {
                self.choices.push(choice);
            }
        }
        self
    }

    pub fn with_freeform(mut self, value: impl Into<SharedString>) -> Self {
        let value = value.into();
        self.freeform = (!value.trim().is_empty()).then_some(value);
        self
    }

    pub fn choices(&self) -> &[SharedString] {
        &self.choices
    }

    pub fn freeform(&self) -> Option<&SharedString> {
        self.freeform.as_ref()
    }

    pub fn is_empty(&self) -> bool {
        self.choices.is_empty() && self.freeform.is_none()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct QuestionnaireAnswers {
    entries: Vec<(SharedString, QuestionnaireAnswer)>,
}

impl QuestionnaireAnswers {
    pub(crate) fn from_entries(entries: Vec<(SharedString, QuestionnaireAnswer)>) -> Self {
        Self { entries }
    }

    pub fn get(&self, name: &str) -> Option<&QuestionnaireAnswer> {
        self.entries
            .iter()
            .find_map(|(item, answer)| (item.as_ref() == name).then_some(answer))
    }

    pub fn iter(&self) -> impl Iterator<Item = (&SharedString, &QuestionnaireAnswer)> {
        self.entries.iter().map(|(name, answer)| (name, answer))
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct QuestionnaireProgressState {
    current: usize,
    total: usize,
}

impl QuestionnaireProgressState {
    pub(crate) fn new(current: usize, total: usize) -> Self {
        Self { current, total }
    }

    pub fn current(&self) -> usize {
        self.current
    }

    pub fn total(&self) -> usize {
        self.total
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct QuestionnaireItemState {
    name: SharedString,
    status: QuestionnaireItemStatus,
    required: bool,
    multiple: bool,
    disabled: bool,
    invalid: bool,
    has_input: bool,
}

impl QuestionnaireItemState {
    pub(crate) fn new(
        name: SharedString,
        status: QuestionnaireItemStatus,
        required: bool,
        multiple: bool,
        disabled: bool,
        invalid: bool,
        has_input: bool,
    ) -> Self {
        Self {
            name,
            status,
            required,
            multiple,
            disabled,
            invalid,
            has_input,
        }
    }

    pub fn name(&self) -> &SharedString {
        &self.name
    }

    pub fn status(&self) -> QuestionnaireItemStatus {
        self.status
    }

    pub fn is_required(&self) -> bool {
        self.required
    }

    pub fn is_multiple(&self) -> bool {
        self.multiple
    }

    pub fn is_disabled(&self) -> bool {
        self.disabled
    }

    pub fn is_invalid(&self) -> bool {
        self.invalid
    }

    pub fn has_input(&self) -> bool {
        self.has_input
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct QuestionnaireChoiceState {
    value: SharedString,
    selected: bool,
    disabled: bool,
    invalid: bool,
    shortcut: Option<SharedString>,
}

impl QuestionnaireChoiceState {
    pub(crate) fn new(
        value: SharedString,
        selected: bool,
        disabled: bool,
        invalid: bool,
        shortcut: Option<SharedString>,
    ) -> Self {
        Self {
            value,
            selected,
            disabled,
            invalid,
            shortcut,
        }
    }

    pub fn value(&self) -> &SharedString {
        &self.value
    }

    pub fn is_selected(&self) -> bool {
        self.selected
    }

    pub fn is_disabled(&self) -> bool {
        self.disabled
    }

    pub fn is_invalid(&self) -> bool {
        self.invalid
    }

    pub fn shortcut(&self) -> Option<&SharedString> {
        self.shortcut.as_ref()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct QuestionnaireNavigationState {
    previous_visible: bool,
    next_visible: bool,
    skip_visible: bool,
    submit_visible: bool,
    confirmable: bool,
}

impl QuestionnaireNavigationState {
    pub(crate) fn new(
        previous_visible: bool,
        next_visible: bool,
        skip_visible: bool,
        submit_visible: bool,
        confirmable: bool,
    ) -> Self {
        Self {
            previous_visible,
            next_visible,
            skip_visible,
            submit_visible,
            confirmable,
        }
    }

    pub fn is_previous_visible(&self) -> bool {
        self.previous_visible
    }

    pub fn is_next_visible(&self) -> bool {
        self.next_visible
    }

    pub fn is_skip_visible(&self) -> bool {
        self.skip_visible
    }

    pub fn is_submit_visible(&self) -> bool {
        self.submit_visible
    }

    pub fn is_confirmable(&self) -> bool {
        self.confirmable
    }
}

/// Immutable validation input. Validators cannot mutate the questionnaire.
#[derive(Clone, Debug)]
pub struct QuestionnaireValidationContext {
    item: SharedString,
    answer: QuestionnaireAnswer,
    answers: QuestionnaireAnswers,
}

impl QuestionnaireValidationContext {
    pub(crate) fn new(
        item: SharedString,
        answer: QuestionnaireAnswer,
        answers: QuestionnaireAnswers,
    ) -> Self {
        Self {
            item,
            answer,
            answers,
        }
    }

    pub fn item(&self) -> &SharedString {
        &self.item
    }

    pub fn answer(&self) -> &QuestionnaireAnswer {
        &self.answer
    }

    pub fn answers(&self) -> &QuestionnaireAnswers {
        &self.answers
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct QuestionnaireAnswerChange {
    item: SharedString,
    answer: QuestionnaireAnswer,
    status: QuestionnaireItemStatus,
}

impl QuestionnaireAnswerChange {
    pub(crate) fn new(
        item: SharedString,
        answer: QuestionnaireAnswer,
        status: QuestionnaireItemStatus,
    ) -> Self {
        Self {
            item,
            answer,
            status,
        }
    }

    pub fn item(&self) -> &SharedString {
        &self.item
    }

    pub fn answer(&self) -> &QuestionnaireAnswer {
        &self.answer
    }

    pub fn status(&self) -> QuestionnaireItemStatus {
        self.status
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct QuestionnaireSubmissionItem {
    name: SharedString,
    status: QuestionnaireItemStatus,
    answer: QuestionnaireAnswer,
}

impl QuestionnaireSubmissionItem {
    pub(crate) fn new(
        name: SharedString,
        status: QuestionnaireItemStatus,
        answer: QuestionnaireAnswer,
    ) -> Self {
        Self {
            name,
            status,
            answer,
        }
    }

    pub fn name(&self) -> &SharedString {
        &self.name
    }

    pub fn status(&self) -> QuestionnaireItemStatus {
        self.status
    }

    pub fn answer(&self) -> &QuestionnaireAnswer {
        &self.answer
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct QuestionnaireSubmission {
    items: Vec<QuestionnaireSubmissionItem>,
}

impl QuestionnaireSubmission {
    pub(crate) fn new(items: Vec<QuestionnaireSubmissionItem>) -> Self {
        Self { items }
    }

    pub fn items(&self) -> &[QuestionnaireSubmissionItem] {
        &self.items
    }

    pub fn answer(&self, name: &str) -> Option<&QuestionnaireAnswer> {
        self.items
            .iter()
            .find_map(|item| (item.name.as_ref() == name).then_some(&item.answer))
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
#[non_exhaustive]
pub enum QuestionnaireEvent {
    CurrentItemChanged {
        previous: Option<SharedString>,
        current: Option<SharedString>,
    },
    AnswerChanged(QuestionnaireAnswerChange),
    Completed(QuestionnaireSubmission),
    Submit(QuestionnaireSubmission),
}

/// Why an item currently fails validation.
///
/// `Required` and `Unanswered` carry no text: base does not own product copy,
/// so the presentation layer supplies the localized sentence. `Message` is the
/// text a validator or the host already wrote.
#[derive(Clone, Debug, PartialEq, Eq)]
#[non_exhaustive]
pub enum QuestionnaireValidationError {
    /// A required item has no answer.
    Required,
    /// An optional item has no answer and has not been skipped.
    Unanswered,
    /// A validator or the host supplied this text.
    Message(SharedString),
}

impl QuestionnaireValidationError {
    /// The text the host or a validator wrote, if this is not a built-in reason.
    pub fn message(&self) -> Option<&SharedString> {
        match self {
            Self::Message(message) => Some(message),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
#[non_exhaustive]
pub enum QuestionnaireSchemaError {
    DuplicateItem(SharedString),
    DuplicateChoice {
        item: SharedString,
        choice: SharedString,
    },
    MultipleDefaultsForSingleItem(SharedString),
    UnknownItem(SharedString),
    UnknownChoice {
        item: SharedString,
        choice: SharedString,
    },
    AnswerDoesNotMatchItem(SharedString),
}

impl fmt::Display for QuestionnaireSchemaError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::DuplicateItem(item) => write!(formatter, "duplicate questionnaire item `{item}`"),
            Self::DuplicateChoice { item, choice } => {
                write!(formatter, "duplicate choice `{choice}` in item `{item}`")
            }
            Self::MultipleDefaultsForSingleItem(item) => write!(
                formatter,
                "single-choice item `{item}` has more than one default answer"
            ),
            Self::UnknownItem(item) => write!(formatter, "unknown questionnaire item `{item}`"),
            Self::UnknownChoice { item, choice } => {
                write!(formatter, "unknown choice `{choice}` in item `{item}`")
            }
            Self::AnswerDoesNotMatchItem(item) => {
                write!(formatter, "answer does not match item `{item}`")
            }
        }
    }
}

impl Error for QuestionnaireSchemaError {}
