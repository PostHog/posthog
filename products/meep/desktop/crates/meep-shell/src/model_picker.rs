//! View's composer picker. Hosts supply a catalogue and acknowledge changes through
//! `set_selection`. Browsing another agent never changes the running conversation.
use super::*;
use gpui_kit::component::{
    ActiveTheme, Disableable,
    button::{ButtonCustomVariant, ButtonVariants},
    input::{Input, InputEvent, InputState},
    popover::Popover,
};
use meep_ui::agent_marks::{self, AgentMark};
use std::rc::Rc;

mod motion;
const SEARCH_FROM: usize = 9;
const ROW: f32 = 30.;

/// Models grouped under one selectable agent.
pub struct AgentModels {
    /// Stable ID for this agent group.
    pub id: String,
    /// Group label shown to the user.
    pub name: String,
    /// Optional mark for this agent.
    pub mark: Option<&'static AgentMark>,
    /// Models offered by this agent.
    pub models: Vec<Model>,
}

/// A selectable model in an agent's catalogue.
pub struct Model {
    /// Backend identifier emitted when the model is chosen.
    pub id: String,
    /// Human-readable model name.
    pub name: String,
    /// Quiet caveat shown beside the name in the menu, such as a missing capability.
    pub note: Option<String>,
}

/// Reasoning effort settings reported by the backend.
#[derive(Clone, Default, PartialEq)]
pub struct Effort {
    /// Backend values and display labels, lowest first.
    pub levels: Vec<(String, String)>,
    /// Currently selected effort level.
    pub current: Option<String>,
    /// Default effort level reported by the backend.
    pub default: Option<String>,
    /// Whether the user may restore the default effort.
    pub can_reset: bool,
}

/// A model picker request for the host to handle.
pub enum Change {
    /// Select a model, or use the backend default.
    Model(Option<String>),
    /// Select an effort level, or restore the default.
    Effort(Option<String>),
    /// Request a fresh model catalogue.
    Refresh,
    /// Perform the recovery action supplied by the host.
    Recover,
}

#[derive(Clone, Copy)]
enum Entry<'a> {
    Agent(&'a AgentModels),
    Model(&'a Model),
    Default,
}

#[derive(Clone, Copy)]
enum RowIndex {
    Agent(usize),
    Model(usize, usize),
    Default,
}

impl RowIndex {
    fn entry(self, agents: &[AgentModels]) -> Entry<'_> {
        match self {
            Self::Agent(i) => Entry::Agent(&agents[i]),
            Self::Model(a, i) => Entry::Model(&agents[a].models[i]),
            Self::Default => Entry::Default,
        }
    }
}

#[derive(Clone)]
enum Choice {
    Agent(String),
    Model(Option<String>),
}

impl Entry<'_> {
    fn choice(self) -> Choice {
        match self {
            Self::Agent(agent) => Choice::Agent(agent.id.clone()),
            Self::Model(model) => Choice::Model(Some(model.id.clone())),
            Self::Default => Choice::Model(None),
        }
    }
}

/// A composer control for browsing agents, models and reasoning efforts.
pub struct ModelPicker {
    agents: Rc<[AgentModels]>,
    selected: Option<String>,
    default_model: Option<String>,
    default_runtime: Option<String>,
    effort: Effort,
    allow_default: bool,
    loading: bool,
    error: Option<String>,
    recovery: Option<String>,
    disabled: bool,
    compact: bool,
    open: bool,
    /// The agent being browsed. Only backend acknowledgement changes the trigger.
    page: Option<String>,
    cursor: Option<usize>,
    query: Entity<InputState>,
    focus: FocusHandle,
    return_focus: FocusHandle,
    scroll: UniformListScrollHandle,
    motion: Rc<motion::PickerMotion>,
}

impl EventEmitter<Change> for ModelPicker {}

impl ModelPicker {
    /// Create a picker that returns focus to the supplied host control.
    pub fn new(return_focus: FocusHandle, w: &mut Window, cx: &mut Context<Self>) -> Self {
        let query = cx.new(|cx| InputState::new(w, cx).placeholder("Find a model…"));
        cx.subscribe(&query, |this, _, event: &InputEvent, cx| {
            if matches!(event, InputEvent::Change) {
                this.cursor = None;
                this.scroll.scroll_to_item_strict(0, ScrollStrategy::Top);
                cx.notify();
            }
        })
        .detach();
        Self {
            agents: Rc::default(),
            selected: None,
            default_model: None,
            default_runtime: None,
            effort: Effort::default(),
            allow_default: true,
            loading: true,
            error: None,
            recovery: None,
            disabled: true,
            compact: false,
            open: false,
            page: None,
            cursor: None,
            query,
            focus: cx.focus_handle(),
            return_focus,
            scroll: UniformListScrollHandle::new(),
            motion: Rc::default(),
        }
    }

    /// Replace the model catalogue with the latest result from the host.
    pub fn set_catalog(&mut self, agents: Vec<AgentModels>, cx: &mut Context<Self>) {
        self.agents = agents.into();
        if self.page.is_some() && self.group().is_none() {
            self.page = None;
        }
        self.cursor = None;
        self.loading = false;
        self.error = None;
        self.recovery = None;
        cx.notify();
    }

    /// Show an error from the latest attempt to load the catalogue.
    pub fn set_catalog_error(&mut self, error: String, cx: &mut Context<Self>) {
        self.loading = false;
        self.agents = Rc::default();
        self.page = None;
        self.cursor = None;
        self.error = Some(error);
        self.recovery = None;
        cx.notify();
    }

    /// Add an explicit recovery action to the current error.
    pub fn set_recovery(&mut self, label: Option<String>, cx: &mut Context<Self>) {
        self.recovery = label;
        cx.notify();
    }

    /// Show the model and effort acknowledged by the backend.
    pub fn set_selection(
        &mut self,
        model: Option<&str>,
        effort: Effort,
        allow_default: bool,
        cx: &mut Context<Self>,
    ) {
        if self.selected.as_deref() != model
            || self.effort != effort
            || self.allow_default != allow_default
        {
            self.selected = model.map(str::to_owned);
            self.effort = effort;
            self.allow_default = allow_default;
            cx.notify();
        }
    }

    /// Set the effective backend default without pinning the person's choice.
    pub fn set_default_model(
        &mut self,
        model: Option<&str>,
        runtime: Option<&str>,
        cx: &mut Context<Self>,
    ) {
        if self.default_model.as_deref() != model || self.default_runtime.as_deref() != runtime {
            self.default_model = model.map(str::to_owned);
            self.default_runtime = runtime.map(str::to_owned);
            cx.notify();
        }
    }

    /// Set availability and compact presentation of the picker button.
    pub fn set_trigger(&mut self, disabled: bool, compact: bool, cx: &mut Context<Self>) {
        if (disabled, compact) != (self.disabled, self.compact) {
            self.disabled = disabled;
            self.compact = compact;
            cx.notify();
        }
    }

    /// Dismiss transient navigation when the host switches away from the composer.
    pub fn dismiss(&mut self, cx: &mut Context<Self>) {
        if self.open {
            self.open = false;
            cx.notify();
        }
    }

    fn group(&self) -> Option<&AgentModels> {
        self.page
            .as_deref()
            .and_then(|id| self.agents.iter().find(|a| a.id == id))
    }

    fn selected_model(&self) -> Option<(&AgentModels, &Model)> {
        let id = self.selected.as_deref().or(self.default_model.as_deref())?;
        self.agents
            .iter()
            .filter(|a| {
                self.selected.is_some()
                    || self
                        .default_runtime
                        .as_deref()
                        .is_none_or(|runtime| a.id == runtime)
            })
            .find_map(|a| a.models.iter().find(|m| m.id == id).map(|m| (a, m)))
    }

    fn searchable(&self) -> bool {
        self.group().map_or(self.agents.len(), |a| a.models.len()) >= SEARCH_FROM
    }

    fn reset_page(&mut self, w: &mut Window, cx: &mut Context<Self>) {
        self.cursor = None;
        self.scroll.scroll_to_item_strict(0, ScrollStrategy::Top);
        self.query.update(cx, |s, cx| s.set_value("", w, cx));
        self.focus.focus(w, cx);
        cx.notify();
    }

    fn opened(&mut self, open: bool, w: &mut Window, cx: &mut Context<Self>) {
        self.open = open;
        if open {
            self.page = self
                .selected_model()
                .map(|(a, _)| a.id.clone())
                .or_else(|| (self.agents.len() == 1).then(|| self.agents[0].id.clone()));
            self.motion.opened();
            self.reset_page(w, cx);
        }
        cx.notify();
    }

    fn turn(&mut self, group: Option<String>, w: &mut Window, cx: &mut Context<Self>) {
        self.page = group;
        self.motion.turned();
        self.reset_page(w, cx);
    }

    fn entries(&self, cx: &App) -> Vec<RowIndex> {
        let query = if self.searchable() {
            self.query.read(cx).value().trim().to_lowercase()
        } else {
            String::new()
        };
        let matches = |name: &str, id: &str| {
            query.is_empty()
                || name.to_lowercase().contains(&query)
                || id.to_lowercase().contains(&query)
        };
        if let Some((a, group)) = self
            .agents
            .iter()
            .enumerate()
            .find(|(_, g)| Some(&g.id) == self.page.as_ref())
        {
            group
                .models
                .iter()
                .enumerate()
                .filter(|(_, m)| matches(&m.name, &m.id))
                .map(|(i, _)| RowIndex::Model(a, i))
                .collect()
        } else {
            self.agents
                .iter()
                .enumerate()
                .filter(|(_, a)| matches(&a.name, &a.id))
                .map(|(i, _)| RowIndex::Agent(i))
                .chain(
                    (self.allow_default
                        && matches("Default", "default")
                        && !self.agents.is_empty())
                    .then_some(RowIndex::Default),
                )
                .collect()
        }
    }

    fn choose(&mut self, choice: Choice, w: &mut Window, cx: &mut Context<Self>) {
        // Revalidate the painted row by ID. A refresh can replace or reorder it before mouse-up.
        match choice {
            Choice::Agent(id) => {
                if self.agents.iter().any(|a| a.id == id) {
                    self.turn(Some(id), w, cx);
                }
            }
            Choice::Model(id) => {
                let available = match &id {
                    Some(id) => self
                        .group()
                        .is_some_and(|a| a.models.iter().any(|m| m.id == *id)),
                    None => self.allow_default,
                };
                if self.disabled || !available {
                    return;
                }
                self.open = false;
                self.return_focus.focus(w, cx);
                if id != self.selected {
                    cx.emit(Change::Model(id));
                }
                cx.notify();
            }
        }
    }

    fn effort_index(&self) -> Option<usize> {
        let id = self
            .effort
            .current
            .as_ref()
            .or(self.effort.default.as_ref())?;
        self.effort.levels.iter().position(|(value, _)| value == id)
    }
    fn shows_effort(&self) -> bool {
        self.page.is_some()
            && !self.effort.levels.is_empty()
            && self
                .selected_model()
                .is_some_and(|(a, _)| Some(&a.id) == self.page.as_ref())
    }

    fn set_level(&self, value: &str, toggle: bool, cx: &mut Context<Self>) {
        if self.disabled {
            return;
        }
        if !self.effort.levels.iter().any(|(id, _)| id == value) {
            return;
        }
        if self.effort.current.as_deref() != Some(value) {
            cx.emit(Change::Effort(Some(value.to_owned())));
        } else if toggle && self.effort.can_reset {
            cx.emit(Change::Effort(None));
        }
    }

    fn key(&mut self, e: &KeyDownEvent, w: &mut Window, cx: &mut Context<Self>) {
        match e.keystroke.key.as_str() {
            "escape" => {
                self.open = false;
                self.return_focus.focus(w, cx);
            }
            key @ ("up" | "down") => {
                let count = self.entries(cx).len();
                if count > 0 {
                    let next = match (self.cursor, key) {
                        (Some(i), "down") => (i + 1).min(count - 1),
                        (Some(i), _) => i.saturating_sub(1),
                        (None, "down") => 0,
                        _ => count - 1,
                    };
                    self.cursor = Some(next);
                    self.scroll.scroll_to_item(next, ScrollStrategy::Nearest);
                }
            }
            "enter" => {
                if let Some(entry) = self.entries(cx).get(self.cursor.unwrap_or(0)).copied() {
                    self.choose(entry.entry(&self.agents).choice(), w, cx);
                }
            }
            key @ ("left" | "right")
                if self.shows_effort() && !self.query.read(cx).focus_handle(cx).is_focused(w) =>
            {
                let index = self.effort_index().map_or(0, |i| {
                    i.saturating_add_signed(if key == "left" { -1 } else { 1 })
                        .min(self.effort.levels.len() - 1)
                });
                self.set_level(&self.effort.levels[index].0, false, cx);
            }
            _ => return,
        }
        cx.stop_propagation();
        cx.notify();
    }

    fn entry_row(&self, entry: Entry<'_>, index: usize, cx: &mut Context<Self>) -> Stateful<Div> {
        let note = match entry {
            Entry::Model(m) => m.note.clone(),
            _ => None,
        };
        let (id, name, current) = match entry {
            Entry::Model(m) => (
                format!("agent-model-{}", m.id),
                m.name.as_str(),
                Some(&m.id) == self.selected.as_ref(),
            ),
            Entry::Agent(a) => (
                format!("agent-provider-{}", a.id),
                a.name.as_str(),
                self.selected_model().is_some_and(|(g, _)| g.id == a.id),
            ),
            Entry::Default => (
                "agent-model-default".into(),
                "Default",
                self.selected.is_none(),
            ),
        };
        let mut row = div()
            .id(SharedString::from(id))
            .role(Role::MenuItem)
            .aria_label(name.to_owned())
            .aria_selected(current)
            .flex()
            .items_center()
            .gap(px(10.))
            .h(px(ROW))
            .flex_shrink_0()
            .px(px(10.))
            .rounded(px(7.))
            .cursor_pointer()
            .hover(|s| s.bg(ui::ink(0x0a)))
            .active(|s| s.bg(ui::ink(0x12)))
            .when(self.cursor == Some(index), |r| r.bg(ui::ink(0x0a)));
        if let Entry::Agent(agent) = entry {
            row = row.child(agent_marks::icon(agent.mark, 16.));
        }
        row = row.child(
            text(name.to_owned())
                .flex_1()
                .min_w_0()
                .truncate()
                .text_size(px(ui::BODY))
                .text_color(rgb(ui::theme::color(INK))),
        );
        if let Some(note) = note {
            row = row.child(
                text(note)
                    .flex_none()
                    .text_size(px(12.))
                    .text_color(rgb(ui::theme::color(MUTED))),
            );
        }
        if let Entry::Agent(_) = entry {
            if let Some((_, m)) = self.selected_model().filter(|_| current) {
                row = row.child(
                    text(m.name.clone())
                        .text_size(px(12.))
                        .text_color(rgb(ui::theme::color(MUTED)))
                        .max_w(px(110.))
                        .truncate(),
                );
            }
            row = row.child(
                icon(Glyph::ChevronRight)
                    .size(px(12.))
                    .text_color(rgb(ui::theme::color(MUTED))),
            );
        } else {
            row = row.child(div().flex_none().w(px(14.)).when(current, |el| {
                el.child(
                    icon(Glyph::Check)
                        .size(px(14.))
                        .text_color(rgb(ui::theme::color(INK))),
                )
            }));
        }
        let choice = entry.choice();
        row.on_click(cx.listener(move |this, _, w, cx| this.choose(choice.clone(), w, cx)))
    }

    fn sheet(&self, w: &mut Window, cx: &mut Context<Self>) -> AnyElement {
        let group = self.group();
        let searchable = self.searchable();
        if searchable && self.focus.is_focused(w) {
            self.query.read(cx).focus_handle(cx).focus(w, cx);
        }
        let sheet = col()
            .id("agent-picker")
            .role(Role::Menu)
            .relative()
            .w(px(300.).min(w.viewport_size().width - px(16.)))
            .bg(rgb(ui::theme::color(PAPER)))
            .rounded(px(12.))
            .overflow_hidden()
            .occlude()
            .track_focus(&self.focus)
            .capture_key_down(cx.listener(Self::key));
        let header = row()
            .h(px(40.))
            .pl(px(if group.is_some() { 8. } else { 16. }))
            .pr(px(8.))
            .gap(px(6.))
            .flex_shrink_0()
            .when_some(group, |row, a| {
                row.child(
                    ui::icon_button("agent-picker-back", Glyph::ChevronLeft, "All agents")
                        .size(px(24.))
                        .on_click(cx.listener(|this, _, w, cx| this.turn(None, w, cx))),
                )
                .child(agent_marks::icon(a.mark, 14.))
            })
            .child(
                text(group.map_or_else(|| "Agent".into(), |a| format!("{} models", a.name)))
                    .flex_1()
                    .min_w_0()
                    .truncate()
                    .text_size(px(12.))
                    .font_weight(FontWeight::MEDIUM)
                    .text_color(rgb(ui::theme::color(MUTED))),
            )
            .when(
                group.is_some() || self.agents.is_empty() || self.error.is_some(),
                |row| {
                    row.child(
                        ui::icon_button("agent-picker-refresh", Glyph::RefreshCw, "Refresh models")
                            .size(px(24.))
                            .disabled(self.loading)
                            .on_click(cx.listener(|this, _, _, cx| {
                                this.loading = true;
                                this.error = None;
                                cx.emit(Change::Refresh);
                                cx.notify();
                            })),
                    )
                },
            );
        let mut page = col().w_full().child(header);
        if searchable {
            page = page.child(
                div()
                    .mx(px(8.))
                    .mb(px(6.))
                    .h(px(28.))
                    .rounded(px(7.))
                    .bg(ui::ink(0x0a))
                    .flex()
                    .items_center()
                    .child(
                        Input::new(&self.query)
                            .small()
                            .appearance(false)
                            .w_full()
                            .py_0()
                            .text_size(px(ui::BODY))
                            .prefix(
                                icon(Glyph::Search)
                                    .size(px(12.))
                                    .text_color(rgb(ui::theme::color(MUTED))),
                            )
                            .aria_label("Find a model"),
                    ),
            );
        }
        let entries = self.entries(cx);
        let footer = self.shows_effort();
        let list_height = (w.viewport_size().height
            - px(108. + if searchable { 34. } else { 0. } + if footer { 60. } else { 0. }))
        .clamp(px(ROW), px(296.));
        let mut list = col()
            .id("agent-picker-list")
            .max_h(list_height)
            .px(px(6.))
            .pb(px(6.))
            .gap(px(1.));
        let empty = entries.is_empty();
        if !empty {
            let catalog = self.agents.clone();
            let owner = cx.weak_entity();
            // Width and hit targets follow View's rows. GPUI only shapes the visible range.
            let content_height = px(entries.len() as f32 * (ROW + 1.) - 1.);
            let viewport =
                (list_height - px(6.) - if self.loading { px(ROW + 1.) } else { px(0.) })
                    .max(px(ROW));
            list = list.child(
                uniform_list("model-choices", entries.len(), move |range, _, cx| {
                    owner
                        .update(cx, |this, cx| {
                            range
                                .map(|i| {
                                    div().w_full().h(px(ROW + 1.)).child(this.entry_row(
                                        entries[i].entry(&catalog),
                                        i,
                                        cx,
                                    ))
                                })
                                .collect::<Vec<_>>()
                        })
                        .unwrap_or_default()
                })
                .track_scroll(&self.scroll)
                .w_full()
                .h(content_height.min(viewport)),
            );
        }
        if self.loading || empty && self.error.is_none() {
            let status = if self.loading {
                "Loading models…"
            } else if self.agents.is_empty() {
                "No models available"
            } else {
                "No matching models"
            };
            list = list.child(
                text(status)
                    .id("model-list-status")
                    .px(px(10.))
                    .h(px(ROW))
                    .flex()
                    .items_center()
                    .text_size(px(12.))
                    .text_color(rgb(ui::theme::color(MUTED))),
            );
        }
        page = page.child(list);
        if let Some(error) = &self.error {
            page =
                page.child(
                    div()
                        .px(px(16.))
                        .pb(px(10.))
                        .child(ui::error_message("models-error", error.clone()))
                        .when_some(self.recovery.clone(), |d, label| {
                            d.child(ui::button("agent-picker-recover", label).on_click(
                                cx.listener(|this, _, _, cx| {
                                    this.loading = true;
                                    this.error = None;
                                    this.recovery = None;
                                    cx.emit(Change::Recover);
                                    cx.notify();
                                }),
                            ))
                        }),
                );
        }
        if footer {
            page = page.child(self.footer(w, cx));
        }
        motion::finish(sheet, page, self.motion.clone(), group.is_none(), w, cx)
    }
    fn footer(&self, window: &mut Window, cx: &mut Context<Self>) -> Div {
        let shown = self.effort_index();
        let level = gpui_kit::base::spring(
            ElementId::from("effort-level"),
            shown.map_or(0., |i| (i + 1) as f32),
            cx.theme().motion_tokens().spring_control,
            window,
            cx,
        );
        let fill = if self.effort.current.is_some() {
            ui::ink(0xff)
        } else {
            ui::ink(0x5c)
        };
        let mut track = row().w_full().gap(px(3.));
        for (index, (id, name)) in self.effort.levels.iter().enumerate() {
            let id = id.clone();
            let amount = (level - index as f32).clamp(0., 1.);
            track = track.child(
                div()
                    .id(SharedString::from(format!("effort-step-{index}")))
                    .role(Role::MenuItemRadio)
                    .aria_label(SharedString::from(name.clone()))
                    .aria_selected(shown == Some(index))
                    .flex_1()
                    .h(px(18.))
                    .flex()
                    .items_center()
                    .cursor_pointer()
                    .child(
                        div()
                            .relative()
                            .w_full()
                            .h(px(4.))
                            .rounded_full()
                            .bg(ui::ink(0x14))
                            .overflow_hidden()
                            .when(amount > 0., |seg| {
                                seg.child(
                                    div()
                                        .absolute()
                                        .left_0()
                                        .top_0()
                                        .h_full()
                                        .w(relative(amount))
                                        .bg(fill),
                                )
                            }),
                    )
                    .on_click(cx.listener(move |this, _, _, cx| this.set_level(&id, true, cx))),
            );
        }
        let name = shown
            .and_then(|i| self.effort.levels.get(i))
            .map_or("Default".to_owned(), |(_, n)| n.clone());
        col()
            .px(px(14.))
            .pt(px(10.))
            .pb(px(10.))
            .gap(px(4.))
            .border_t_1()
            .border_color(rgb(ui::theme::color(LINE)))
            .child(
                row()
                    .h(px(18.))
                    .gap(px(4.))
                    .child(
                        text("Effort")
                            .flex_1()
                            .text_size(px(12.))
                            .font_weight(FontWeight::MEDIUM)
                            .text_color(rgb(ui::theme::color(MUTED))),
                    )
                    .child(
                        text(name)
                            .text_size(px(12.))
                            .font_weight(FontWeight::MEDIUM)
                            .text_color(rgb(ui::theme::color(INK))),
                    )
                    .when(self.effort.current.is_none() && shown.is_some(), |row| {
                        row.child(
                            text("· Default")
                                .text_size(px(12.))
                                .text_color(rgb(ui::theme::color(MUTED))),
                        )
                    }),
            )
            .child(track)
    }
}
impl Render for ModelPicker {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let selection = self.selected_model();
        let name = selection
            .map(|(_, m)| m.name.as_str())
            .or(self.selected.as_deref())
            // With no choice yet, a host that allows it runs on the backend default.
            .unwrap_or(if self.allow_default && !self.agents.is_empty() {
                "Default model"
            } else {
                "Choose agent"
            });
        let mark = match selection {
            Some((agent, _)) => agent.mark,
            None => self
                .selected
                .as_deref()
                .and_then(|id| agent_marks::for_model(None, id)),
        };
        let effort = self
            .effort_index()
            .map(|i| self.effort.levels[i].1.as_str());
        let hint = selection
            .map(|(a, _)| format!("{} · {name}", a.name))
            .unwrap_or_else(|| name.into());
        let hint = effort.map_or_else(|| hint.clone(), |level| format!("{hint} · {level}"));
        let visible_name = if self.selected.is_none() {
            selection
                .map(|(a, _)| format!("{} · {name}", a.name))
                .unwrap_or_else(|| name.to_owned())
        } else {
            name.to_owned()
        };
        let trigger = Button::new("model-picker")
            .custom(
                ButtonCustomVariant::new(cx)
                    .hover(ui::ink(0x0a).into())
                    .active(ui::ink(0x0d).into()),
            )
            .small()
            .h(px(28.))
            .rounded(px(6.))
            .max_w(relative(1.))
            .px(px(6.))
            .min_w_0()
            .disabled(self.disabled && !self.open)
            .accessibility_label("Choose agent and model")
            .tooltip(hint)
            .child(
                row()
                    .min_w_0()
                    .max_w(relative(1.))
                    .gap(px(6.))
                    .child(agent_marks::icon(mark, 14.))
                    .child(
                        text(visible_name)
                            .text_size(px(ui::BODY))
                            .text_color(rgb(ui::theme::color(INK)))
                            .truncate()
                            .min_w_0(),
                    )
                    .when_some(effort.filter(|_| !self.compact), |r, e| {
                        r.child(
                            text(e.to_owned())
                                .flex_none()
                                .text_size(px(ui::BODY))
                                .text_color(rgb(ui::theme::color(MUTED))),
                        )
                    })
                    // The chevron marks the name as a menu, not a label.
                    .child(
                        icon(Glyph::ChevronDown)
                            .flex_none()
                            .size(px(10.))
                            .text_color(rgb(ui::theme::color(MUTED))),
                    ),
            );
        let weak = cx.weak_entity();
        Popover::new("model-menu")
            .trigger_style(StyleRefinement::default().min_w_0().max_w(relative(1.)))
            .anchor(Anchor::BottomLeft)
            .offset(px(6.))
            .appearance(false)
            .open(self.open)
            .track_focus(&self.focus)
            .on_open_change(cx.listener(|this, open, w, cx| this.opened(*open, w, cx)))
            .trigger(trigger)
            .content(move |_, w, cx| {
                weak.update(cx, |this, cx| this.sheet(w, cx))
                    .unwrap_or_else(|_| div().into_any_element())
            })
    }
}
