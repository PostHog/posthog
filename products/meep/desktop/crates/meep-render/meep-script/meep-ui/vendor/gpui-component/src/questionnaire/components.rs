use std::rc::Rc;

use gpui::{
    AnyElement, App, ElementId, Entity, InteractiveElement, IntoElement, ParentElement, RenderOnce,
    Role, SharedString, StatefulInteractiveElement, StyleRefinement, Styled, Window, div,
    prelude::FluentBuilder as _, svg,
};
use gpui_base::RadioGroup;
use rust_i18n::t;

use crate::{
    ActiveTheme as _, IconName, Sizable, Size, StyledExt as _, ThemeStyled as _,
    button::{Button, ButtonVariants as _},
    icon::IconNamed as _,
    input::Input,
    kbd::Kbd,
};

use gpui_base::questionnaire::{
    QuestionnaireChoiceControl, QuestionnaireChoiceState, QuestionnaireState,
    QuestionnaireValidationError,
};

type ChoiceRenderer =
    Rc<dyn Fn(&QuestionnaireChoiceState, &mut Window, &mut App) -> AnyElement + 'static>;

/// Where a questionnaire's scale lives between the root and its parts.
///
/// GPUI has no style cascade, and `with_rem_size` resolves during layout, which
/// a `RenderOnce` part cannot reach. So the root records the scale it was given
/// under its state's id, and every part of that questionnaire reads it back. A
/// part still accepts its own `with_size`, which wins.
///
/// A root renders before its children, so the entry is in place by the time a
/// part looks for it; a part rendered outside a root falls back to `Medium`.
#[derive(Default)]
struct QuestionnaireSizes(std::collections::HashMap<gpui::EntityId, Size>);

impl gpui::Global for QuestionnaireSizes {}

/// Bounded so an application that builds and drops many questionnaires cannot
/// grow the table without end. Every root rewrites its entry on the next frame,
/// so clearing it costs at most one frame at the default scale.
const MAX_TRACKED_QUESTIONNAIRES: usize = 128;

fn publish_size(state: &Entity<QuestionnaireState>, size: Size, cx: &mut App) {
    let id = state.entity_id();
    let sizes = cx.default_global::<QuestionnaireSizes>();
    if sizes.0.len() >= MAX_TRACKED_QUESTIONNAIRES && !sizes.0.contains_key(&id) {
        sizes.0.clear();
    }
    sizes.0.insert(id, size);
}

fn resolve_size(own: Option<Size>, state: &Entity<QuestionnaireState>, cx: &App) -> Size {
    own.unwrap_or_else(|| {
        cx.try_global::<QuestionnaireSizes>()
            .and_then(|sizes| sizes.0.get(&state.entity_id()).copied())
            .unwrap_or(Size::Medium)
    })
}

/// The questionnaire skin's geometry, following the ReUI `base-nova`
/// questionnaire at `Medium`. Every number comes from the semantic spacing and
/// radius tokens; the size picks which of them apply.
#[derive(Clone, Copy)]
struct QuestionnaireMetrics {
    root_gap: gpui::Pixels,
    item_gap: gpui::Pixels,
    choices_gap: gpui::Pixels,
    choice_gap: gpui::Pixels,
    content_gap: gpui::Pixels,
    choice_padding_x: gpui::Pixels,
    choice_padding_y: gpui::Pixels,
    choice_min_height: gpui::Pixels,
    choice_radius: gpui::Pixels,
    indicator_size: gpui::Pixels,
    indicator_mark_size: gpui::Pixels,
    indicator_check_size: gpui::Pixels,
    shortcut_size: gpui::Pixels,
    shortcut_text_size: gpui::Pixels,
    shortcut_radius: gpui::Pixels,
}

impl QuestionnaireMetrics {
    fn new(size: Size, cx: &App) -> Self {
        let tokens = cx.theme().semantic_tokens();
        let spacing = tokens.spacing;
        let radius = tokens.radius;
        match size {
            Size::XSmall => Self {
                root_gap: spacing.sm,
                item_gap: spacing.sm,
                choices_gap: spacing.xs,
                choice_gap: spacing.xs + spacing.xxs,
                content_gap: spacing.xxs,
                choice_padding_x: spacing.sm,
                choice_padding_y: spacing.xs,
                choice_min_height: spacing.xl + spacing.xs,
                choice_radius: radius.md,
                indicator_size: spacing.md,
                indicator_mark_size: spacing.xs + spacing.xxs * 0.5,
                indicator_check_size: spacing.sm + spacing.xxs,
                shortcut_size: spacing.lg,
                shortcut_text_size: spacing.sm,
                shortcut_radius: radius.sm,
            },
            Size::Small => Self {
                root_gap: spacing.md,
                item_gap: spacing.md,
                choices_gap: spacing.xs + spacing.xxs,
                choice_gap: spacing.sm,
                content_gap: spacing.xxs,
                choice_padding_x: spacing.sm + spacing.xxs,
                choice_padding_y: spacing.sm,
                choice_min_height: spacing.xxl + spacing.xs,
                choice_radius: radius.lg,
                indicator_size: spacing.md + spacing.xxs,
                indicator_mark_size: spacing.xs + spacing.xxs,
                indicator_check_size: spacing.md,
                shortcut_size: spacing.lg + spacing.xxs,
                shortcut_text_size: spacing.sm + spacing.xxs * 0.5,
                shortcut_radius: radius.md,
            },
            Size::Large => Self {
                root_gap: spacing.xl,
                item_gap: spacing.xl,
                choices_gap: spacing.sm + spacing.xxs,
                choice_gap: spacing.md,
                content_gap: spacing.xs,
                choice_padding_x: spacing.lg,
                choice_padding_y: spacing.md,
                choice_min_height: spacing.xxl + spacing.lg,
                choice_radius: radius.xl,
                indicator_size: spacing.lg + spacing.xxs,
                indicator_mark_size: spacing.sm + spacing.xxs,
                indicator_check_size: spacing.lg,
                shortcut_size: spacing.xl,
                shortcut_text_size: spacing.md,
                shortcut_radius: radius.lg,
            },
            Size::Size(value) => Self {
                root_gap: value,
                item_gap: value,
                choices_gap: value * 0.5,
                choice_gap: value * 0.625,
                content_gap: value * 0.125,
                choice_padding_x: value * 0.75,
                choice_padding_y: value * 0.625,
                choice_min_height: value * 2.75,
                choice_radius: radius.lg,
                indicator_size: value,
                indicator_mark_size: value * 0.5,
                indicator_check_size: value * 0.875,
                shortcut_size: value * 1.25,
                shortcut_text_size: value * 0.625,
                shortcut_radius: radius.md,
            },
            Size::Medium => Self {
                root_gap: spacing.lg,
                item_gap: spacing.lg,
                choices_gap: spacing.sm,
                choice_gap: spacing.sm + spacing.xxs,
                content_gap: spacing.xxs,
                choice_padding_x: spacing.md,
                choice_padding_y: spacing.sm + spacing.xxs,
                choice_min_height: spacing.xxl + spacing.md,
                choice_radius: radius.lg,
                indicator_size: spacing.lg,
                indicator_mark_size: spacing.sm,
                indicator_check_size: spacing.md + spacing.xxs,
                shortcut_size: spacing.lg + spacing.xs,
                shortcut_text_size: spacing.sm + spacing.xxs,
                shortcut_radius: radius.md,
            },
        }
    }
}

/// Answer text matches the Checkbox and Radio family's label at each size.
fn text_style<T: Styled>(element: T, size: Size, cx: &App) -> T {
    let typography = cx.theme().semantic_tokens().typography;
    match size {
        Size::XSmall => apply_text_token(element, typography.xs),
        Size::Small => apply_text_token(element, typography.sm),
        Size::Large => apply_text_token(element, typography.lg),
        Size::Size(value) => element.text_size(value),
        Size::Medium => apply_text_token(element, typography.md),
    }
}

/// Secondary text sits one step below the answer text.
fn secondary_text_style<T: Styled>(element: T, size: Size, cx: &App) -> T {
    let typography = cx.theme().semantic_tokens().typography;
    match size {
        Size::XSmall | Size::Small => apply_text_token(element, typography.xs),
        Size::Large => apply_text_token(element, typography.md),
        Size::Size(value) => element.text_size(value * 0.875),
        Size::Medium => apply_text_token(element, typography.sm),
    }
}

fn progress_text_style<T: Styled>(element: T, size: Size, cx: &App) -> T {
    let typography = cx.theme().semantic_tokens().typography;
    match size {
        Size::Large => apply_text_token(element, typography.sm),
        Size::Size(value) => element.text_size(value * 0.75),
        _ => apply_text_token(element, typography.xs),
    }
    .font_weight(gpui::FontWeight::MEDIUM)
}

fn description_text_style<T: Styled>(element: T, size: Size, cx: &App) -> T {
    secondary_text_style(element, size, cx)
}

fn title_text_style<T: Styled>(element: T, size: Size, cx: &App) -> T {
    let typography = cx.theme().semantic_tokens().typography;
    match size {
        Size::XSmall => apply_text_token(element, typography.sm),
        Size::Small => apply_text_token(element, typography.md),
        Size::Large => apply_text_token(element, typography.xl),
        Size::Size(value) => element.text_size(value * 1.125),
        Size::Medium => apply_text_token(element, typography.lg),
    }
    .font_weight(gpui::FontWeight::MEDIUM)
}

/// The line box the answer label occupies. An indicator or a shortcut badge
/// centers on that first line, so a two-line answer keeps them beside the
/// label rather than drifting toward the description.
fn answer_line_height(size: Size, cx: &App) -> gpui::Pixels {
    let typography = cx.theme().semantic_tokens().typography;
    match size {
        Size::XSmall => typography.xs.line_height,
        Size::Small => typography.sm.line_height,
        Size::Large => typography.lg.line_height,
        Size::Size(value) => value * 1.5,
        Size::Medium => typography.md.line_height,
    }
}

/// How far to push an adornment of `height` down so it centers on that line.
fn center_on_answer_line(height: gpui::Pixels, size: Size, cx: &App) -> gpui::Pixels {
    ((answer_line_height(size, cx) - height) * 0.5).max(gpui::Pixels::ZERO)
}

fn apply_text_token<T: Styled>(element: T, token: gpui_base::TextStyleToken) -> T {
    element
        .text_size(token.size)
        .line_height(token.line_height)
        .font_weight(token.weight)
}

fn item_label(
    definition: &gpui_base::questionnaire::QuestionnaireItemDefinition,
) -> Option<SharedString> {
    Some(definition.accessibility_label().clone())
}

fn item_description(
    definition: &gpui_base::questionnaire::QuestionnaireItemDefinition,
) -> Option<SharedString> {
    definition.description().cloned()
}

/// A part addresses its question by name. A name the schema does not define
/// renders nothing, which is silent enough to hide a typo, so a debug build
/// names what went missing. It is a warning rather than an assertion because
/// one view may legitimately render the parts of several questionnaires and
/// hand each a state that defines only some of them.
#[cfg(debug_assertions)]
#[track_caller]
fn report_unknown_item(item: &SharedString) {
    tracing::warn!("questionnaire has no item named `{item}`; the part renders nothing");
}

/// The same for a choice value inside a question that does exist.
#[cfg(debug_assertions)]
#[track_caller]
fn report_unknown_choice(item: &SharedString, value: &SharedString) {
    tracing::warn!(
        "questionnaire item `{item}` has no choice named `{value}`; the part renders nothing"
    );
}

#[cfg(not(debug_assertions))]
fn report_unknown_item(_: &SharedString) {}

#[cfg(not(debug_assertions))]
fn report_unknown_choice(_: &SharedString, _: &SharedString) {}

fn element_id(state: &Entity<QuestionnaireState>, suffix: impl std::fmt::Display) -> ElementId {
    ElementId::Name(format!("questionnaire-{}-{suffix}", state.entity_id()).into())
}

/// The composable questionnaire root. It owns layout and keyboard routing while
/// [`QuestionnaireState`] remains the single source of behavioral state.
#[derive(IntoElement)]
pub struct Questionnaire {
    state: Entity<QuestionnaireState>,
    style: StyleRefinement,
    size: Option<Size>,
    children: Vec<AnyElement>,
}

impl Questionnaire {
    pub fn new(state: &Entity<QuestionnaireState>) -> Self {
        Self {
            state: state.clone(),
            style: StyleRefinement::default(),
            size: None,
            children: Vec::new(),
        }
    }
}

impl Sizable for Questionnaire {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = Some(size.into());
        self
    }
}

impl Styled for Questionnaire {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for Questionnaire {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl RenderOnce for Questionnaire {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        // The root is the one place a caller names the scale, so it records it
        // for the parts before any of them render.
        let size = self.size.unwrap_or(Size::Medium);
        publish_size(&self.state, size, cx);
        let metrics = QuestionnaireMetrics::new(size, cx);
        let focus_handle = self.state.read(cx).focus_handle().clone();
        let state = self.state.clone();
        let debug_selector = format!("questionnaire-{}-root", self.state.entity_id());

        div()
            .id(element_id(&self.state, "root"))
            .debug_selector(move || debug_selector)
            .role(Role::Form)
            .key_context("Questionnaire")
            .track_focus(&focus_handle)
            .capture_key_down(move |event, window, cx| {
                gpui_base::questionnaire::handle_key_down(&state, event, window, cx)
            })
            .flex()
            .flex_col()
            .min_w_0()
            .gap(metrics.root_gap)
            .w_full()
            .refine_style(&self.style)
            .children(self.children)
    }
}

/// Textual progress, following the ReUI `base-nova` questionnaire skin.
#[derive(IntoElement)]
pub struct QuestionnaireProgress {
    state: Entity<QuestionnaireState>,
    style: StyleRefinement,
    size: Option<Size>,
    children: Vec<AnyElement>,
}

impl QuestionnaireProgress {
    pub fn new(state: &Entity<QuestionnaireState>) -> Self {
        Self {
            state: state.clone(),
            style: StyleRefinement::default(),
            size: None,
            children: Vec::new(),
        }
    }
}

impl Sizable for QuestionnaireProgress {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = Some(size.into());
        self
    }
}

impl Styled for QuestionnaireProgress {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for QuestionnaireProgress {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl RenderOnce for QuestionnaireProgress {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let progress = self.state.read(cx).progress();
        let current = progress.current();
        let total = progress.total();
        let label: SharedString =
            t!("Questionnaire.progress", current = current, total = total).into();
        let colors = cx.theme().semantic_tokens().colors;
        let has_children = !self.children.is_empty();

        let size = resolve_size(self.size, &self.state, cx);
        progress_text_style(
            div()
                .id(element_id(&self.state, "progress"))
                .role(Role::ProgressIndicator)
                .aria_label(label.clone())
                .aria_min_numeric_value(0.)
                .aria_max_numeric_value(total as f64)
                .aria_numeric_value(current as f64)
                .text_color(colors.muted_foreground),
            size,
            cx,
        )
        .refine_style(&self.style)
        .when(!has_children, |this| this.child(label))
        .children(self.children)
    }
}

macro_rules! questionnaire_item_part {
    ($name:ident, $fallback:ident, $style:ident, $color:ident, $closes_item_gap:expr) => {
        #[derive(IntoElement)]
        pub struct $name {
            state: Entity<QuestionnaireState>,
            item: SharedString,
            style: StyleRefinement,
            size: Option<Size>,
            children: Vec<AnyElement>,
        }

        impl $name {
            pub fn new(state: &Entity<QuestionnaireState>, item: impl Into<SharedString>) -> Self {
                Self {
                    state: state.clone(),
                    item: item.into(),
                    style: StyleRefinement::default(),
                    size: None,
                    children: Vec::new(),
                }
            }
        }

        impl Sizable for $name {
            fn with_size(mut self, size: impl Into<Size>) -> Self {
                self.size = Some(size.into());
                self
            }
        }

        impl Styled for $name {
            fn style(&mut self) -> &mut StyleRefinement {
                &mut self.style
            }
        }

        impl ParentElement for $name {
            fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
                self.children.extend(elements);
            }
        }

        impl RenderOnce for $name {
            fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
                let Some(definition) = self.state.read(cx).item_definition(&self.item) else {
                    report_unknown_item(&self.item);
                    return gpui::Empty.into_any_element();
                };
                let fallback = $fallback(definition);
                let has_children = !self.children.is_empty();
                if !has_children && fallback.is_none() {
                    return gpui::Empty.into_any_element();
                }
                let colors = cx.theme().semantic_tokens().colors;
                // The item stacks its parts on one gap. A title with no
                // description of its own closes the gap the description would
                // have filled, so answers never crowd the question.
                let closes_item_gap = $closes_item_gap && item_description(definition).is_none();
                let size = resolve_size(self.size, &self.state, cx);
                $style(div().w_full().text_color(colors.$color), size, cx)
                    .when(closes_item_gap, |this| {
                        this.mb(QuestionnaireMetrics::new(size, cx).item_gap)
                    })
                    .refine_style(&self.style)
                    .when(!has_children, |this| {
                        this.when_some(fallback, |this, fallback| this.child(fallback))
                    })
                    .children(self.children)
                    .into_any_element()
            }
        }
    };
}

questionnaire_item_part!(
    QuestionnaireTitle,
    item_label,
    title_text_style,
    foreground,
    true
);
questionnaire_item_part!(
    QuestionnaireDescription,
    item_description,
    description_text_style,
    muted_foreground,
    false
);

/// The active question group. Inactive or disabled items do not enter layout,
/// focus traversal, or the accessibility tree.
#[derive(IntoElement)]
pub struct QuestionnaireItem {
    state: Entity<QuestionnaireState>,
    item: SharedString,
    style: StyleRefinement,
    size: Option<Size>,
    children: Vec<AnyElement>,
}

impl QuestionnaireItem {
    pub fn new(state: &Entity<QuestionnaireState>, item: impl Into<SharedString>) -> Self {
        Self {
            state: state.clone(),
            item: item.into(),
            style: StyleRefinement::default(),
            size: None,
            children: Vec::new(),
        }
    }
}

impl Sizable for QuestionnaireItem {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = Some(size.into());
        self
    }
}

impl Styled for QuestionnaireItem {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for QuestionnaireItem {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl RenderOnce for QuestionnaireItem {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let state = self.state.read(cx);
        let active = state.current_item().is_some_and(|name| name == &self.item);
        let Some(item_state) = state.item_state(&self.item) else {
            report_unknown_item(&self.item);
            return gpui::Empty.into_any_element();
        };
        if !active || item_state.is_disabled() {
            return gpui::Empty.into_any_element();
        }
        let Some(definition) = state.item_definition(&self.item) else {
            return gpui::Empty.into_any_element();
        };
        let focus_handle = state.item_focus_handle(&self.item).cloned();
        let label = definition.accessibility_label().clone();
        let description = definition.description().cloned();
        let metrics = QuestionnaireMetrics::new(resolve_size(self.size, &self.state, cx), cx);

        div()
            .id(element_id(&self.state, format!("item-{}", self.item)))
            .role(Role::Group)
            .aria_label(label)
            .when_some(description, |this, description| {
                this.aria_description(description)
            })
            .when_some(focus_handle, |this, focus_handle| {
                this.track_focus(&focus_handle.tab_index(-1).tab_stop(false))
            })
            .flex()
            .flex_col()
            .gap(metrics.item_gap)
            .w_full()
            .refine_style(&self.style)
            .children(self.children)
            .into_any_element()
    }
}

/// Container for an item's answer controls.
#[derive(IntoElement)]
pub struct QuestionnaireChoices {
    state: Entity<QuestionnaireState>,
    item: SharedString,
    style: StyleRefinement,
    size: Option<Size>,
    children: Vec<AnyElement>,
}

impl QuestionnaireChoices {
    pub fn new(state: &Entity<QuestionnaireState>, item: impl Into<SharedString>) -> Self {
        Self {
            state: state.clone(),
            item: item.into(),
            style: StyleRefinement::default(),
            size: None,
            children: Vec::new(),
        }
    }
}

impl Sizable for QuestionnaireChoices {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = Some(size.into());
        self
    }
}

impl Styled for QuestionnaireChoices {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for QuestionnaireChoices {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl RenderOnce for QuestionnaireChoices {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let state = self.state.read(cx);
        let active = state.current_item().is_some_and(|name| name == &self.item);
        let Some(item) = state.item_state(&self.item) else {
            report_unknown_item(&self.item);
            return gpui::Empty.into_any_element();
        };
        if !active || item.is_disabled() {
            return gpui::Empty.into_any_element();
        }
        let metrics = QuestionnaireMetrics::new(resolve_size(self.size, &self.state, cx), cx);

        if item.is_multiple() {
            div()
                .id(element_id(&self.state, format!("choices-{}", self.item)))
                .role(Role::Group)
                .flex()
                .flex_col()
                .gap(metrics.choices_gap)
                .w_full()
                .refine_style(&self.style)
                .children(self.children)
                .into_any_element()
        } else {
            RadioGroup::new(element_id(&self.state, format!("choices-{}", self.item)))
                .flex()
                .flex_col()
                .gap(metrics.choices_gap)
                .w_full()
                .refine_style(&self.style)
                .children(self.children)
                .into_any_element()
        }
    }
}

/// A selectable choice card, following the ReUI `base-nova` questionnaire skin.
#[derive(IntoElement)]
pub struct QuestionnaireChoice {
    state: Entity<QuestionnaireState>,
    item: SharedString,
    value: SharedString,
    style: StyleRefinement,
    indicator_style: StyleRefinement,
    content_style: StyleRefinement,
    shortcut_style: StyleRefinement,
    size: Option<Size>,
    children: Vec<AnyElement>,
    indicator_renderer: Option<ChoiceRenderer>,
    shortcut_renderer: Option<ChoiceRenderer>,
}

impl QuestionnaireChoice {
    pub fn new(
        state: &Entity<QuestionnaireState>,
        item: impl Into<SharedString>,
        value: impl Into<SharedString>,
    ) -> Self {
        Self {
            state: state.clone(),
            item: item.into(),
            value: value.into(),
            style: StyleRefinement::default(),
            indicator_style: StyleRefinement::default(),
            content_style: StyleRefinement::default(),
            shortcut_style: StyleRefinement::default(),
            size: None,
            children: Vec::new(),
            indicator_renderer: None,
            shortcut_renderer: None,
        }
    }

    pub fn indicator_style(mut self, style: StyleRefinement) -> Self {
        self.indicator_style = style;
        self
    }

    pub fn content_style(mut self, style: StyleRefinement) -> Self {
        self.content_style = style;
        self
    }

    pub fn shortcut_style(mut self, style: StyleRefinement) -> Self {
        self.shortcut_style = style;
        self
    }

    pub fn render_indicator(
        mut self,
        renderer: impl Fn(&QuestionnaireChoiceState, &mut Window, &mut App) -> AnyElement + 'static,
    ) -> Self {
        self.indicator_renderer = Some(Rc::new(renderer));
        self
    }

    pub fn render_shortcut(
        mut self,
        renderer: impl Fn(&QuestionnaireChoiceState, &mut Window, &mut App) -> AnyElement + 'static,
    ) -> Self {
        self.shortcut_renderer = Some(Rc::new(renderer));
        self
    }
}

impl Sizable for QuestionnaireChoice {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = Some(size.into());
        self
    }
}

impl Styled for QuestionnaireChoice {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for QuestionnaireChoice {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

#[allow(clippy::too_many_arguments)]
fn style_choice_card<T>(
    base: T,
    indicator: AnyElement,
    content: AnyElement,
    shortcut: AnyElement,
    metrics: QuestionnaireMetrics,
    selected: bool,
    disabled: bool,
    invalid: bool,
    focused: bool,
    instance_style: &StyleRefinement,
    window: &Window,
    cx: &App,
) -> T
where
    T: Styled + ParentElement + StatefulInteractiveElement + gpui::prelude::FluentBuilder,
{
    let tokens = cx.theme().semantic_tokens();
    base.flex()
        .items_start()
        .gap(metrics.choice_gap)
        .w_full()
        .min_h(metrics.choice_min_height)
        .px(metrics.choice_padding_x)
        .py(metrics.choice_padding_y)
        .border_1()
        .border_color(if invalid {
            tokens.colors.destructive
        } else if selected {
            tokens.colors.primary.opacity(0.4)
        } else {
            tokens.colors.input
        })
        .bg(if selected {
            tokens.colors.muted
        } else if cx.theme().is_dark() {
            tokens.colors.input.opacity(0.2)
        } else {
            tokens.colors.background.opacity(0.)
        })
        .rounded(metrics.choice_radius)
        .when(!disabled, |this| {
            this.hover(|style| style.bg(tokens.colors.muted.opacity(0.5)))
        })
        .when(focused, |this| this.focus_ring_style(window, cx))
        .when(disabled, |this| this.opacity(0.5))
        .refine_style(instance_style)
        .child(indicator)
        .child(content)
        .child(shortcut)
}

impl RenderOnce for QuestionnaireChoice {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let state = self.state.read(cx);
        let active = state.current_item().is_some_and(|name| name == &self.item);
        let Some(choice_state) = state.choice_state(&self.item, &self.value) else {
            if state.item_state(&self.item).is_none() {
                report_unknown_item(&self.item);
            } else {
                report_unknown_choice(&self.item, &self.value);
            }
            return gpui::Empty.into_any_element();
        };
        if !active {
            return gpui::Empty.into_any_element();
        }
        let Some(item) = state.item_state(&self.item) else {
            report_unknown_item(&self.item);
            return gpui::Empty.into_any_element();
        };
        let Some(definition) = state.choice_definition(&self.item, &self.value) else {
            return gpui::Empty.into_any_element();
        };
        let multiple = item.is_multiple();
        let label = definition.accessibility_label().clone();
        let description = definition.description().cloned();
        let selected = choice_state.is_selected();
        let disabled = choice_state.is_disabled();
        let invalid = choice_state.is_invalid();
        let shortcut = choice_state.shortcut().cloned();
        let focus_handle = state.choice_focus_handle(&self.item, &self.value).cloned();
        let colors = cx.theme().semantic_tokens().colors;
        let radius = cx.theme().semantic_tokens().radius;
        let indicator_background = cx.theme().input_background();
        let mono_font = cx.theme().semantic_tokens().typography.mono.clone();
        let size = resolve_size(self.size, &self.state, cx);
        let metrics = QuestionnaireMetrics::new(size, cx);
        let indicator_offset = center_on_answer_line(metrics.indicator_size, size, cx);
        let shortcut_offset = center_on_answer_line(metrics.shortcut_size, size, cx);
        let focused = focus_handle
            .as_ref()
            .is_some_and(|focus_handle| focus_handle.is_focused(window));
        let has_children = !self.children.is_empty();
        let check_path = crate::resolve_icon_path(IconName::Check.path(), cx);

        let default_indicator = || {
            div()
                .relative()
                .flex()
                .items_center()
                .justify_center()
                .flex_shrink_0()
                .size(metrics.indicator_size)
                .border_1()
                .border_color(if selected {
                    colors.primary
                } else {
                    colors.input
                })
                .bg(if selected {
                    colors.primary
                } else {
                    indicator_background
                })
                .when(multiple, |this| this.rounded(radius.sm))
                .when(!multiple, |this| this.rounded(radius.full))
                .refine_style(&self.indicator_style)
                .when(selected && multiple, |this| {
                    this.child(
                        svg()
                            .size(metrics.indicator_check_size)
                            .path(check_path.clone())
                            .text_color(colors.primary_foreground),
                    )
                })
                .when(selected && !multiple, |this| {
                    this.child(
                        div()
                            .size(metrics.indicator_mark_size)
                            .rounded(radius.full)
                            .bg(colors.primary_foreground),
                    )
                })
                .into_any_element()
        };

        // The slot, not the element, owns the vertical alignment, so a custom
        // indicator lands on the label's line without having to know the metrics.
        let indicator = div()
            .flex_shrink_0()
            .mt(indicator_offset)
            .child(
                self.indicator_renderer
                    .as_ref()
                    .map(|renderer| renderer(&choice_state, window, cx))
                    .unwrap_or_else(default_indicator),
            )
            .into_any_element();

        let content = div()
            .flex()
            .flex_1()
            .flex_col()
            .gap(metrics.content_gap)
            .refine_style(&self.content_style)
            .when(!has_children, |this| {
                this.child(text_style(
                    div().text_color(colors.foreground).child(label.clone()),
                    size,
                    cx,
                ))
                .when_some(description.clone(), |this, description| {
                    this.child(secondary_text_style(
                        div().text_color(colors.muted_foreground).child(description),
                        size,
                        cx,
                    ))
                })
            })
            .children(self.children);

        let os = cx.platform_info().os;
        let default_shortcut = || {
            let Some(shortcut) = shortcut.clone() else {
                return gpui::Empty.into_any_element();
            };
            let Ok(keystroke) = gpui::Keystroke::parse_with_os(&shortcut.to_lowercase(), os) else {
                return gpui::Empty.into_any_element();
            };
            Kbd::new(keystroke)
                .outline()
                .flex()
                .items_center()
                .justify_center()
                .size(metrics.shortcut_size)
                .p_0()
                .bg(colors.background)
                .border_color(colors.input)
                .text_color(colors.muted_foreground)
                .font_family(mono_font.clone())
                .text_size(metrics.shortcut_text_size)
                .font_weight(gpui::FontWeight::MEDIUM)
                .rounded(metrics.shortcut_radius)
                .refine_style(&self.shortcut_style)
                .into_any_element()
        };
        let shortcut_element = div()
            .flex_shrink_0()
            .mt(shortcut_offset)
            .child(
                self.shortcut_renderer
                    .as_ref()
                    .map(|renderer| renderer(&choice_state, window, cx))
                    .unwrap_or_else(default_shortcut),
            )
            .into_any_element();

        let id = element_id(&self.state, format!("choice-{}-{}", self.item, self.value));
        let instance_style = self.style.clone();
        let item_name = self.item.clone();
        let choice_value = self.value.clone();

        let Some(control) =
            QuestionnaireChoiceControl::new(&self.state, item_name, choice_value, id, cx)
        else {
            return gpui::Empty.into_any_element();
        };
        match control {
            QuestionnaireChoiceControl::Checkbox(base) => style_choice_card(
                base,
                indicator,
                content.into_any_element(),
                shortcut_element,
                metrics,
                selected,
                disabled,
                invalid,
                focused,
                &instance_style,
                window,
                cx,
            )
            .into_any_element(),
            QuestionnaireChoiceControl::Radio(base) => style_choice_card(
                base,
                indicator,
                content.into_any_element(),
                shortcut_element,
                metrics,
                selected,
                disabled,
                invalid,
                focused,
                &instance_style,
                window,
                cx,
            )
            .into_any_element(),
        }
    }
}

/// Secondary text for custom choice compositions.
#[derive(IntoElement)]
pub struct QuestionnaireChoiceDescription {
    style: StyleRefinement,
    size: Option<Size>,
    children: Vec<AnyElement>,
}

impl QuestionnaireChoiceDescription {
    pub fn new() -> Self {
        Self {
            style: StyleRefinement::default(),
            size: None,
            children: Vec::new(),
        }
    }
}

impl Default for QuestionnaireChoiceDescription {
    fn default() -> Self {
        Self::new()
    }
}

impl Sizable for QuestionnaireChoiceDescription {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = Some(size.into());
        self
    }
}

impl Styled for QuestionnaireChoiceDescription {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for QuestionnaireChoiceDescription {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl RenderOnce for QuestionnaireChoiceDescription {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let colors = cx.theme().semantic_tokens().colors;
        secondary_text_style(
            div().text_color(colors.muted_foreground),
            self.size.unwrap_or(Size::Medium),
            cx,
        )
        .refine_style(&self.style)
        .children(self.children)
    }
}

/// The optional freeform answer input for an item.
#[derive(IntoElement)]
pub struct QuestionnaireInput {
    state: Entity<QuestionnaireState>,
    item: SharedString,
    style: StyleRefinement,
    size: Option<Size>,
}

impl QuestionnaireInput {
    pub fn new(state: &Entity<QuestionnaireState>, item: impl Into<SharedString>) -> Self {
        Self {
            state: state.clone(),
            item: item.into(),
            style: StyleRefinement::default(),
            size: None,
        }
    }
}

impl Sizable for QuestionnaireInput {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = Some(size.into());
        self
    }
}

impl Styled for QuestionnaireInput {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for QuestionnaireInput {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let state = self.state.read(cx);
        let active = state.current_item().is_some_and(|name| name == &self.item);
        let Some(item_state) = state.item_state(&self.item) else {
            report_unknown_item(&self.item);
            return gpui::Empty.into_any_element();
        };
        let Some(definition) = state.item_definition(&self.item) else {
            return gpui::Empty.into_any_element();
        };
        let Some(input_definition) = definition.input() else {
            return gpui::Empty.into_any_element();
        };
        if !active {
            return gpui::Empty.into_any_element();
        }

        let size = resolve_size(self.size, &self.state, cx);
        let metrics = QuestionnaireMetrics::new(size, cx);

        Input::new(input_definition.state())
            .aria_label(input_definition.accessibility_label().clone())
            .disabled(item_state.is_disabled() || input_definition.is_disabled())
            .with_size(size)
            // The freeform answer is one of the answers, so its text starts on
            // the same edge a choice's indicator does — the card padding.
            .pl(metrics.choice_padding_x)
            .rounded(metrics.choice_radius)
            .when(item_state.is_invalid(), |this| {
                this.border_color(cx.theme().semantic_tokens().colors.destructive)
            })
            .refine_style(&self.style)
            .into_any_element()
    }
}

/// Validation error for an item. It only enters the tree while invalid.
#[derive(IntoElement)]
pub struct QuestionnaireError {
    state: Entity<QuestionnaireState>,
    item: SharedString,
    style: StyleRefinement,
    size: Option<Size>,
    children: Vec<AnyElement>,
}

impl QuestionnaireError {
    pub fn new(state: &Entity<QuestionnaireState>, item: impl Into<SharedString>) -> Self {
        Self {
            state: state.clone(),
            item: item.into(),
            style: StyleRefinement::default(),
            size: None,
            children: Vec::new(),
        }
    }
}

impl Sizable for QuestionnaireError {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = Some(size.into());
        self
    }
}

impl Styled for QuestionnaireError {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for QuestionnaireError {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

fn questionnaire_error_root(id: ElementId) -> gpui::Stateful<gpui::Div> {
    div().id(id).role(Role::Alert)
}

/// Base reports why an item failed; the skin owns the sentence a person reads.
fn error_text(error: &QuestionnaireValidationError) -> SharedString {
    match error {
        QuestionnaireValidationError::Required => t!("Questionnaire.error.required").into(),
        QuestionnaireValidationError::Unanswered => t!("Questionnaire.error.optional").into(),
        QuestionnaireValidationError::Message(message) => message.clone(),
        _ => SharedString::default(),
    }
}

impl RenderOnce for QuestionnaireError {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let state = self.state.read(cx);
        let Some(item) = state.item_state(&self.item) else {
            report_unknown_item(&self.item);
            return gpui::Empty.into_any_element();
        };
        let error = state.error(&self.item).cloned();
        if !item.is_invalid() || error.is_none() {
            return gpui::Empty.into_any_element();
        }
        let has_children = !self.children.is_empty();
        let colors = cx.theme().semantic_tokens().colors;
        let spacing = cx.theme().semantic_tokens().spacing;
        let size = resolve_size(self.size, &self.state, cx);

        secondary_text_style(
            questionnaire_error_root(element_id(&self.state, format!("error-{}", self.item)))
                .mt(spacing.sm)
                .text_color(colors.destructive),
            size,
            cx,
        )
        .refine_style(&self.style)
        .when(!has_children, |this| {
            this.when_some(error, |this, error| this.child(error_text(&error)))
        })
        .children(self.children)
        .into_any_element()
    }
}

/// Layout part for questionnaire navigation actions.
#[derive(IntoElement)]
pub struct QuestionnaireActions {
    state: Entity<QuestionnaireState>,
    style: StyleRefinement,
    size: Option<Size>,
    children: Vec<AnyElement>,
}

impl QuestionnaireActions {
    pub fn new(state: &Entity<QuestionnaireState>) -> Self {
        Self {
            state: state.clone(),
            style: StyleRefinement::default(),
            size: None,
            children: Vec::new(),
        }
    }
}

impl Sizable for QuestionnaireActions {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = Some(size.into());
        self
    }
}

impl Styled for QuestionnaireActions {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for QuestionnaireActions {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl RenderOnce for QuestionnaireActions {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let metrics = QuestionnaireMetrics::new(resolve_size(self.size, &self.state, cx), cx);
        let debug_selector = format!("questionnaire-{}-actions", self.state.entity_id());
        div()
            .id(element_id(&self.state, "actions"))
            .debug_selector(move || debug_selector)
            .flex()
            .min_w_0()
            .items_center()
            .justify_start()
            .gap(metrics.choices_gap)
            .w_full()
            .refine_style(&self.style)
            .children(self.children)
    }
}

#[derive(Clone, Copy)]
enum QuestionnaireAction {
    Previous,
    Skip,
    Next,
    Submit,
}

macro_rules! questionnaire_action_part {
    ($name:ident, $action:ident, $translation:literal, $outline:expr, $primary:expr) => {
        #[derive(IntoElement)]
        pub struct $name {
            state: Entity<QuestionnaireState>,
            style: StyleRefinement,
            size: Option<Size>,
            children: Vec<AnyElement>,
        }

        impl $name {
            pub fn new(state: &Entity<QuestionnaireState>) -> Self {
                Self {
                    state: state.clone(),
                    style: StyleRefinement::default(),
                    size: None,
                    children: Vec::new(),
                }
            }
        }

        impl Styled for $name {
            fn style(&mut self) -> &mut StyleRefinement {
                &mut self.style
            }
        }

        impl Sizable for $name {
            fn with_size(mut self, size: impl Into<Size>) -> Self {
                self.size = Some(size.into());
                self
            }
        }

        impl ParentElement for $name {
            fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
                self.children.extend(elements);
            }
        }

        impl RenderOnce for $name {
            fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
                let navigation = self.state.read(cx).navigation_state();
                let action = QuestionnaireAction::$action;
                let visible = match action {
                    QuestionnaireAction::Previous => navigation.is_previous_visible(),
                    QuestionnaireAction::Skip => navigation.is_skip_visible(),
                    QuestionnaireAction::Next => navigation.is_next_visible(),
                    QuestionnaireAction::Submit => navigation.is_submit_visible(),
                };
                if !visible {
                    return gpui::Empty.into_any_element();
                }

                let anchors_trailing_actions = match action {
                    QuestionnaireAction::Skip => true,
                    QuestionnaireAction::Next | QuestionnaireAction::Submit => {
                        !navigation.is_skip_visible()
                    }
                    QuestionnaireAction::Previous => false,
                };
                let state = self.state.clone();
                let has_children = !self.children.is_empty();
                let debug_selector = format!(
                    "questionnaire-{}-{}",
                    self.state.entity_id(),
                    stringify!($action)
                );
                Button::new(element_id(&self.state, stringify!($action)))
                    .debug_selector(move || debug_selector)
                    .with_size(resolve_size(self.size, &self.state, cx))
                    .when($outline, |this| this.outline())
                    .when($primary, |this| this.primary())
                    .when(anchors_trailing_actions, |this| this.ml_auto())
                    .on_click(move |_, window, cx| {
                        state.update(cx, |state, cx| match action {
                            QuestionnaireAction::Previous => state.go_previous(window, cx),
                            QuestionnaireAction::Skip => state.skip_current(window, cx),
                            QuestionnaireAction::Next => state.go_next(window, cx),
                            QuestionnaireAction::Submit => state.submit(window, cx),
                        });
                    })
                    .refine_style(&self.style)
                    .when(!has_children, |this| this.label(t!($translation)))
                    .children(self.children)
                    .into_any_element()
            }
        }
    };
}

questionnaire_action_part!(
    QuestionnairePrevious,
    Previous,
    "Questionnaire.previous",
    true,
    false
);
questionnaire_action_part!(QuestionnaireSkip, Skip, "Questionnaire.skip", true, false);
questionnaire_action_part!(QuestionnaireNext, Next, "Questionnaire.next", false, true);
questionnaire_action_part!(
    QuestionnaireSubmit,
    Submit,
    "Questionnaire.submit",
    false,
    true
);

#[cfg(test)]
mod tests {
    use super::*;
    use gpui::{
        AppContext as _, Context, Element as _, Focusable as _, KeyDownEvent, Keystroke, Render,
        TestAppContext, VisualTestContext, accesskit, px,
    };

    use gpui_base::questionnaire::{
        QuestionnaireChoiceDefinition, QuestionnaireEvent, QuestionnaireInputDefinition,
        QuestionnaireItemDefinition, QuestionnaireShortcutMode,
    };

    #[test]
    fn compound_parts_support_builder_customization() {
        let _ = QuestionnaireChoiceDescription::new()
            .opacity(0.8)
            .child("Description");
    }

    struct QuestionnaireHarness {
        state: Entity<QuestionnaireState>,
        override_skip_margin: bool,
    }

    impl Render for QuestionnaireHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            Questionnaire::new(&self.state)
                .size(px(480.))
                .child(
                    QuestionnaireItem::new(&self.state, "choice")
                        .child(
                            QuestionnaireChoices::new(&self.state, "choice")
                                .child(QuestionnaireChoice::new(&self.state, "choice", "alpha")),
                        )
                        .child(QuestionnaireInput::new(&self.state, "choice")),
                )
                .child(
                    QuestionnaireItem::new(&self.state, "first")
                        .child(
                            QuestionnaireChoices::new(&self.state, "first")
                                .child(QuestionnaireChoice::new(&self.state, "first", "alpha"))
                                .child(QuestionnaireChoice::new(&self.state, "first", "beta")),
                        )
                        .child(QuestionnaireInput::new(&self.state, "first")),
                )
                .child(
                    QuestionnaireItem::new(&self.state, "second")
                        .child(QuestionnaireInput::new(&self.state, "second")),
                )
                .child(
                    QuestionnaireActions::new(&self.state)
                        .child(QuestionnairePrevious::new(&self.state))
                        .child(
                            QuestionnaireSkip::new(&self.state)
                                .when(self.override_skip_margin, |this| this.ml(px(0.))),
                        )
                        .child(QuestionnaireNext::new(&self.state))
                        .child(QuestionnaireSubmit::new(&self.state)),
                )
        }
    }

    fn visual_harness(
        cx: &mut TestAppContext,
        items: Vec<QuestionnaireItemDefinition>,
        shortcuts: Option<QuestionnaireShortcutMode>,
    ) -> (&mut VisualTestContext, Entity<QuestionnaireState>) {
        cx.update(crate::init);
        let (view, cx) = cx.add_window_view(move |_, cx| {
            let state = cx.new(|cx| {
                let state = QuestionnaireState::new(items, cx).unwrap();
                match shortcuts {
                    Some(shortcuts) => state.with_shortcuts(shortcuts),
                    None => state,
                }
            });
            QuestionnaireHarness {
                state,
                override_skip_margin: false,
            }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let state = cx.update(|_, cx| view.read(cx).state.clone());
        cx.update(|window, cx| {
            let focus_handle = state.read(cx).focus_handle().clone();
            focus_handle.focus(window, cx);
        });
        (cx, state)
    }

    fn input_visual_harness(
        cx: &mut TestAppContext,
        multiple: bool,
    ) -> (&mut VisualTestContext, Entity<QuestionnaireState>) {
        cx.update(crate::init);
        let (view, cx) = cx.add_window_view(move |window, cx| {
            let input = cx.new(|cx| crate::input::InputState::new(window, cx));
            let state = cx.new(|cx| {
                QuestionnaireState::new(
                    vec![
                        QuestionnaireItemDefinition::new("first", "First")
                            .with_required(true)
                            .with_multiple(multiple)
                            .with_choices([
                                QuestionnaireChoiceDefinition::new("alpha", "Alpha"),
                                QuestionnaireChoiceDefinition::new("beta", "Beta"),
                            ])
                            .with_input(QuestionnaireInputDefinition::new(input, "Other")),
                        QuestionnaireItemDefinition::new("second", "Second"),
                    ],
                    cx,
                )
                .unwrap()
            });
            QuestionnaireHarness {
                state,
                override_skip_margin: false,
            }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let state = cx.update(|_, cx| view.read(cx).state.clone());
        (cx, state)
    }

    fn actions_visual_harness(
        cx: &mut TestAppContext,
        override_skip_margin: bool,
    ) -> (&mut VisualTestContext, Entity<QuestionnaireState>) {
        cx.update(crate::init);
        let (view, cx) = cx.add_window_view(|_, cx| {
            let state = cx.new(|cx| {
                QuestionnaireState::new(
                    vec![
                        QuestionnaireItemDefinition::new("first", "First").with_required(true),
                        QuestionnaireItemDefinition::new("second", "Second"),
                        QuestionnaireItemDefinition::new("third", "Third").with_required(true),
                    ],
                    cx,
                )
                .unwrap()
                .with_current_item("second")
                .unwrap()
            });
            QuestionnaireHarness {
                state,
                override_skip_margin,
            }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let state = cx.update(|_, cx| view.read(cx).state.clone());
        (cx, state)
    }

    fn focus_input(cx: &mut VisualTestContext, state: &Entity<QuestionnaireState>, item: &str) {
        cx.update(|window, cx| {
            let input = state.read(cx).input_state(item).unwrap();
            let focus_handle = input.read(cx).focus_handle(cx);
            focus_handle.focus(window, cx);
        });
    }

    fn simulate_key(cx: &mut VisualTestContext, key: &str, is_held: bool, simulate_ime: bool) {
        let os = cx.update(|_, cx| cx.platform_info().os);
        let mut keystroke = Keystroke::parse_with_os(key, os).unwrap();
        if simulate_ime {
            keystroke = keystroke.with_simulated_ime();
        }
        cx.simulate_event(KeyDownEvent {
            keystroke,
            is_held,
            prefer_character_input: false,
        });
    }

    #[gpui::test]
    fn progress_projects_numeric_accessibility(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let window = cx.add_empty_window();
        window.update(|window, cx| {
            let state = cx.new(|cx| {
                QuestionnaireState::new(
                    vec![
                        QuestionnaireItemDefinition::new("first", "First"),
                        QuestionnaireItemDefinition::new("second", "Second"),
                    ],
                    cx,
                )
                .unwrap()
            });
            let mut node = accesskit::Node::new(Role::ProgressIndicator);
            QuestionnaireProgress::new(&state)
                .render(window, cx)
                .into_element()
                .write_a11y_info(&mut node);

            assert_eq!(node.numeric_value(), Some(1.));
            assert_eq!(node.min_numeric_value(), Some(0.));
            assert_eq!(node.max_numeric_value(), Some(2.));

            let root = Questionnaire::new(&state).render(window, cx).into_element();
            assert_eq!(root.a11y_role(), Some(Role::Form));
        });
    }

    #[gpui::test]
    fn actions_stay_inside_questionnaire_width(cx: &mut TestAppContext) {
        let (cx, state) = actions_visual_harness(cx, false);
        let entity_id = state.entity_id();
        let root_id = Box::leak(format!("questionnaire-{entity_id}-root").into_boxed_str());
        let actions_id = Box::leak(format!("questionnaire-{entity_id}-actions").into_boxed_str());
        let previous_id = Box::leak(format!("questionnaire-{entity_id}-Previous").into_boxed_str());
        let skip_id = Box::leak(format!("questionnaire-{entity_id}-Skip").into_boxed_str());
        let next_id = Box::leak(format!("questionnaire-{entity_id}-Next").into_boxed_str());
        let submit_id = Box::leak(format!("questionnaire-{entity_id}-Submit").into_boxed_str());
        let root = cx.debug_bounds(root_id).expect("questionnaire rendered");
        let actions = cx.debug_bounds(actions_id).expect("actions rendered");
        let previous = cx.debug_bounds(previous_id).expect("previous rendered");
        let skip = cx.debug_bounds(skip_id).expect("skip rendered");
        let next = cx.debug_bounds(next_id).expect("next rendered");

        assert!(actions.left() >= root.left());
        assert!(actions.right() <= root.right());
        assert_eq!(previous.left(), actions.left());
        assert!(previous.right() <= skip.left());
        assert!(skip.right() <= next.left());
        assert_eq!(next.right(), actions.right());

        cx.update(|window, cx| {
            state
                .update(cx, |state, cx| state.set_current_item("first", window, cx))
                .unwrap();
            window.draw(cx).clear(cx);
        });
        let first_actions = cx.debug_bounds(actions_id).expect("first actions rendered");
        let first_next = cx.debug_bounds(next_id).expect("first next rendered");
        assert!(first_next.left() >= first_actions.left());
        assert_eq!(first_next.right(), first_actions.right());

        cx.update(|window, cx| {
            state
                .update(cx, |state, cx| state.set_current_item("third", window, cx))
                .unwrap();
            window.draw(cx).clear(cx);
        });
        let last_actions = cx.debug_bounds(actions_id).expect("last actions rendered");
        let last_previous = cx
            .debug_bounds(previous_id)
            .expect("last previous rendered");
        let submit = cx.debug_bounds(submit_id).expect("submit rendered");
        assert_eq!(last_previous.left(), last_actions.left());
        assert!(last_previous.right() <= submit.left());
        assert_eq!(submit.right(), last_actions.right());
    }

    #[gpui::test]
    fn action_instance_style_overrides_default_trailing_anchor(cx: &mut TestAppContext) {
        let (cx, state) = actions_visual_harness(cx, true);
        let entity_id = state.entity_id();
        let actions_id = Box::leak(format!("questionnaire-{entity_id}-actions").into_boxed_str());
        let previous_id = Box::leak(format!("questionnaire-{entity_id}-Previous").into_boxed_str());
        let skip_id = Box::leak(format!("questionnaire-{entity_id}-Skip").into_boxed_str());
        let next_id = Box::leak(format!("questionnaire-{entity_id}-Next").into_boxed_str());
        let actions = cx.debug_bounds(actions_id).expect("actions rendered");
        let previous = cx.debug_bounds(previous_id).expect("previous rendered");
        let skip = cx.debug_bounds(skip_id).expect("skip rendered");
        let next = cx.debug_bounds(next_id).expect("next rendered");

        assert_eq!(previous.left(), actions.left());
        assert!(previous.right() <= skip.left());
        assert!(skip.right() <= next.left());
        assert!(next.right() < actions.right());
    }

    struct ScaleHarness {
        state: Entity<QuestionnaireState>,
        root_size: Size,
        part_size: Option<Size>,
    }

    impl Render for ScaleHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let part_size = self.part_size;
            Questionnaire::new(&self.state)
                .with_size(self.root_size)
                .size(px(480.))
                .child(
                    QuestionnaireItem::new(&self.state, "scale")
                        .when_some(part_size, |this, size| this.with_size(size))
                        .child(
                            QuestionnaireChoices::new(&self.state, "scale")
                                .when_some(part_size, |this, size| this.with_size(size))
                                .child(
                                    div()
                                        .id("scale-choice")
                                        .debug_selector(|| "scale-choice".to_string())
                                        .child(
                                            QuestionnaireChoice::new(&self.state, "scale", "alpha")
                                                .when_some(part_size, |this, size| {
                                                    this.with_size(size)
                                                }),
                                        ),
                                ),
                        ),
                )
        }
    }

    fn scale_harness(
        cx: &mut TestAppContext,
        root_size: Size,
        part_size: Option<Size>,
    ) -> gpui::Bounds<gpui::Pixels> {
        cx.update(crate::init);
        let (_view, cx) = cx.add_window_view(move |_, cx| {
            let state = cx.new(|cx| {
                QuestionnaireState::new(
                    vec![
                        QuestionnaireItemDefinition::new("scale", "Scale")
                            .with_choice(QuestionnaireChoiceDefinition::new("alpha", "Alpha")),
                    ],
                    cx,
                )
                .unwrap()
            });
            ScaleHarness {
                state,
                root_size,
                part_size,
            }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        cx.debug_bounds("scale-choice").expect("choice rendered")
    }

    #[gpui::test]
    fn parts_take_their_scale_from_the_root_and_a_part_may_override_it(cx: &mut TestAppContext) {
        // A part left alone must land exactly where the same part told to use
        // the root's size lands: the root publishes the scale for all of them.
        let inherited = scale_harness(cx, Size::Small, None);
        let explicit = scale_harness(cx, Size::Small, Some(Size::Small));
        assert_eq!(inherited.size, explicit.size);

        // A different root scale has to move the part, or nothing was inherited.
        let large_root = scale_harness(cx, Size::Large, None);
        assert!(large_root.size.height > inherited.size.height);

        // A part that names its own size keeps it whatever the root says.
        let overridden = scale_harness(cx, Size::Large, Some(Size::Small));
        assert_eq!(overridden.size, inherited.size);
    }

    #[gpui::test]
    fn shortcut_guards_held_keys_before_activation(cx: &mut TestAppContext) {
        let (cx, state) = visual_harness(
            cx,
            vec![
                QuestionnaireItemDefinition::new("choice", "Choice")
                    .with_choice(QuestionnaireChoiceDefinition::new("alpha", "Alpha")),
                QuestionnaireItemDefinition::new("second", "Second"),
            ],
            Some(QuestionnaireShortcutMode::Letters),
        );

        simulate_key(cx, "a", true, true);
        simulate_key(cx, "a", false, false);
        simulate_key(cx, "shift-a", false, true);
        cx.update(|_, cx| assert!(state.read(cx).answer("choice").unwrap().is_empty()));

        simulate_key(cx, "a", false, true);
        cx.update(|window, cx| {
            assert_eq!(
                state.read(cx).answer("choice").unwrap().choices(),
                &[SharedString::from("alpha")]
            );
            assert_eq!(
                state
                    .read(cx)
                    .focused_current_choice(window)
                    .map(SharedString::as_ref),
                Some("alpha")
            );
        });
        simulate_key(cx, "enter", false, false);
        cx.update(|_, cx| {
            assert_eq!(state.read(cx).current_item().unwrap().as_ref(), "second");
        });
    }

    #[gpui::test]
    fn root_keyboard_preserves_navigation_and_radio_semantics(cx: &mut TestAppContext) {
        let (cx, state) = visual_harness(
            cx,
            vec![
                QuestionnaireItemDefinition::new("first", "First")
                    .with_required(true)
                    .with_choices([
                        QuestionnaireChoiceDefinition::new("alpha", "Alpha"),
                        QuestionnaireChoiceDefinition::new("beta", "Beta"),
                    ]),
                QuestionnaireItemDefinition::new("second", "Second"),
            ],
            None,
        );

        simulate_key(cx, "right", false, false);
        cx.update(|_, cx| {
            assert_eq!(state.read(cx).current_item().unwrap().as_ref(), "first");
            assert!(state.read(cx).answer("first").unwrap().is_empty());
        });

        cx.update(|window, cx| {
            let focus_handle = state
                .read(cx)
                .choice_focus_handle("first", "alpha")
                .unwrap()
                .clone();
            focus_handle.focus(window, cx);
        });
        simulate_key(cx, "enter", false, false);
        cx.update(|_, cx| {
            assert_eq!(state.read(cx).current_item().unwrap().as_ref(), "first");
            assert!(state.read(cx).answer("first").unwrap().is_empty());
        });

        simulate_key(cx, "right", false, false);
        cx.update(|window, cx| window.draw(cx).clear(cx));
        cx.update(|_, cx| {
            assert_eq!(
                state.read(cx).answer("first").unwrap().choices(),
                &[SharedString::from("beta")]
            );
            assert_eq!(state.read(cx).current_item().unwrap().as_ref(), "first");
        });

        simulate_key(cx, "enter", false, false);
        cx.update(|_, cx| {
            assert_eq!(state.read(cx).current_item().unwrap().as_ref(), "second");
        });
    }

    #[gpui::test]
    fn empty_input_enter_stays_put_and_arrows_move_to_answers(cx: &mut TestAppContext) {
        let (cx, state) = input_visual_harness(cx, false);
        focus_input(cx, &state, "first");

        simulate_key(cx, "enter", false, false);
        cx.update(|_, cx| {
            assert_eq!(state.read(cx).current_item().unwrap().as_ref(), "first");
            assert!(state.read(cx).answer("first").unwrap().is_empty());
            assert!(state.read(cx).error("first").is_none());
        });

        simulate_key(cx, "secondary-enter", false, false);
        cx.update(|_, cx| {
            assert_eq!(state.read(cx).current_item().unwrap().as_ref(), "first");
            assert!(state.read(cx).error("first").is_some());
        });

        focus_input(cx, &state, "first");
        simulate_key(cx, "up", false, false);
        cx.update(|window, cx| {
            assert_eq!(
                state
                    .read(cx)
                    .focused_current_choice(window)
                    .map(SharedString::as_ref),
                Some("beta")
            );
        });

        simulate_key(cx, "down", false, false);
        cx.update(|window, cx| {
            assert!(state.read(cx).is_current_input_focused(window));
            assert_eq!(
                state.read(cx).answer("first").unwrap().choices(),
                &[SharedString::from("beta")]
            );
        });

        simulate_key(cx, "down", false, false);
        cx.update(|window, cx| {
            assert_eq!(
                state
                    .read(cx)
                    .focused_current_choice(window)
                    .map(SharedString::as_ref),
                Some("alpha")
            );
            assert_eq!(
                state.read(cx).answer("first").unwrap().choices(),
                &[SharedString::from("alpha")]
            );
        });

        simulate_key(cx, "down", false, false);
        cx.update(|window, cx| {
            assert_eq!(
                state
                    .read(cx)
                    .focused_current_choice(window)
                    .map(SharedString::as_ref),
                Some("beta")
            );
            assert_eq!(
                state.read(cx).answer("first").unwrap().choices(),
                &[SharedString::from("beta")]
            );
        });

        cx.update(|window, cx| {
            state.update(cx, |state, cx| {
                state
                    .set_input_value("first", "Preserved draft", window, cx)
                    .unwrap();
                state.activate_choice("first", "alpha", cx).unwrap();
            });
        });
        focus_input(cx, &state, "first");
        simulate_key(cx, "enter", false, false);
        cx.update(|_, cx| {
            let answer = state.read(cx).answer("first").unwrap();
            assert_eq!(state.read(cx).current_item().unwrap().as_ref(), "first");
            assert_eq!(answer.choices(), &[SharedString::from("alpha")]);
            assert!(answer.freeform().is_none());
        });
    }

    #[gpui::test]
    fn filled_group_input_keeps_text_editing_directions(cx: &mut TestAppContext) {
        let (cx, state) = input_visual_harness(cx, true);
        cx.update(|window, cx| {
            state
                .update(cx, |state, cx| {
                    state.set_input_value("first", "Freeform answer", window, cx)
                })
                .unwrap();
        });
        focus_input(cx, &state, "first");

        simulate_key(cx, "down", false, false);
        cx.update(|window, cx| {
            let state = state.read(cx);
            assert!(state.is_current_input_focused(window));
            assert_eq!(
                state
                    .answer("first")
                    .unwrap()
                    .freeform()
                    .map(SharedString::as_ref),
                Some("Freeform answer")
            );
            assert!(state.answer("first").unwrap().choices().is_empty());
        });

        simulate_key(cx, "up", false, false);
        cx.update(|window, cx| {
            let state = state.read(cx);
            assert!(state.is_current_input_focused(window));
            assert_eq!(
                state
                    .answer("first")
                    .unwrap()
                    .freeform()
                    .map(SharedString::as_ref),
                Some("Freeform answer")
            );
            assert!(state.answer("first").unwrap().choices().is_empty());
        });
    }

    /// A single-answer item, a multiple-answer item, then a last single-answer
    /// item with a freeform input; each choice sits in a wrapper the test can
    /// click by its debug selector.
    struct ChooseHarness {
        state: Entity<QuestionnaireState>,
        submits: usize,
        _subscription: gpui::Subscription,
    }

    impl Render for ChooseHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let state = &self.state;
            let choice = |item: &'static str, value: &'static str| {
                div()
                    .id(SharedString::from(format!("choice-{item}-{value}")))
                    .debug_selector(move || format!("choice-{item}-{value}"))
                    .child(QuestionnaireChoice::new(state, item, value))
            };
            Questionnaire::new(state)
                .size(px(480.))
                .child(
                    QuestionnaireItem::new(state, "first").child(
                        QuestionnaireChoices::new(state, "first")
                            .child(choice("first", "alpha"))
                            .child(choice("first", "beta")),
                    ),
                )
                .child(
                    QuestionnaireItem::new(state, "second").child(
                        QuestionnaireChoices::new(state, "second")
                            .child(choice("second", "x"))
                            .child(choice("second", "y")),
                    ),
                )
                .child(
                    QuestionnaireItem::new(state, "third")
                        .child(
                            QuestionnaireChoices::new(state, "third")
                                .child(choice("third", "omega")),
                        )
                        .child(QuestionnaireInput::new(state, "third")),
                )
        }
    }

    fn choose_harness(
        cx: &mut TestAppContext,
    ) -> (
        &mut VisualTestContext,
        Entity<ChooseHarness>,
        Entity<QuestionnaireState>,
    ) {
        cx.update(crate::init);
        let (view, cx) = cx.add_window_view(|window, cx| {
            let input = cx.new(|cx| crate::input::InputState::new(window, cx));
            let state = cx.new(|cx| {
                QuestionnaireState::new(
                    vec![
                        QuestionnaireItemDefinition::new("first", "First").with_choices([
                            QuestionnaireChoiceDefinition::new("alpha", "Alpha"),
                            QuestionnaireChoiceDefinition::new("beta", "Beta"),
                        ]),
                        QuestionnaireItemDefinition::new("second", "Second")
                            .with_multiple(true)
                            .with_choices([
                                QuestionnaireChoiceDefinition::new("x", "X"),
                                QuestionnaireChoiceDefinition::new("y", "Y"),
                            ]),
                        QuestionnaireItemDefinition::new("third", "Third")
                            .with_choice(QuestionnaireChoiceDefinition::new("omega", "Omega"))
                            .with_input(QuestionnaireInputDefinition::new(input, "Other")),
                    ],
                    cx,
                )
                .unwrap()
                .with_shortcuts(QuestionnaireShortcutMode::Numbers)
            });
            let subscription = cx.subscribe(&state, |this: &mut ChooseHarness, _, event, _| {
                if matches!(event, QuestionnaireEvent::Submit(_)) {
                    this.submits += 1;
                }
            });
            ChooseHarness {
                state,
                submits: 0,
                _subscription: subscription,
            }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let state = cx.update(|_, cx| view.read(cx).state.clone());
        cx.update(|window, cx| {
            let focus_handle = state.read(cx).focus_handle().clone();
            focus_handle.focus(window, cx);
        });
        (cx, view, state)
    }

    /// Past the hold a newly chosen single answer keeps before confirming.
    fn wait_out_hold(cx: &mut VisualTestContext) {
        cx.executor()
            .advance_clock(std::time::Duration::from_millis(200));
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));
    }

    fn click_choice(cx: &mut VisualTestContext, item: &str, value: &str) {
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let selector = Box::leak(format!("choice-{item}-{value}").into_boxed_str());
        let bounds = cx.debug_bounds(selector).expect("choice rendered");
        cx.simulate_click(bounds.center(), gpui::Modifiers::default());
    }

    fn press(cx: &mut VisualTestContext, key: &str) {
        let os = cx.update(|_, cx| cx.platform_info().os);
        let keystroke = Keystroke::parse_with_os(key, os).unwrap();
        cx.simulate_event(KeyDownEvent {
            keystroke: keystroke.clone(),
            is_held: false,
            prefer_character_input: false,
        });
        cx.simulate_event(gpui::KeyUpEvent { keystroke });
    }

    fn focus_choice(
        cx: &mut VisualTestContext,
        state: &Entity<QuestionnaireState>,
        item: &str,
        value: &str,
    ) {
        cx.update(|window, cx| {
            let focus_handle = state
                .read(cx)
                .choice_focus_handle(item, value)
                .unwrap()
                .clone();
            focus_handle.focus(window, cx);
        });
    }

    fn current(cx: &mut VisualTestContext, state: &Entity<QuestionnaireState>) -> SharedString {
        cx.update(|_, cx| state.read(cx).current_item().unwrap().clone())
    }

    fn choices(
        cx: &mut VisualTestContext,
        state: &Entity<QuestionnaireState>,
        item: &str,
    ) -> Vec<SharedString> {
        cx.update(|_, cx| state.read(cx).answer(item).unwrap().choices().to_vec())
    }

    #[gpui::test]
    fn clicking_a_single_choice_shows_it_then_advances(cx: &mut TestAppContext) {
        let (cx, view, state) = choose_harness(cx);

        click_choice(cx, "first", "alpha");
        cx.run_until_parked();
        assert_eq!(
            choices(cx, &state, "first"),
            vec![SharedString::from("alpha")]
        );
        assert_eq!(current(cx, &state), "first", "the selection paints first");
        wait_out_hold(cx);
        assert_eq!(current(cx, &state), "second");

        click_choice(cx, "second", "x");
        wait_out_hold(cx);
        assert_eq!(current(cx, &state), "second", "a checkbox only toggles");
        assert_eq!(choices(cx, &state, "second"), vec![SharedString::from("x")]);

        cx.update(|window, cx| state.update(cx, |state, cx| state.go_next(window, cx)));
        focus_input(cx, &state, "third");
        cx.simulate_input("draft");
        wait_out_hold(cx);
        assert_eq!(current(cx, &state), "third", "typing never advances");

        click_choice(cx, "third", "omega");
        click_choice(cx, "third", "omega");
        wait_out_hold(cx);
        assert_eq!(
            cx.update(|_, cx| view.read(cx).submits),
            1,
            "a double click on the last item submits once"
        );

        // Choosing the selected answer again after going back confirms it.
        cx.update(|window, cx| {
            state
                .update(cx, |state, cx| state.set_current_item("first", window, cx))
                .unwrap();
        });
        click_choice(cx, "first", "alpha");
        assert_eq!(current(cx, &state), "second");
    }

    #[gpui::test]
    fn shortcuts_and_space_advance_while_arrows_only_move(cx: &mut TestAppContext) {
        let (cx, _, state) = choose_harness(cx);

        focus_choice(cx, &state, "first", "alpha");
        press(cx, "down");
        wait_out_hold(cx);
        assert_eq!(
            choices(cx, &state, "first"),
            vec![SharedString::from("beta")]
        );
        assert_eq!(
            current(cx, &state),
            "first",
            "an arrow moves the selection only"
        );

        simulate_key(cx, "1", false, true);
        cx.run_until_parked();
        assert_eq!(
            choices(cx, &state, "first"),
            vec![SharedString::from("alpha")]
        );
        assert_eq!(current(cx, &state), "first");
        wait_out_hold(cx);
        assert_eq!(current(cx, &state), "second");

        simulate_key(cx, "2", false, true);
        wait_out_hold(cx);
        assert_eq!(
            current(cx, &state),
            "second",
            "a multiple-answer shortcut toggles"
        );
        assert_eq!(choices(cx, &state, "second"), vec![SharedString::from("y")]);

        cx.update(|window, cx| state.update(cx, |state, cx| state.go_previous(window, cx)));
        focus_choice(cx, &state, "first", "beta");
        press(cx, "space");
        wait_out_hold(cx);
        assert_eq!(
            choices(cx, &state, "first"),
            vec![SharedString::from("beta")]
        );
        assert_eq!(current(cx, &state), "second", "Space chooses and advances");
    }

    #[test]
    fn invalid_error_projects_alert_role() {
        let error = questionnaire_error_root("questionnaire-error-test".into()).into_element();
        assert_eq!(error.a11y_role(), Some(Role::Alert));
    }
}
