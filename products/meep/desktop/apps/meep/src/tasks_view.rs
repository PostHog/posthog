//! The Tasks tab, after Linear: a dense list grouped by status by default, a
//! board on request, and Display options for grouping, ordering and which
//! properties show. Tasks are always the agent's. One click opens a task's
//! conversation in the side chat.
use super::details::column_dot;
use super::*;
use chrono::Utc;
use meep_ui::gpui_kit::component::{
    Disableable, Icon, Sizable,
    input::Enter,
    menu::{DropdownMenu, PopupMenu, PopupMenuItem},
    scroll::{Scrollbar, ScrollbarMode},
};
use std::collections::BTreeSet;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub(super) enum Grouping {
    #[default]
    Status,
    Source,
}
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub(super) enum Ordering {
    #[default]
    Updated,
    Created,
    Title,
}
/// How the Tasks tab shows its work, kept on this Mac.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub(super) struct TaskDisplay {
    /// Topics shown as a board; every other topic shows the list.
    pub boards: BTreeSet<TopicId>,
    pub grouping: Grouping,
    pub ordering: Ordering,
    pub show_source: bool,
    pub show_model: bool,
    pub show_date: bool,
}
impl Default for TaskDisplay {
    fn default() -> Self {
        Self {
            boards: BTreeSet::new(),
            grouping: Grouping::Status,
            ordering: Ordering::Updated,
            show_source: true,
            show_model: true,
            show_date: true,
        }
    }
}

/// Linear's order: what needs you first, then running work, then the queue.
pub(super) const STATUS_ORDER: [Column; 4] = [
    Column::NeedsYou,
    Column::InProgress,
    Column::Todo,
    Column::Done,
];

/// How far a task row is indented past its group header's leading edge: the
/// header's chevron, its gap and its status mark, so tasks start under the name.
const TASK_INDENT: f32 = 11. + 10. + 14.;
const TASK_GROUP_HEIGHT: f32 = 34.;
const TASK_ROW_HEIGHT: f32 = 42.;
const TASK_EMPTY_HEIGHT: f32 = 36.;
const TASK_OVERSCAN: f32 = 300.;

/// A board reads left to right, as work moves.
const BOARD_ORDER: [Column; 4] = [
    Column::Todo,
    Column::InProgress,
    Column::NeedsYou,
    Column::Done,
];

/// A status mark drawn like Linear's: an empty ring to do, a ring with a core
/// in progress, a filled ring waiting on you, a filled check when done.
pub(super) fn status_icon(column: Column) -> Div {
    let tone = rgb(column_dot(column));
    let ring = div()
        .flex_none()
        .size(px(14.))
        .rounded_full()
        .border(px(1.5))
        .border_color(tone)
        .flex()
        .items_center()
        .justify_center();
    match column {
        Column::Todo => ring.border_color(rgb(ui::theme::color(ui::TERTIARY))),
        Column::InProgress => ring.child(div().size(px(5.)).rounded_full().bg(tone)),
        Column::NeedsYou => ring.child(div().size(px(7.)).rounded_full().bg(tone)),
        Column::Done => ring.bg(tone).child(
            Icon::new(Glyph::Check)
                .size(px(9.))
                .text_color(rgb(ui::theme::color(ui::CANVAS))),
        ),
    }
}

/// What a task is doing that its column does not say: running, waiting in
/// the queue, or stalled on a run that could not start.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Activity {
    Working,
    Queued,
    Stalled,
}

fn activity(t: &meep_topic::Task) -> Option<Activity> {
    // A run that could not start reads as that, not as its error text.
    let stalled = t.column == Column::NeedsYou
        && t.action.is_none()
        && !t.review_before_start
        && t.assignment != Some(InboxAssignment::Human)
        && t.result.is_some();
    if stalled {
        Some(Activity::Stalled)
    } else if t.column == Column::InProgress {
        Some(Activity::Working)
    } else if t.queued && t.column == Column::Todo {
        Some(Activity::Queued)
    } else {
        None
    }
}

/// The small label for an [`Activity`], as cards and rows show it.
fn activity_badge(a: Activity) -> Div {
    let (tone, mark, label) = match a {
        Activity::Stalled => (
            super::pages::warning(),
            Icon::new(Glyph::TriangleAlert)
                .size(px(11.))
                .text_color(rgb(super::pages::warning()))
                .into_any_element(),
            "Needs attention",
        ),
        Activity::Working => (
            ui::theme::color(ui::SECONDARY),
            div()
                .size(px(6.))
                .rounded_full()
                .bg(rgb(column_dot(Column::InProgress)))
                .into_any_element(),
            "Working",
        ),
        Activity::Queued => (
            ui::theme::color(ui::TERTIARY),
            div().into_any_element(),
            "Queued",
        ),
    };
    ui::row()
        .flex_none()
        .gap(px(5.))
        .text_size(px(11.5))
        .font_weight(FontWeight::MEDIUM)
        .text_color(rgb(tone))
        .child(mark)
        .child(label)
}

/// The model working a task, drawn as a round avatar like an assignee.
fn model_avatar(model: Option<&meep_wire::ChatModel>) -> Div {
    div()
        .flex_none()
        .size(px(20.))
        .rounded_full()
        .border_1()
        .border_color(ui::ink(0x10))
        .flex()
        .items_center()
        .justify_center()
        .child(meep_ui::agent_marks::icon(
            model
                .and_then(|m| m.runtime.as_deref())
                .and_then(meep_ui::agent_marks::named),
            11.,
        ))
}

fn age(t: &meep_topic::Task) -> String {
    super::pages::ago(Utc::now() - t.updated_at)
}

const BOARD_COLUMN: f32 = 180.;
pub(super) const BOARD_PANE: f32 = 4. * BOARD_COLUMN + 3. * 8. + 2. * super::details::PAGE_X;

impl Desktop {
    pub(super) fn task_board(&self, id: TopicId) -> bool {
        self.task_display.boards.contains(&id) && self.board_room.get()
    }
    pub(super) fn set_task_display(
        &mut self,
        f: impl FnOnce(&mut TaskDisplay),
        cx: &mut Context<Self>,
    ) {
        f(&mut self.task_display);
        if let Err(e) = self
            .client()
            .set_preference("task-display", &self.task_display)
        {
            self.fail(e)
        }
        cx.notify()
    }
    pub(super) fn toggle_task_board(&mut self, id: TopicId, cx: &mut Context<Self>) {
        self.set_task_display(
            |d| {
                if !d.boards.remove(&id) {
                    d.boards.insert(id);
                }
            },
            cx,
        )
    }
    fn group_collapsed(&self, key: &str) -> bool {
        let folded_by_default = key == "status-Done" && self.focus_has_open_work();
        folded_by_default != self.toggled_groups.contains(key)
    }
    fn focus_has_open_work(&self) -> bool {
        self.topic_id()
            .and_then(|id| self.states.iter().find(|s| s.topic.id == id))
            .is_none_or(|s| {
                s.tasks
                    .iter()
                    .any(|t| !t.hidden() && t.column != Column::Done)
            })
    }
    /// Tasks in the order the list shows them, grouped.
    pub(super) fn task_groups<'a>(
        &self,
        state: &'a TopicState,
    ) -> Vec<(String, String, Option<Column>, Vec<&'a meep_topic::Task>)> {
        let mut sorted: Vec<&meep_topic::Task> =
            state.tasks.iter().filter(|t| !t.hidden()).collect();
        match self.task_display.ordering {
            Ordering::Updated => sorted.sort_by_key(|t| std::cmp::Reverse(t.updated_at)),
            Ordering::Created => sorted.sort_by_key(|t| std::cmp::Reverse(t.created_at)),
            Ordering::Title => sorted.sort_by_key(|t| t.title.to_lowercase()),
        }
        match self.task_display.grouping {
            Grouping::Status => STATUS_ORDER
                .into_iter()
                .map(|c| {
                    (
                        format!("status-{c:?}"),
                        column_name(c).to_owned(),
                        Some(c),
                        sorted.iter().copied().filter(|t| t.column == c).collect(),
                    )
                })
                .collect(),
            Grouping::Source => {
                let mut groups: Vec<(String, String, Option<Column>, Vec<&meep_topic::Task>)> =
                    vec![];
                let mut indices: std::collections::HashMap<String, usize> =
                    std::collections::HashMap::new();
                for t in sorted {
                    let src = self.task_origin(state, t);
                    if let Some(&index) = indices.get(&src) {
                        groups[index].3.push(t);
                    } else {
                        indices.insert(src.clone(), groups.len());
                        groups.push((format!("source-{src}"), src, None, vec![t]));
                    }
                }
                groups
            }
        }
    }
    /// What j/k walk through: the rows that are drawn, top to bottom.
    pub(super) fn visible_tasks(&self, state: &TopicState) -> Vec<TaskId> {
        if self.task_board(state.topic.id) {
            return BOARD_ORDER
                .into_iter()
                .flat_map(|c| {
                    state
                        .tasks
                        .iter()
                        .filter(move |t| t.column == c && !t.hidden())
                        .map(|t| t.id)
                })
                .collect();
        }
        self.task_groups(state)
            .into_iter()
            .filter(|g| !self.group_collapsed(&g.0))
            .flat_map(|g| g.3.into_iter().map(|t| t.id))
            .collect()
    }
    /// The Tasks tab's bar controls: List or Board, and Display options.
    pub(super) fn tasks_toolbar(&self, id: TopicId, compact: bool, cx: &Context<Self>) -> Div {
        let board = self.task_board(id);
        let toggle = |key: &'static str, glyph: Glyph, label: &'static str, on: bool| {
            div()
                .id(key)
                .role(Role::RadioButton)
                .aria_label(label)
                .aria_selected(on)
                .size(px(26.))
                .rounded(px(6.))
                .flex()
                .items_center()
                .justify_center()
                .cursor_pointer()
                .when(on, |b| b.bg(rgb(ui::theme::color(ui::CANVAS))).shadow_sm())
                .when(!on, |b| b.hover(|s| s.bg(ui::ink(0x08))))
                .child(
                    Icon::new(glyph)
                        .size(px(14.))
                        .text_color(rgb(ui::theme::color(if on {
                            ui::INK
                        } else {
                            ui::SECONDARY
                        }))),
                )
                .on_click(cx.listener(move |s, _, _, cx| {
                    let wants_board = key == "tasks-board";
                    if s.task_board(id) != wants_board && (s.board_room.get() || !wants_board) {
                        s.toggle_task_board(id, cx)
                    }
                }))
        };
        let room = self.board_room.get();
        let owner = cx.entity().downgrade();
        let display = self.task_display.clone();
        let menu = move |m: PopupMenu, _: &mut Window, _: &mut Context<PopupMenu>| {
            let set = |label: &'static str, on: bool, f: fn(&mut TaskDisplay)| {
                let owner = owner.clone();
                PopupMenuItem::new(label)
                    .checked(on)
                    .on_click(move |_, _, cx| {
                        let _ = owner.update(cx, |s, cx| s.set_task_display(f, cx));
                    })
            };
            m.min_w(px(220.))
                .label("Group by")
                .item(set("Status", display.grouping == Grouping::Status, |d| {
                    d.grouping = Grouping::Status
                }))
                .item(set("Source", display.grouping == Grouping::Source, |d| {
                    d.grouping = Grouping::Source
                }))
                .separator()
                .label("Sort by")
                .item(set(
                    "Last updated",
                    display.ordering == Ordering::Updated,
                    |d| d.ordering = Ordering::Updated,
                ))
                .item(set("Created", display.ordering == Ordering::Created, |d| {
                    d.ordering = Ordering::Created
                }))
                .item(set("Title", display.ordering == Ordering::Title, |d| {
                    d.ordering = Ordering::Title
                }))
                .separator()
                .label("Show")
                .item(set("Source", display.show_source, |d| {
                    d.show_source = !d.show_source
                }))
                .item(set("Model", display.show_model, |d| {
                    d.show_model = !d.show_model
                }))
                .item(set("Updated", display.show_date, |d| {
                    d.show_date = !d.show_date
                }))
        };
        // Neither control gives way when the bar is narrow; they keep their size.
        ui::row()
            .flex_none()
            .gap(px(8.))
            .child(
                ui::row()
                    .flex_none()
                    .gap(px(2.))
                    .p(px(2.))
                    .rounded(px(8.))
                    .bg(ui::ink(0x0a))
                    .child(toggle("tasks-list", Glyph::List, "List", !board))
                    .child(
                        toggle("tasks-board", Glyph::Kanban, "Board", board).when(!room, |b| {
                            b.opacity(0.4).tooltip(|w, cx| {
                                meep_ui::gpui_kit::component::tooltip::Tooltip::new(
                                    "Hide the overview or widen the window to see the board",
                                )
                                .build(w, cx)
                            })
                        }),
                    ),
            )
            .child(
                // A tight bar keeps the menu as its icon alone.
                ui::button("tasks-display", if compact { "" } else { "Display" })
                    .small()
                    .flex_none()
                    .icon(Glyph::SlidersHorizontal)
                    .tooltip("Display")
                    .h(px(30.))
                    .px(px(if compact { 8. } else { 10. }))
                    .rounded(px(6.))
                    .border_1()
                    .border_color(ui::ink(0x14))
                    .dropdown_caret(true)
                    .dropdown_menu_with_anchor(gpui::Anchor::TopRight, menu),
            )
    }
    /// The Tasks tab: empty, list or board, with the composer over it.
    pub(super) fn tasks_page(&self, state: &TopicState, w: &Window, cx: &Context<Self>) -> Div {
        let id = state.topic.id;
        let page = if state.tasks.iter().all(|t| t.hidden()) {
            ui::column()
                .size_full()
                .min_h(px(360.))
                .items_center()
                .justify_center()
                .gap(px(12.))
                .child(super::topic_icon::bob(
                    "no-tasks-hog",
                    super::topic_icon::hero("workmaxxing", 112.),
                    cx.reduce_motion(),
                ))
                .child(
                    div()
                        .pt(px(4.))
                        .text_size(px(15.))
                        .font_weight(FontWeight::SEMIBOLD)
                        .child("No tasks yet"),
                )
                .child(ui::caption(
                    "Give the agent something to work on, or queue it for later.",
                ))
                .child(
                    ui::row()
                        .gap(px(8.))
                        .child(control(
                            "add-task",
                            "New task",
                            true,
                            cx,
                            move |s, w, cx| s.begin_task(id, w, cx),
                        ))
                        .child(
                            ui::row()
                                .gap(px(5.))
                                .child(ui::caption("C").px(px(5.)).rounded(px(3.)).bg(ui::ink(16)))
                                .child(ui::caption("to create")),
                        ),
                )
        } else if self.task_board(id) {
            self.task_columns(state, cx)
        } else {
            self.task_list(state, w, cx)
        };
        let _ = w;
        page
    }
    fn open_task(id: TopicId, task: TaskId) -> Page {
        Page::Topic(id, Tab::Tasks, Some(Detail::Task(task)))
    }
    /// Where a task came from, when that says more than "Agent" or "You".
    fn task_source(&self, state: &TopicState, t: &meep_topic::Task) -> Option<String> {
        if !self.task_display.show_source {
            return None;
        }
        let origin = self.task_origin(state, t);
        (!matches!(origin.as_str(), "Agent" | "You")).then_some(origin)
    }
    fn task_model(&self, t: &meep_topic::Task) -> Option<&meep_wire::ChatModel> {
        t.model
            .as_ref()
            .and_then(|m| self.catalogue.models.iter().find(|c| &c.id == m))
    }
    fn start_button(id: TopicId, task: TaskId, cx: &Context<Self>) -> Button {
        control(
            format!("start-{task}"),
            "Start",
            false,
            cx,
            move |s, _, _| {
                s.issue(id, Command::StartTask { task });
            },
        )
        .icon(Glyph::Play)
        .h(px(22.))
        .px(px(7.))
    }
    /// A list row's end, in fixed slots so every row lines up: what it is
    /// doing, the model as an avatar, then how long ago it moved.
    fn task_row_end(&self, state: &TopicState, t: &meep_topic::Task, cx: &Context<Self>) -> Div {
        let d = &self.task_display;
        let model = self.task_model(t);
        let name: SharedString = model.map_or("Agent".into(), |m| m.name.clone().into());
        let act = activity(t);
        ui::row()
            .flex_none()
            .gap(px(12.))
            .when_some(act, |r, a| {
                r.when(a == Activity::Queued, |r| {
                    r.child(Self::start_button(state.topic.id, t.id, cx))
                })
                .child(activity_badge(a))
            })
            .when(d.show_model, |r| {
                r.child(
                    div()
                        .id(SharedString::from(format!("model-{}", t.id)))
                        .child(model_avatar(model))
                        .tooltip(move |w, cx| {
                            meep_ui::gpui_kit::component::tooltip::Tooltip::new(name.clone())
                                .build(w, cx)
                        }),
                )
            })
            .when(d.show_date, |r| {
                r.child(
                    div()
                        .w(px(56.))
                        .text_right()
                        .text_size(px(12.))
                        .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                        .child(age(t)),
                )
            })
    }
    /// A board card, as a work tracker draws one: where it came from and what
    /// it is doing, the title, then who works it and when it last moved.
    fn task_card(&self, state: &TopicState, t: &meep_topic::Task, cx: &Context<Self>) -> Div {
        let d = &self.task_display;
        let tertiary = rgb(ui::theme::color(ui::TERTIARY));
        let model = self.task_model(t);
        let source = self.task_source(state, t);
        let act = activity(t);
        let top = (source.is_some() || act.is_some()).then(|| {
            ui::row()
                .w_full()
                .gap(px(8.))
                .child(
                    div()
                        .flex_1()
                        .min_w_0()
                        .truncate()
                        .text_size(px(12.))
                        .text_color(tertiary)
                        .children(source),
                )
                .children(act.map(activity_badge))
        });
        let worker = d.show_model.then(|| {
            ui::row()
                .flex_1()
                .min_w_0()
                .gap(px(6.))
                .child(model_avatar(model))
                .child(
                    div()
                        .min_w_0()
                        .truncate()
                        .text_size(px(12.5))
                        .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                        .child(model.map_or("Agent".to_owned(), |m| m.name.clone())),
                )
        });
        let when = if act == Some(Activity::Queued) {
            Some(Self::start_button(state.topic.id, t.id, cx).into_any_element())
        } else {
            d.show_date.then(|| {
                div()
                    .flex_none()
                    .text_size(px(12.))
                    .text_color(tertiary)
                    .child(age(t))
                    .into_any_element()
            })
        };
        let bottom = (worker.is_some() || when.is_some()).then(|| {
            ui::row()
                .w_full()
                .pt(px(2.))
                .gap(px(8.))
                .children(worker)
                .when(!d.show_model, |r| r.child(div().flex_1()))
                .children(when)
        });
        ui::column()
            .w_full()
            .gap(px(6.))
            .children(top)
            .child(
                div()
                    .w_full()
                    .text_size(px(14.))
                    .font_weight(FontWeight::MEDIUM)
                    .line_height(relative(1.4))
                    .line_clamp(2)
                    .text_ellipsis()
                    .overflow_hidden()
                    .child(meep_topic::title_line(&t.title)),
            )
            .children(bottom)
    }
    fn task_list(&self, state: &TopicState, w: &Window, cx: &Context<Self>) -> Div {
        let id = state.topic.id;
        let mut list = ui::column().gap_0().mx(px(-29.));
        // Keep off-screen rows out of the element tree, but preserve their
        // height so the existing scroll handle and keyboard reveal still work.
        // Accessibility and drag operations need the complete set of targets.
        let virtualize = !w.is_a11y_active() && !cx.has_active_drag();
        let top = (-f32::from(self.content_scroll.offset().y)).max(0.);
        let height = f32::from(self.content_scroll.bounds().size.height)
            .max(f32::from(w.viewport_size().height));
        let low = (top - TASK_OVERSCAN).max(0.);
        let high = top + height + TASK_OVERSCAN;
        let mut y = 0_f32;
        for (key, name, column, tasks) in self.task_groups(state) {
            if tasks.is_empty() && column.is_none_or(|c| !matches!(c, Column::Todo)) {
                continue;
            }
            let collapsed = self.group_collapsed(&key);
            let toggle = key.clone();
            let add = column.filter(|c| matches!(c, Column::Todo | Column::InProgress));
            list = list.child(
                ui::row()
                    .id(SharedString::from(format!("group-{key}")))
                    .h(px(TASK_GROUP_HEIGHT))
                    .px(px(24.))
                    .gap(px(10.))
                    // A quiet label with a rule under it, like every other list's
                    // section label, so a header never reads as one more task.
                    .border_b_1()
                    .border_color(ui::ink(0x0d))
                    .cursor_pointer()
                    .child(
                        Icon::new(Glyph::ChevronRight)
                            .size(px(11.))
                            .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                            .rotate(meep_ui::gpui_kit::radians(if collapsed {
                                0.
                            } else {
                                std::f32::consts::FRAC_PI_2
                            })),
                    )
                    .children(column.map(status_icon))
                    .child(
                        div()
                            .font_weight(FontWeight::SEMIBOLD)
                            .text_size(px(13.))
                            .child(name),
                    )
                    .child(
                        div()
                            .text_size(px(12.))
                            .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                            .child(tasks.len().to_string()),
                    )
                    .child(div().flex_1())
                    .when_some(add, |r, c| {
                        r.child(
                            ui::icon_button(
                                SharedString::from(if c == Column::Todo {
                                    "add-task".to_owned()
                                } else {
                                    "add-task-running".to_owned()
                                }),
                                Glyph::Plus,
                                "New task",
                            )
                            .on_click(cx.listener(
                                move |s, _, w, cx| {
                                    cx.stop_propagation();
                                    s.begin_task(id, w, cx);
                                    s.task_for_agent = c == Column::InProgress;
                                },
                            )),
                        )
                    })
                    .on_click(cx.listener(move |s, _, _, cx| {
                        if !s.toggled_groups.remove(&toggle) {
                            s.toggled_groups.insert(toggle.clone());
                        }
                        let open = !s.group_collapsed(&toggle);
                        s.folds
                            .toggled(format!("task-group-{id}-{toggle}"), open, cx);
                        cx.notify()
                    })),
            );
            y += TASK_GROUP_HEIGHT;
            let fold = format!("task-group-{id}-{key}");
            if collapsed && self.folds.progress(&fold, false, cx) <= 0. {
                continue;
            }
            let mut body = ui::column().gap_0();
            if tasks.is_empty() {
                y += TASK_EMPTY_HEIGHT;
                body = body.child(
                    div()
                        .h(px(TASK_EMPTY_HEIGHT))
                        .pl(px(24. + TASK_INDENT + 10.))
                        .flex()
                        .items_center()
                        .border_b_1()
                        .border_color(ui::ink(0x08))
                        .child(ui::caption("Nothing queued")),
                );
            }
            let mut skipped = 0_usize;
            for t in tasks {
                let dest = Self::open_task(id, t.id);
                let selected = self.page == dest;
                let row_y = y;
                y += TASK_ROW_HEIGHT;
                if virtualize && !selected && (row_y + TASK_ROW_HEIGHT < low || row_y > high) {
                    skipped += 1;
                    continue;
                }
                if skipped > 0 {
                    body = body.child(div().h(px(TASK_ROW_HEIGHT * skipped as f32)).flex_none());
                    skipped = 0;
                }
                let row = line(format!("card-{}", t.id), selected)
                    .when(selected, |r| r.track_scroll(&self.selection_bounds))
                    .h(px(TASK_ROW_HEIGHT))
                    .px(px(24.))
                    .gap(px(10.))
                    .rounded_none()
                    .border_b_1()
                    .border_color(ui::ink(0x08))
                    // Tasks sit one step in from their group: each status mark
                    // lines up under the group's name, not its mark.
                    .child(div().w(px(TASK_INDENT)).flex_none())
                    .child(status_icon(t.column))
                    .child(
                        // The title keeps its room; the source after it gives
                        // way first.
                        ui::row()
                            .flex_1()
                            .min_w_0()
                            .gap(px(10.))
                            .child(
                                div()
                                    .flex_shrink(1.)
                                    .min_w_0()
                                    .truncate()
                                    .text_size(px(13.5))
                                    .font_weight(FontWeight::MEDIUM)
                                    .child(meep_topic::title_line(&t.title)),
                            )
                            .children(self.task_source(state, t).map(|src| {
                                div()
                                    .flex_shrink(4.)
                                    .min_w_0()
                                    .max_w(px(160.))
                                    .truncate()
                                    .text_size(px(12.5))
                                    .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                                    .child(src)
                            })),
                    )
                    .child(self.task_row_end(state, t, cx))
                    .on_click(cx.listener(move |s, _, w, cx| s.go(dest.clone(), w, cx)));
                body = body.child(self.task_drag(row, id, t));
            }
            if skipped > 0 {
                body = body.child(div().h(px(TASK_ROW_HEIGHT * skipped as f32)).flex_none());
            }
            list = list.children(
                self.folds
                    .reveal(&fold, !collapsed, cx, || body.into_any_element()),
            );
        }
        list
    }
    fn task_columns(&self, state: &TopicState, cx: &Context<Self>) -> Div {
        let id = state.topic.id;
        let mut board = ui::row()
            .items_stretch()
            .gap(px(10.))
            .min_h_full()
            .flex_none();
        for c in BOARD_ORDER {
            let cards: Vec<_> = state
                .tasks
                .iter()
                .filter(|t| t.column == c && !t.hidden())
                .collect();
            let mut heading = ui::row()
                .h(px(30.))
                .px(px(6.))
                .gap(px(8.))
                .child(status_icon(c))
                .child(
                    div()
                        .text_size(px(13.))
                        .font_weight(FontWeight::SEMIBOLD)
                        .child(column_name(c)),
                )
                .child(
                    div()
                        .text_size(px(12.))
                        .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                        .child(cards.len().to_string()),
                )
                .child(div().flex_1());
            if matches!(c, Column::Todo | Column::InProgress) {
                heading = heading.child(
                    ui::icon_button(
                        SharedString::from(if c == Column::Todo {
                            "add-task".to_owned()
                        } else {
                            "add-task-running".to_owned()
                        }),
                        Glyph::Plus,
                        "New task",
                    )
                    .on_click(cx.listener(move |s, _, w, cx| {
                        s.begin_task(id, w, cx);
                        s.task_for_agent = c == Column::InProgress;
                    })),
                )
            }
            let mut col = ui::column()
                .id(format!("column-{c:?}"))
                .gap(px(8.))
                .min_w(px(BOARD_COLUMN))
                .max_w(px(340.))
                .flex_1()
                .flex_shrink_0()
                .rounded(px(12.))
                .bg(ui::ink(0x04))
                .p(px(8.))
                .child(heading);
            if cards.is_empty() {
                col = col.child(
                    ui::caption(match c {
                        Column::Todo => "Nothing queued",
                        Column::InProgress => "Nothing running",
                        Column::NeedsYou => "Nothing waiting on you",
                        Column::Done => "Nothing finished yet",
                    })
                    .text_size(px(12.))
                    .px(px(8.))
                    .py(px(4.)),
                );
            }
            for t in cards {
                let dest = Self::open_task(id, t.id);
                let selected = self.page == dest;
                let card = line(format!("card-{}", t.id), selected)
                    .when(selected, |r| r.track_scroll(&self.selection_bounds))
                    .flex_none()
                    .px(px(12.))
                    .py(px(10.))
                    .rounded(px(10.))
                    .bg(rgb(ui::theme::color(ui::CANVAS)))
                    .border_1()
                    .border_color(if selected {
                        ui::ink(0x40)
                    } else {
                        ui::ink(0x10)
                    })
                    .shadow(vec![BoxShadow {
                        color: rgba(0x00000008).into(),
                        offset: point(px(0.), px(1.)),
                        blur_radius: px(2.),
                        spread_radius: px(0.),
                        inset: false,
                    }])
                    .child(self.task_card(state, t, cx))
                    .on_click(cx.listener(move |s, _, w, cx| s.go(dest.clone(), w, cx)));
                col = col.child(self.task_drag(card, id, t));
            }
            board = board.child(self.task_drop(col, id, c, cx));
        }
        // The board takes the pane's width and scrolls sideways when its columns
        // need more, so a narrow pane never cuts a column off.
        ui::column()
            .relative()
            .w_full()
            .min_h_full()
            .child(
                board
                    .id("columns")
                    .w_full()
                    .track_scroll(&self.board_scroll)
                    .overflow_x_scroll(),
            )
            .child(
                div().absolute().inset_0().child(
                    Scrollbar::horizontal(&self.board_scroll)
                        .id("task-board-scrollbar")
                        .mode(ScrollbarMode::Always)
                        .viewport_from_layout(),
                ),
            )
    }
    /// The task composer, over the list: what to do, the model and effort,
    /// Codex billing when a Codex model is chosen, then Queue or Start.
    pub(super) fn task_composer(&self, w: &Window, cx: &Context<Self>) -> AnyElement {
        let empty = self.task_description.read(cx).value().trim().is_empty();
        let chosen = self.chosen_task_model();
        let codex = chosen.is_some_and(|m| m.runtime.as_deref() == Some("codex"));
        let me = cx.entity().downgrade();
        let own = self.billing.as_deref() == Some("own-subscription");
        let billing = codex.then(|| {
            meep_shell::settings::segmented(
                "task-billing",
                &["PostHog", "ChatGPT subscription"],
                Some(own as usize),
                move |i, _, cx| {
                    let _ = me.update(cx, |s, cx| {
                        s.billing = Some(
                            if i == 1 {
                                "own-subscription"
                            } else {
                                "posthog-gateway"
                            }
                            .into(),
                        );
                        cx.notify()
                    });
                },
            )
        });
        let note = chosen
            .filter(|m| !m.meep_tools)
            .map(|_| "Runs without Meep tools: it can’t read the topic or propose actions.");
        let focused = self
            .task_description
            .focus_handle(cx)
            .contains_focused(w, cx);
        let card = ui::column()
            .id("new-task-composer")
            // Files dropped on the form upload into the topic and attach to the task.
            .drag_over::<ExternalPaths>(|style, _, _, _| style.border_color(ui::ink(0x48)))
            .on_drop(cx.listener(|s, paths: &ExternalPaths, w, cx| {
                s.upload_chat_files(paths.paths().to_vec(), w, cx)
            }))
            // ↵ starts it; ⇧↵ breaks the line; ⌘↵ is handled with the other shortcuts.
            .on_action(cx.listener(|s, action: &Enter, w, cx| {
                if !action.shift && !action.secondary {
                    s.task_for_agent = true;
                    s.submit(w, cx)
                }
            }))
            .w(px(620.))
            .max_w(relative(0.92))
            .rounded(px(12.))
            .bg(rgb(ui::theme::color(ui::CANVAS)))
            .border_1()
            .border_color(ui::ink(if focused { 0x1c } else { 0x12 }))
            .shadow_lg()
            .occlude()
            .child(
                ui::row()
                    .px(px(16.))
                    .pt(px(12.))
                    .gap(px(8.))
                    .child(status_icon(Column::Todo))
                    .child(ui::caption("New task").font_weight(FontWeight::MEDIUM))
                    .child(div().flex_1())
                    .child(ui::icon_button("cancel-task", Glyph::X, "Close").on_click(
                        cx.listener(|s, _, w, cx| {
                            s.adding = false;
                            s.focus.focus(w, cx);
                            cx.notify()
                        }),
                    )),
            )
            .child(
                ui::column().px(px(16.)).pt(px(6.)).gap(px(4.)).child(
                    meep_shell::composer::input(&self.task_description, "Task brief")
                        .text_size(px(15.))
                        .min_h(px(72.)),
                ),
            )
            .when_some(note, |c, n| c.child(ui::caption(n).px(px(16.)).pb(px(6.))))
            // Attached files, as in the chat composer.
            .when(
                !self.task_files.is_empty() || self.chat_uploading > 0,
                |c| {
                    c.child(div().px(px(16.)).pb(px(8.)).child(self.file_chips(
                        &self.task_files,
                        super::details::Attach::Task,
                        cx,
                    )))
                },
            )
            .child(
                ui::row()
                    .px(px(12.))
                    .py(px(10.))
                    .gap(px(8.))
                    .border_t_1()
                    .border_color(ui::ink(0x0c))
                    .child(
                        ui::icon_button("attach-task-files", Glyph::Paperclip, "Attach files")
                            .tooltip("Attach files · saved to this topic’s Files")
                            .on_click(cx.listener(|s, _, w, cx| s.choose_chat_files(w, cx))),
                    )
                    .child(self.task_models.clone())
                    .children(billing)
                    .child(div().flex_1())
                    .child(
                        control("queue-task", "Queue", false, cx, |s, w, cx| {
                            s.task_for_agent = false;
                            s.submit(w, cx)
                        })
                        .disabled(empty)
                        .tooltip("Add to To do without starting"),
                    )
                    .child(
                        control(
                            "save-task",
                            format!("Start  {}", super::shortcuts::SEND_LATER.label()),
                            true,
                            cx,
                            |s, w, cx| {
                                s.task_for_agent = true;
                                s.submit(w, cx)
                            },
                        )
                        .disabled(empty || self.chat_uploading > 0),
                    ),
            );
        div()
            .absolute()
            .inset_0()
            .bg(rgba(0x00000024))
            .flex()
            .items_start()
            .justify_center()
            .pt(relative(0.12))
            .child(card)
            .into_any_element()
    }
}
