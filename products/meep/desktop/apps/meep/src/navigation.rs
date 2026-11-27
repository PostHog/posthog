use super::*;
use meep_ui::gpui_kit::component::input::Enter;
use meep_ui::gpui_kit::component::{Disableable, Icon, Sizable, input::Textarea};

pub(super) const TOPIC_SIDEBAR_WIDTH: f32 = 276.;
const TOPIC_ROW_HEIGHT: f32 = 52.;
const TOPIC_ROW_RADIUS: f32 = 10.;
const TOPIC_ROW_TRAILING: f32 = 8.;
const TOPIC_TILE: f32 = 34.;
const SEARCH_ICON: f32 = 20.;
const TOPIC_ROW_GAP: f32 = 4.;

fn tall_row(key: &str) -> bool {
    key.starts_with("topic:") || key.starts_with("view:")
}

fn row_gap(key: &str) -> f32 {
    if tall_row(key) {
        TOPIC_ROW_GAP
    } else {
        ui::nav::GAP
    }
}

pub(super) struct TopicPreview {
    at: chrono::DateTime<chrono::Utc>,
    text: SharedString,
}

impl TopicPreview {
    pub(super) fn new(state: &TopicState) -> Self {
        let messages = state
            .threads
            .iter()
            .filter(|thread| {
                !thread.source_material && !state.archived_threads.contains(&thread.id)
            })
            .flat_map(|thread| {
                thread
                    .messages
                    .iter()
                    .map(|message| (message.at, message.text.as_str()))
            });
        let results = state
            .tasks
            .iter()
            .filter_map(|task| task.result.as_deref().map(|text| (task.updated_at, text)));
        let latest = messages
            .chain(results)
            .filter(|(_, text)| !text.trim().is_empty())
            .max_by_key(|(at, _)| *at);
        let (at, preview) = latest.unwrap_or((state.topic.created_at, ""));
        Self {
            at,
            text: super::pages::plain_line(preview).into(),
        }
    }
}

fn row_date(at: chrono::DateTime<chrono::Utc>) -> String {
    let at = at.with_timezone(&chrono::Local);
    match (chrono::Local::now().date_naive() - at.date_naive()).num_days() {
        0 => at.format("%H:%M").to_string(),
        1 => "Yesterday".to_owned(),
        2..=6 => at.format("%a").to_string(),
        _ => at.format("%b %-d").to_string(),
    }
}

fn view_tile(v: &meep_wire::views::View) -> Div {
    div()
        .flex_none()
        .size(px(TOPIC_TILE))
        .flex()
        .items_center()
        .justify_center()
        .child(meep_shell::icons::window(&v.icon, &v.color, TOPIC_TILE))
}

fn view_row_text(v: &meep_wire::views::View, group: &SharedString) -> Div {
    let latest = v.turns.last();
    let line = latest.map(|t| match t.stage.finished() {
        true => super::pages::plain_line(&t.prompt),
        false => super::views::progress(&t.stage),
    });
    let at = latest
        .map(|t| t.at)
        .into_iter()
        .chain(v.revisions.last().map(|r| r.at))
        .max();
    ui::column()
        .flex_1()
        .gap(px(1.))
        .child(
            ui::row()
                .gap(px(6.))
                .child(
                    ui::nav::title(v.title.clone())
                        .text_size(px(15.))
                        .line_height(px(20.)),
                )
                .children(at.map(|at| {
                    ui::caption(row_date(at))
                        .flex_none()
                        .relative()
                        .top(px(1.))
                        .text_size(px(12.))
                        .line_height(px(20.))
                        .group_hover(group.clone(), |style| style.opacity(0.))
                })),
        )
        .children(line.map(|text| {
            ui::row().gap(px(5.)).min_w_0().child(
                ui::caption(text)
                    .flex_1()
                    .min_w_0()
                    .truncate()
                    .text_size(px(13.))
                    .line_height(px(18.)),
            )
        }))
}

fn topic_row_text(state: &TopicState, preview: &TopicPreview, group: &SharedString) -> Div {
    let date = row_date(preview.at);

    ui::column()
        .flex_1()
        .gap(px(1.))
        .child(
            ui::row()
                .gap(px(6.))
                .child(
                    ui::nav::title(state.topic.name.clone())
                        .text_size(px(15.))
                        .line_height(px(20.)),
                )
                .child(
                    ui::caption(date)
                        .flex_none()
                        .relative()
                        .top(px(1.))
                        .text_size(px(12.))
                        .line_height(px(20.))
                        .group_hover(group.clone(), |style| style.opacity(0.)),
                ),
        )
        .when(!preview.text.is_empty(), |column| {
            column.child(
                ui::caption(preview.text.clone())
                    .truncate()
                    .text_size(px(13.))
                    .line_height(px(18.)),
            )
        })
}

#[cfg(test)]
mod preview_tests {
    use super::TopicPreview;
    use crate::{Message, MessageId, Producer, ThreadId, Topic, TopicId, TopicState};
    use chrono::Utc;
    use uuid::Uuid;

    #[test]
    fn preview_follows_the_latest_visible_message() {
        let now = chrono::DateTime::parse_from_rfc3339("2026-01-05T10:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let mut state = TopicState::new(Topic::new(TopicId(Uuid::from_u128(1)), "Topic", now));
        let first = ThreadId(Uuid::from_u128(2));
        let second = ThreadId(Uuid::from_u128(3));
        for (i, text, thread) in [(0, "First", first), (1, "**Second**", second)] {
            let at = now + chrono::Duration::minutes(i);
            state
                .receive(
                    Message {
                        id: MessageId(Uuid::from_u128(10 + i as u128)),
                        producer: Producer::User,
                        origin: None,
                        author: "Person".into(),
                        at,
                        text: text.into(),
                        external_id: None,
                    },
                    format!("thread-{i}"),
                    thread,
                    at,
                )
                .unwrap();
        }
        assert_eq!(TopicPreview::new(&state).text, "Second");
        state.archived_threads.insert(second);
        assert_eq!(TopicPreview::new(&state).text, "First");
    }
}

impl Desktop {
    /// New routine, in the New view pattern: describe it, or start from a template.
    pub(super) fn routine_page(&self, w: &Window, cx: &Context<Self>) -> Div {
        let send = |s: &mut Self, w: &mut Window, cx: &mut Context<Self>| {
            let prompt = s.routine_prompt.read(cx).value().trim().to_owned();
            if prompt.is_empty() || s.creating_template.is_some() {
                return;
            }
            // An untouched template builds its own workflow; anything else goes to the agent.
            let template = s.routine_template.clone().filter(|t| {
                matches!(&s.templates, Some(Ok(list))
                    if list.iter().any(|x| &x.id == t && x.description.trim() == prompt))
            });
            if let Some(t) = template {
                s.add_template(t, w, cx);
                return;
            }
            s.new_routine = false;
            s.routine_template = None;
            s.ask_in_chat(
                &format!("Create a PostHog workflow for this topic: {prompt}"),
                w,
                cx,
            );
            s.send_chat(w, cx);
            s.routine_prompt.update(cx, |e, cx| e.set_value("", w, cx));
        };
        let busy = self.creating_template.is_some();
        let empty = self.routine_prompt.read(cx).value().trim().is_empty();
        let field = meep_shell::composer::surface(
            self.routine_prompt.focus_handle(cx).contains_focused(w, cx),
        )
        .id("routine-composer")
        .on_action(cx.listener(move |s, action: &Enter, w, cx| {
            if !action.shift {
                send(s, w, cx)
            }
        }))
        .child(
            meep_shell::composer::input(
                &self.routine_prompt,
                "Describe the routine, and when it should run…",
            )
            .min_h(px(80.)),
        )
        .child(
            ui::row().justify_end().child(
                control(
                    "create-routine",
                    if busy { "Creating…" } else { "Create" },
                    true,
                    cx,
                    send,
                )
                .disabled(empty || busy),
            ),
        );
        let mut ideas = vec![];
        match &self.templates {
            Some(Ok(items)) => {
                for t in items {
                    let glyph = match t.id.as_str() {
                        "sort-inbox" => Glyph::Inbox,
                        "urgent-only" => Glyph::Zap,
                        "scout" => Glyph::Search,
                        "daily-brief" => Glyph::FileText,
                        "weekly-goals" => Glyph::Flag,
                        "digest-then-drop" => Glyph::Archive,
                        _ => Glyph::Workflow,
                    };
                    let (tid, prompt) = (t.id.clone(), t.description.clone());
                    ideas.push(
                        div()
                            .id(SharedString::from(format!("template-{}", t.id)))
                            .role(Role::Button)
                            .aria_label(t.name.clone())
                            .flex()
                            .items_start()
                            .gap(px(10.))
                            .px(px(10.))
                            .py(px(6.))
                            .rounded(px(8.))
                            .cursor_pointer()
                            .hover(|s| s.bg(ui::ink(0x0a)))
                            // The name sits on the glyph's line; what it does reads under it.
                            .child(div().pt(px(3.)).child(ui::nav::glyph(glyph, false)))
                            .child(
                                ui::column()
                                    .flex_1()
                                    .min_w_0()
                                    .gap_0()
                                    .child(
                                        div()
                                            .text_size(px(ui::BODY))
                                            .text_color(rgb(ui::theme::color(ui::INK)))
                                            .child(t.name.clone()),
                                    )
                                    .child(
                                        div()
                                            .text_size(px(12.))
                                            .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                                            .child(t.description.clone()),
                                    ),
                            )
                            .on_click(cx.listener(move |s, _, w, cx| {
                                s.routine_template = Some(tid.clone());
                                s.routine_prompt.update(cx, |e, cx| {
                                    e.set_value(prompt.clone(), w, cx);
                                    e.focus(w, cx)
                                });
                                cx.notify()
                            }))
                            .into_any_element(),
                    );
                }
            }
            Some(Err(e)) => ideas.push(ui::caption(e.clone()).px(px(10.)).into_any_element()),
            None => ideas.push(
                ui::caption("Loading templates…")
                    .px(px(10.))
                    .into_any_element(),
            ),
        }
        let link = div()
            .id("routine-bind")
            .role(Role::Button)
            .cursor_pointer()
            .text_size(px(12.))
            .text_color(rgb(ui::theme::color(ui::SECONDARY)))
            .hover(|s| s.text_color(rgb(ui::theme::color(ui::INK))))
            .child("Use an existing PostHog workflow →")
            .on_click(cx.listener(|s, _, w, cx| s.open_sheet(Sheet::Bind, w, cx)));
        creation_page(
            Creation {
                glyph: Glyph::Workflow,
                id: "routine-heading",
                title: "New routine",
                intro: "A PostHog workflow that runs on a schedule or when something arrives.",
                hint: Some(
                    div()
                        .child("The agent builds it and asks before it runs.")
                        .into_any_element(),
                ),
                cancel: true,
                ideas_label: "Or start from a template",
                ideas,
                footer: Some(link.into_any_element()),
            },
            field,
        )
    }

    pub(super) fn save_file_revision(
        &self,
        topic: TopicId,
        original: &str,
        revision: u64,
        w: &Window,
        cx: &mut Context<Self>,
    ) {
        let name = std::path::Path::new(original)
            .file_name()
            .unwrap_or_default()
            .to_string_lossy();
        let directory = dirs::download_dir()
            .or_else(dirs::home_dir)
            .unwrap_or_else(std::env::temp_dir);
        let selection =
            cx.prompt_for_new_path(&directory, Some(&format!("revision-{revision}-{name}")));
        let original = original.to_owned();
        let client = self.client().clone();
        self.job(
            async move {
                let Some(path) = selection.await?? else {
                    return Ok(());
                };
                let file = client.get_file_at(topic, &original, revision).await?;
                tokio::task::spawn_blocking(move || -> Result<()> {
                    use std::io::Write;
                    let directory = path
                        .parent()
                        .ok_or_else(|| anyhow::anyhow!("Missing destination folder"))?;
                    let mut tmp = tempfile::NamedTempFile::new_in(directory)?;
                    tmp.write_all(&file.bytes)?;
                    tmp.as_file().sync_all()?;
                    tmp.persist(path)?;
                    Ok(())
                })
                .await?
            },
            w,
            cx,
            |s, result, _, _| {
                if let Err(error) = result {
                    s.fail(error);
                }
            },
        );
    }

    fn save_rejected_file(
        &self,
        id: meep_topic::CommandId,
        original: &str,
        w: &Window,
        cx: &mut Context<Self>,
    ) {
        let filename = std::path::Path::new(original)
            .file_name()
            .and_then(|n| n.to_str());
        let directory = dirs::download_dir()
            .or_else(dirs::home_dir)
            .unwrap_or_else(std::env::temp_dir);
        let selection = cx.prompt_for_new_path(&directory, filename);
        let client = self.client().clone();
        self.job(
            async move {
                let Some(path) = selection.await?? else {
                    return Ok(());
                };
                tokio::task::spawn_blocking(move || -> Result<()> {
                    use std::io::Write;
                    let directory = path
                        .parent()
                        .ok_or_else(|| anyhow::anyhow!("Missing destination folder"))?;
                    let mut file = tempfile::NamedTempFile::new_in(directory)?;
                    file.write_all(&client.rejected_file_bytes(id)?)?;
                    file.as_file().sync_all()?;
                    file.persist(path)?;
                    client.dismiss_rejection(id)
                })
                .await?
            },
            w,
            cx,
            |s, result, _, _| {
                if let Err(error) = result {
                    s.fail(error);
                }
            },
        );
    }
}

#[derive(Clone)]
enum Drag {
    /// A sidebar section, by its header.
    Section(Uuid),
    /// A topic or view row, by its layout key.
    Item(String),
    Task(TopicId, TaskId),
}
pub(super) struct DragLabel(String);
impl Render for DragLabel {
    fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
        ui::column()
            .p(px(8.))
            .rounded(px(6.))
            .bg(rgb(ui::theme::color(ui::CANVAS)))
            .child(self.0.clone())
    }
}

impl Desktop {
    /// A page header with a back control when navigation history is available.
    pub(super) fn header_row(&self, cx: &Context<Self>) -> Div {
        ui::row().when(!self.back.is_empty(), |row| {
            row.child(
                ui::icon_button("back", Glyph::ArrowLeft, "Back").on_click(cx.listener(
                    |s, _, w, cx| {
                        if let Some(p) = s.back.pop() {
                            s.navigate(p, w, cx);
                        }
                    },
                )),
            )
        })
    }
    fn key(&mut self, e: &KeyDownEvent, w: &mut Window, cx: &mut Context<Self>) {
        if self.renaming_section.is_some() {
            if e.keystroke.key == "escape" {
                self.finish_section_rename(false, w, cx);
                cx.stop_propagation();
            }
            return;
        }
        let k = &e.keystroke;
        let key = k.key.as_str();
        let cmd = k.modifiers.platform;
        let typing = self.views.prompt.focus_handle(cx).contains_focused(w, cx)
            || self
                .views
                .emoji_query
                .focus_handle(cx)
                .contains_focused(w, cx)
            || self.name.focus_handle(cx).contains_focused(w, cx)
            || self.search.focus_handle(cx).contains_focused(w, cx)
            || self.mission_edit.focus_handle(cx).contains_focused(w, cx)
            || self.mission.focus_handle(cx).contains_focused(w, cx)
            || self.note.focus_handle(cx).contains_focused(w, cx)
            || self.run_input.focus_handle(cx).contains_focused(w, cx)
            || self.routine_prompt.focus_handle(cx).contains_focused(w, cx)
            || self
                .task_description
                .focus_handle(cx)
                .contains_focused(w, cx)
            || self.draft.focus_handle(cx).contains_focused(w, cx)
            || self.composer.focus_handle(cx).contains_focused(w, cx);
        match (cmd, key) {
            _ if shortcuts::SEARCH.matches(k) && self.identity.is_some() => {
                self.open_sheet(Sheet::Search, w, cx)
            }
            _ if shortcuts::SEND_LATER.matches(k) && self.adding && self.sheet.is_none() => {
                self.task_for_agent = true;
                self.submit(w, cx)
            }
            _ if shortcuts::TASK_BOARD.matches(k) => {
                if let Page::Topic(id, Tab::Tasks, _) = self.page {
                    self.toggle_task_board(id, cx)
                }
            }
            _ if shortcuts::NEW_TASK.matches(k)
                && !typing
                && self.sheet.is_none()
                && !self.adding
                && matches!(self.page, Page::Topic(_, Tab::Tasks, _)) =>
            {
                if let Page::Topic(id, ..) = self.page {
                    self.begin_task(id, w, cx)
                }
            }
            _ if shortcuts::NEW_TOPIC.matches(k) => self.open_sheet(Sheet::New, w, cx),
            _ if shortcuts::SETTINGS.matches(k) => self.go(Page::Settings, w, cx),
            _ if shortcuts::OVERVIEW.matches(k) => {
                if let Page::Topic(id, ..) = self.page {
                    self.toggle_overview(id, w)
                }
            }
            _ if shortcuts::TOGGLE_SIDEBAR.matches(k) && self.page != Page::Settings => {
                self.sidebar_hidden = !self.sidebar_hidden;
            }
            _ if shortcuts::GO_BACK.matches(k) => {
                if let Some(p) = self.back.pop() {
                    self.navigate(p, w, cx)
                }
            }
            (false, "escape") => {
                if matches!(self.page, Page::View(_))
                    && (self.views.settings || self.views.panel)
                    && self.sheet.is_none()
                {
                    if self.views.settings {
                        self.views.settings = false;
                    } else {
                        self.views.panel = false;
                    }
                    self.focus.focus(w, cx);
                } else if matches!(self.page, Page::NewView | Page::Settings)
                    && self.sheet.is_none()
                {
                    let page = self.back.pop().unwrap_or(Page::Needs);
                    self.navigate(page, w, cx);
                } else if self.menu {
                    self.menu = false;
                } else if self.sheet.is_some() {
                    self.dismiss_sheet(w, cx);
                } else if self.send_back {
                    self.send_back = false;
                    self.focus.focus(w, cx);
                } else if self.adding {
                    self.adding = false;
                    self.focus.focus(w, cx);
                } else if self.new_routine {
                    self.new_routine = false;
                    self.focus.focus(w, cx);
                } else if self.editing {
                    self.editing = false;
                    self.focus.focus(w, cx);
                } else if self.draft.focus_handle(cx).contains_focused(w, cx) {
                    self.focus.focus(w, cx);
                } else if matches!(self.page, Page::Topic(..)) {
                    self.up(w, cx);
                }
            }
            (false, "up" | "down") if self.sheet == Some(Sheet::Search) => {
                self.search_index = if key == "up" {
                    self.search_index.saturating_sub(1)
                } else {
                    (self.search_index + 1).min(self.hits(cx).len().saturating_sub(1))
                };
                self.search_scroll.scroll_to_item(self.search_index);
            }
            (false, "enter")
                if (self.sheet.is_some() || self.adding)
                    && !self.mission.focus_handle(cx).contains_focused(w, cx) =>
            {
                self.submit(w, cx)
            }
            (false, "j" | "k" | "up" | "down")
                if self.page != Page::Settings
                    && self.identity.is_some()
                    && !typing
                    && self.sheet.is_none()
                    && !self.menu =>
            {
                self.step(matches!(key, "j" | "down"), w, cx)
            }
            _ => return,
        }
        cx.stop_propagation();
        w.prevent_default();
        cx.notify()
    }
    fn dismiss_sheet(&mut self, w: &mut Window, cx: &mut Context<Self>) {
        self.sheet = None;
        self.sheet_return_focus
            .take()
            .unwrap_or_else(|| self.focus.clone())
            .focus(w, cx);
    }
    fn step(&mut self, forward: bool, w: &mut Window, cx: &mut Context<Self>) {
        let pages = self.list_pages();
        let next = pages
            .iter()
            .position(|p| p == &self.page)
            .map(|i| {
                if forward {
                    (i + 1).min(pages.len() - 1)
                } else {
                    i.saturating_sub(1)
                }
            })
            .unwrap_or(0);
        if let Some(p) = pages.get(next)
            && *p != self.page
        {
            if matches!(self.page, Page::Topic(_, _, Some(_))) {
                self.navigate(p.clone(), w, cx);
            } else {
                self.go(p.clone(), w, cx);
            }
            self.reveal_selection = matches!(
                p,
                Page::Topic(_, Tab::Inbox | Tab::Tasks | Tab::Routines, _)
            );
        }
    }
    fn list_pages(&self) -> Vec<Page> {
        match &self.page {
            Page::Topic(id, tab, _) => self
                .states
                .iter()
                .find(|s| s.topic.id == *id)
                .map(|s| {
                    let details: Vec<_> = match tab {
                        Tab::Inbox => super::pages::ordered_threads(s, self.skipped)
                            .into_iter()
                            .map(|t| Detail::Thread(t.id))
                            .collect(),
                        Tab::Tasks => self
                            .visible_tasks(s)
                            .into_iter()
                            .map(Detail::Task)
                            .collect(),
                        Tab::Routines => s
                            .scouts
                            .iter()
                            .map(|scout| Detail::Scout(scout.id))
                            .chain(
                                s.topic
                                    .routines
                                    .iter()
                                    .filter(|r| r.binding.backend == "posthog")
                                    .map(|r| Detail::Routine(r.binding.id.clone())),
                            )
                            .collect(),
                        Tab::Facts | Tab::Files => {
                            let prefix = if *tab != Tab::Files {
                                "fact-review/"
                            } else {
                                "file-review/"
                            };
                            let mut reviews: Vec<_> = s
                                .threads
                                .iter()
                                .filter(|thread| {
                                    thread.key.starts_with(prefix)
                                        && !s.archived_threads.contains(&thread.id)
                                        && matches!(thread.state, ThreadState::NeedsYou { .. })
                                })
                                .map(|thread| Detail::Thread(thread.id))
                                .collect();
                            if *tab != Tab::Files {
                                reviews.extend(
                                    s.topic
                                        .facts
                                        .iter()
                                        .filter(|f| f.is_current())
                                        .map(|f| Detail::Fact(f.id)),
                                );
                            } else {
                                reviews.extend(self.file_order(s).into_iter().map(Detail::File));
                            }
                            reviews
                        }
                        Tab::Goals => s.topic.goals.iter().map(|g| Detail::Goal(g.id)).collect(),
                        Tab::Linked => s
                            .topic
                            .context_sources
                            .iter()
                            .map(|w| Detail::Linked(w.key.clone()))
                            .collect(),
                        Tab::Chat | Tab::Needs | Tab::Mission | Tab::Rules => vec![],
                    };
                    details
                        .into_iter()
                        .map(|d| Page::Topic(*id, *tab, Some(d)))
                        .collect()
                })
                .unwrap_or_default(),
            Page::Needs => self
                .states
                .iter()
                .flat_map(|s| {
                    self.needs
                        .iter()
                        .filter_map(move |n| super::pages::attention(n, s).map(|a| a.page))
                })
                .collect(),
            _ => vec![],
        }
    }
    /// A topic's sidebar row: open it, drag it, or act on it from its menu.
    fn topic_row(&self, s: &TopicState, cx: &mut Context<Self>) -> AnyElement {
        let tid = s.topic.id;
        let name = s.topic.name.clone();
        let needs = s.needs_you();
        let cnt = needs.threads.len() + needs.tasks.len();
        let problem = self
            .needs
            .iter()
            .any(|n| matches!(n, NeedsYouItem::Problem {topics,..} if topics.contains(&tid)));
        let gname: SharedString = format!("row-topic-{tid}").into();
        let key = super::sidebar::topic_key(tid);
        let row = super::sidebar::MenuRow::Topic(tid);
        let lifted = cx.has_active_drag() && self.drag_source.as_deref() == Some(key.as_str());
        let (hover_key, title) = (key.clone(), name.clone());
        let selected = self.topic_id() == Some(tid) && self.sheet != Some(Sheet::New);
        let decision = !problem && cnt > 0;
        let badge = if decision { 10. } else { 14. };
        nav_line(format!("topic-{tid}"), selected)
            .h(px(TOPIC_ROW_HEIGHT))
            .relative()
            .group(gname.clone())
            .when(lifted, |r| r.opacity(0.35))
            .pr(px(TOPIC_ROW_TRAILING))
            .rounded(px(TOPIC_ROW_RADIUS))
            .child(
                div()
                    .relative()
                    .flex_none()
                    .child(super::topic_icon::sidebar_tile(&s.topic.display_icon()))
                    .when(
                        problem || cnt > 0 || super::desktop::topic_working(s),
                        |tile| {
                            tile.child(
                                div()
                                    .absolute()
                                    .top(px(if decision { -1. } else { -2. }))
                                    .right(px(if decision { -1. } else { -2. }))
                                    .size(px(badge))
                                    .rounded_full()
                                    .bg(rgb(ui::theme::get(if selected { 7 } else { 6 })))
                                    .flex()
                                    .items_center()
                                    .justify_center()
                                    .child(if problem {
                                        Icon::new(Glyph::TriangleAlert)
                                            .size(px(12.))
                                            .text_color(rgb(ui::theme::color(0xc2610c)))
                                            .into_any_element()
                                    } else if cnt > 0 {
                                        ui::nav::decision_dot().into_any_element()
                                    } else {
                                        self.sidebar_activity.clone().into_any_element()
                                    }),
                            )
                        },
                    ),
            )
            .child(topic_row_text(s, &self.topic_previews[&tid], &gname))
            .child(
                div()
                    .id(SharedString::from(format!("topic-slot-{tid}")))
                    .absolute()
                    .top(px(6.5))
                    .right(px(TOPIC_ROW_TRAILING))
                    .child(
                        row_actions(format!("topic-actions-{tid}"), &name, gname.clone()).on_click(
                            cx.listener(move |s, e: &ClickEvent, w, cx| {
                                cx.stop_propagation();
                                s.show_row_menu(row, e.position(), w, cx);
                            }),
                        ),
                    ),
            )
            .on_drag(Drag::Item(key.clone()), move |_, _, _, cx| {
                cx.new(|_| super::sidebar::Lifted {
                    glyph: Glyph::AtSign,
                    title: title.clone(),
                    trailing: None,
                })
            })
            .on_drag_move(cx.listener(move |s, e: &DragMoveEvent<Drag>, _, cx| {
                if let Drag::Item(source) = e.drag(cx).clone() {
                    s.hover_item_row(&hover_key, &source, e.bounds, e.event.position, cx)
                }
            }))
            .on_hover(
                cx.listener(move |s, hovered: &bool, _, cx| s.hover_topic_card(tid, *hovered, cx)),
            )
            .children(self.topic_card(s, cx))
            .on_click(cx.listener(move |s, _, w, cx| {
                s.dismiss_topic_card(cx);
                s.go(Page::Topic(tid, Tab::Chat, None), w, cx)
            }))
            .on_mouse_down(
                MouseButton::Right,
                cx.listener(move |s, e: &MouseDownEvent, w, cx| {
                    cx.stop_propagation();
                    s.show_row_menu(row, e.position, w, cx);
                }),
            )
            .into_any_element()
    }
    /// A view's sidebar row.
    fn view_row(&self, v: &meep_wire::views::View, cx: &mut Context<Self>) -> AnyElement {
        let vid = v.id;
        let title = v.title.clone();
        let gname: SharedString = format!("row-view-{vid}").into();
        let key = super::sidebar::view_key(vid);
        let row = super::sidebar::MenuRow::View(vid);
        let working = super::desktop::view_working(v);
        let lifted = cx.has_active_drag() && self.drag_source.as_deref() == Some(key.as_str());
        let (hover_key, label) = (key.clone(), title.clone());
        nav_line(format!("view-{vid}"), self.page == Page::View(vid))
            .h(px(TOPIC_ROW_HEIGHT))
            .relative()
            .group(gname.clone())
            .when(lifted, |r| r.opacity(0.35))
            .pr(px(TOPIC_ROW_TRAILING))
            .rounded(px(TOPIC_ROW_RADIUS))
            .child(
                div()
                    .relative()
                    .flex_none()
                    .child(view_tile(v))
                    .when(working, |tile| {
                        tile.child(
                            div()
                                .absolute()
                                .top(px(-1.))
                                .right(px(-1.))
                                .size(px(14.))
                                .rounded_full()
                                .bg(rgb(ui::theme::get(6)))
                                .flex()
                                .items_center()
                                .justify_center()
                                .child(self.sidebar_activity.clone()),
                        )
                    }),
            )
            .child(view_row_text(v, &gname))
            .child(
                div()
                    .id(SharedString::from(format!("view-slot-{vid}")))
                    .absolute()
                    .right(px(TOPIC_ROW_TRAILING))
                    .top(px(6.5))
                    .child(
                        row_actions(format!("view-actions-{vid}"), &title, gname).on_click(
                            cx.listener(move |s, e: &ClickEvent, w, cx| {
                                cx.stop_propagation();
                                s.show_row_menu(row, e.position(), w, cx);
                            }),
                        ),
                    ),
            )
            .on_drag(Drag::Item(key.clone()), move |_, _, _, cx| {
                cx.new(|_| super::sidebar::Lifted {
                    glyph: Glyph::LayoutDashboard,
                    title: label.clone(),
                    trailing: None,
                })
            })
            .on_drag_move(cx.listener(move |s, e: &DragMoveEvent<Drag>, _, cx| {
                if let Drag::Item(source) = e.drag(cx).clone() {
                    s.hover_item_row(&hover_key, &source, e.bounds, e.event.position, cx)
                }
            }))
            .on_click(cx.listener(move |s, _, w, cx| s.go(Page::View(vid), w, cx)))
            .on_mouse_down(
                MouseButton::Right,
                cx.listener(move |s, e: &MouseDownEvent, w, cx| {
                    cx.stop_propagation();
                    s.show_row_menu(row, e.position, w, cx);
                }),
            )
            .into_any_element()
    }
    fn sidebar_row(&self, key: &str, cx: &mut Context<Self>) -> Option<AnyElement> {
        if let Some(rest) = key.strip_prefix("topic:") {
            let id = TopicId(Uuid::parse_str(rest).ok()?);
            let index = self.states.binary_search_by_key(&id, |s| s.topic.id).ok()?;
            let state = &self.states[index];
            return Some(self.topic_row(state, cx));
        }
        let id = Uuid::parse_str(key.strip_prefix("view:")?).ok()?;
        let v = self.views.rows.iter().find(|v| v.id == id)?.clone();
        Some(self.view_row(&v, cx))
    }
    /// Loose topics and views, then each section under its header, as in View.
    fn sidebar_list(&self, w: &mut Window, cx: &mut Context<Self>) -> Div {
        use meep_ui::gpui_kit::component::ActiveTheme;
        const PITCH: f32 = ui::nav::PITCH;
        let item_pitch = |key: &str| {
            if tall_row(key) {
                TOPIC_ROW_HEIGHT + TOPIC_ROW_GAP
            } else {
                PITCH
            }
        };
        let space_above = ui::nav::SECTION_SPACE;
        let arrangement = self.arrangement();
        let hint = cx
            .has_active_drag()
            .then(|| self.drop_hint.clone())
            .flatten();
        // An item dropped into a folded or empty section lights its header.
        let lit = match &hint {
            Some(super::sidebar::Drop::Item {
                section: Some(id), ..
            }) => arrangement
                .sections
                .iter()
                .find(|s| &s.id == id)
                .filter(|s| s.collapsed || s.items.is_empty())
                .map(|s| s.id),
            _ => None,
        };
        let mut list = ui::column().gap_0().relative();
        let mut y = 0.;
        let mut loose_tops = vec![];
        for key in &arrangement.loose {
            if let Some(row) = self.sidebar_row(key, cx) {
                loose_tops.push(y);
                list = list.child(div().pb(px(row_gap(key))).child(row));
                y += item_pitch(key);
            }
        }
        let drawn_loose = loose_tops.len();
        if drawn_loose > 0 {
            loose_tops.push(y);
        }
        let mut header_tops = vec![];
        let mut section_tops: Vec<Vec<f32>> = vec![];
        for (k, section) in arrangement.sections.iter().enumerate() {
            let space = if k == 0 && drawn_loose == 0 {
                0.
            } else {
                space_above
            };
            header_tops.push(y + space);
            list = list.child(
                div()
                    .pt(px(space))
                    .pb(px(ui::nav::GAP))
                    .child(self.section_header(section, lit == Some(section.id), cx)),
            );
            y += space + PITCH;
            let mut open = 0.;
            let mut tops = vec![];
            let mut body = ui::column().gap_0();
            if section.items.is_empty() {
                open = PITCH;
                body = body.child(
                    div().pb(px(ui::nav::GAP)).child(
                        div()
                            .h(px(ui::nav::ROW))
                            .flex()
                            .items_center()
                            .pl(px(ui::nav::PAD + ui::nav::ICON_BOX + 8.))
                            .text_size(px(12.))
                            .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                            .child("Drag topics or views here"),
                    ),
                );
            }
            for key in &section.items {
                if let Some(row) = self.sidebar_row(key, cx) {
                    tops.push(y + open);
                    body = body.child(div().pb(px(row_gap(key))).child(row));
                    open += item_pitch(key);
                }
            }
            if !tops.is_empty() {
                tops.push(y + open);
            }
            section_tops.push(tops);
            let height = meep_ui::gpui_kit::base::spring(
                ElementId::from(SharedString::from(format!("section-height-{}", section.id))),
                if section.collapsed { 0. } else { open },
                cx.theme().motion_tokens().spring_control,
                w,
                cx,
            );
            if height > 0.5 {
                list = list.child(
                    div()
                        .h(px(height))
                        .overflow_hidden()
                        .child(body.opacity((height / open).clamp(0., 1.))),
                );
            }
            y += height;
        }
        let line = |tops: &[f32], index: usize, fallback: f32| -> f32 {
            tops.get(index)
                .or_else(|| tops.last())
                .map_or(fallback, |top| top - ui::nav::GAP / 2.)
        };
        let line_y = match &hint {
            Some(super::sidebar::Drop::Item {
                section: None,
                index,
            }) => Some(line(
                &loose_tops,
                *index,
                header_tops
                    .first()
                    .map_or(1., |top| (top - space_above / 2.).max(1.)),
            )),
            Some(super::sidebar::Drop::Item {
                section: Some(id),
                index,
            }) if lit.is_none() => arrangement
                .sections
                .iter()
                .position(|s| &s.id == id)
                .map(|k| line(&section_tops[k], *index, header_tops[k] + PITCH)),
            Some(super::sidebar::Drop::Section { index }) => Some(match header_tops.get(*index) {
                Some(top) if *index > 0 || drawn_loose > 0 => top - space_above / 2.,
                Some(_) => 1.,
                None => y + space_above / 2.,
            }),
            _ => None,
        };
        if let Some(target) = line_y {
            let at = meep_ui::gpui_kit::base::spring(
                ElementId::from(SharedString::from("sidebar-drop-line")),
                target,
                cx.theme().motion_tokens().spring_control,
                w,
                cx,
            );
            list = list.child(super::sidebar::drop_line(at));
        }
        // Leaving the list drops nothing; letting go anywhere on it lands where
        // the line is.
        list.on_drag_move(cx.listener(|s, e: &DragMoveEvent<Drag>, _, cx| {
            if !matches!(e.drag(cx), Drag::Task(..)) {
                s.leave_list(e.bounds, e.event.position, cx)
            }
        }))
        .on_drop(cx.listener(|s, d: &Drag, _, cx| match d {
            Drag::Item(key) => s.finish_drop(key, cx),
            Drag::Section(id) => s.finish_drop(&id.to_string(), cx),
            Drag::Task(..) => {}
        }))
    }
    fn section_header(&self, section: &Section, lit: bool, cx: &mut Context<Self>) -> AnyElement {
        fn name_style<E: Styled>(element: E) -> E {
            element
                .text_size(px(12.))
                .line_height(px(16.))
                .font_weight(FontWeight::SEMIBOLD)
                .text_color(rgb(ui::theme::color(ui::TERTIARY)))
        }
        let folder = if section.collapsed {
            Glyph::Folder
        } else {
            Glyph::FolderOpen
        };
        let id = section.id;
        if self.renaming_section == Some(id) {
            return ui::row()
                .h(px(ui::nav::ROW))
                .pl(px(ui::nav::PAD))
                .pr(px(ui::nav::TRAIL + ui::nav::ACCESSORY))
                .gap(px(8.))
                .child(ui::nav::glyph(folder, false))
                .child(
                    name_style(Input::new(&self.section_name))
                        .appearance(false)
                        .small()
                        .px_0()
                        .py_0()
                        .min_w_0()
                        .aria_label("Section name")
                        .flex_1(),
                )
                .into_any_element();
        }
        let group: SharedString = format!("section-group-{id}").into();
        let lifted =
            cx.has_active_drag() && self.drag_source.as_deref() == Some(id.to_string().as_str());
        // A folded section still says when something in it needs you.
        let waiting = section.collapsed
            && section.items.iter().any(|k| {
                k.strip_prefix("topic:")
                    .and_then(|t| Uuid::parse_str(t).ok())
                    .and_then(|t| self.states.iter().find(|s| s.topic.id.0 == t))
                    .is_some_and(|s| {
                        let n = s.needs_you();
                        n.threads.len() + n.tasks.len() > 0
                    })
            });
        let row = super::sidebar::MenuRow::Section(id);
        let (title, count) = (section.name.clone(), section.items.len());
        div()
            .id(SharedString::from(format!("section-{id}")))
            .group(group.clone())
            .relative()
            .w_full()
            .h(px(ui::nav::ROW))
            .rounded(px(ui::nav::RADIUS))
            .when(lit, |h| h.bg(ui::ink(ui::nav::PRESSED & 0xff)))
            .when(lifted, |h| h.opacity(0.35))
            .on_drag(Drag::Section(id), move |_, _, _, cx| {
                cx.new(|_| super::sidebar::Lifted {
                    glyph: Glyph::Folder,
                    title: title.clone(),
                    trailing: Some(count.to_string()),
                })
            })
            .on_drag_move(cx.listener(move |s, e: &DragMoveEvent<Drag>, _, cx| {
                match e.drag(cx).clone() {
                    Drag::Item(source) => {
                        s.hover_header_with_item(id, &source, e.bounds, e.event.position, cx)
                    }
                    Drag::Section(source) => s.hover_header_with_section(
                        id,
                        &source.to_string(),
                        e.bounds,
                        e.event.position,
                        cx,
                    ),
                    Drag::Task(..) => {}
                }
            }))
            .child(
                div()
                    .id(SharedString::from(format!("section-toggle-{id}")))
                    .role(Role::Button)
                    .aria_label(format!(
                        "{} section, {}",
                        section.name,
                        if section.collapsed {
                            "collapsed"
                        } else {
                            "expanded"
                        }
                    ))
                    .size_full()
                    .flex()
                    .items_center()
                    .gap(px(8.))
                    .pl(px(ui::nav::PAD))
                    .pr(px(ui::nav::TRAIL + ui::nav::ACCESSORY))
                    .rounded(px(ui::nav::RADIUS))
                    .cursor_pointer()
                    .hover(|s| s.bg(ui::ink(ui::nav::HOVER & 0xff)))
                    .active(|s| s.bg(ui::ink(ui::nav::PRESSED & 0xff)))
                    .child(ui::nav::glyph(folder, false))
                    .child(
                        name_style(div())
                            .flex_1()
                            .min_w_0()
                            .truncate()
                            .child(section.name.clone()),
                    )
                    // Only a toggle: renaming is in the section's menu.
                    .on_click(cx.listener(move |s, _, _, cx| s.toggle_section(id, cx))),
            )
            .child(
                div()
                    .id(SharedString::from(format!("section-slot-{id}")))
                    .absolute()
                    .top_0()
                    .bottom_0()
                    .right(px(ui::nav::TRAIL))
                    .flex()
                    .items_center()
                    .when(waiting, |slot| {
                        slot.child(
                            div()
                                .absolute()
                                .right_0()
                                .group_hover(group.clone(), |s| s.opacity(0.))
                                .child(ui::nav::decision()),
                        )
                    })
                    .child(
                        row_actions(format!("section-actions-{id}"), &section.name, group)
                            .tooltip("Section actions")
                            .on_click(cx.listener(move |s, e: &ClickEvent, w, cx| {
                                cx.stop_propagation();
                                s.show_row_menu(row, e.position(), w, cx);
                            })),
                    ),
            )
            .on_mouse_down(
                MouseButton::Right,
                cx.listener(move |s, e: &MouseDownEvent, w, cx| {
                    cx.stop_propagation();
                    s.show_row_menu(row, e.position, w, cx);
                }),
            )
            .into_any_element()
    }
    fn sidebar(&self, w: &mut Window, cx: &mut Context<Self>) -> Div {
        // Arc's command bar: one quiet field at the top of the glass.
        let top = ui::column()
            .gap(px(ui::nav::GAP))
            .pb(px(ui::nav::SECTION_SPACE))
            .child(
                ui::row()
                    .id("search")
                    .role(Role::Button)
                    .aria_label("Search")
                    .h(px(30.))
                    .mb(px(8.))
                    .px(px(ui::nav::PAD))
                    .gap(px(8.))
                    .rounded(px(8.))
                    .bg(ui::ink(0x0b))
                    .hover(|s| s.bg(ui::ink(0x12)))
                    .cursor_pointer()
                    .child(ui::nav::glyph(Glyph::Search, false))
                    .child(
                        div()
                            .flex_1()
                            .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                            .child("Search"),
                    )
                    .child(
                        div()
                            .text_size(px(11.))
                            .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                            .child(shortcuts::SEARCH.label()),
                    )
                    .on_click(cx.listener(|s, _, w, cx| s.open_sheet(Sheet::Search, w, cx))),
            );
        let mut tree = ui::column().gap_0().child(self.sidebar_list(w, cx));
        // Archived topics leave their sections; they stay reachable here.
        let archived: Vec<_> = self.states.iter().filter(|s| s.archived).collect();
        if !archived.is_empty() {
            use meep_ui::gpui_kit::component::ActiveTheme;
            let open = self.archived_open;
            // Folds like a section: a turning chevron, the name, and its count.
            let turn = meep_ui::gpui_kit::base::spring(
                "archived-turn",
                if open { 1. } else { 0. },
                cx.theme().motion_tokens().spring_control,
                w,
                cx,
            );
            let mut group = ui::column()
                .pt(px(ui::nav::SECTION_SPACE))
                .gap(px(ui::nav::GAP))
                .child(
                    div()
                        .id("archived-toggle")
                        .role(Role::Button)
                        .aria_label(format!(
                            "Archived, {} topics, {}",
                            archived.len(),
                            if open { "expanded" } else { "collapsed" }
                        ))
                        .w_full()
                        .h(px(ui::nav::ROW))
                        .flex()
                        .items_center()
                        .gap(px(8.))
                        .pl(px(ui::nav::PAD))
                        .pr(px(ui::nav::TRAIL + ui::nav::COUNT_INSET - 4.))
                        .rounded(px(ui::nav::RADIUS))
                        .cursor_pointer()
                        .hover(|s| s.bg(ui::ink(ui::nav::HOVER & 0xff)))
                        .active(|s| s.bg(ui::ink(ui::nav::PRESSED & 0xff)))
                        .child(
                            div()
                                .flex_none()
                                .size(px(ui::nav::ICON_BOX))
                                .flex()
                                .items_center()
                                .justify_center()
                                .child(
                                    Icon::new(Glyph::ChevronRight)
                                        .size(px(12.))
                                        .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                                        .rotate(meep_ui::gpui_kit::radians(
                                            std::f32::consts::FRAC_PI_2 * turn,
                                        )),
                                ),
                        )
                        .child(
                            div()
                                .flex_1()
                                .min_w_0()
                                .text_size(px(12.))
                                .font_weight(FontWeight::SEMIBOLD)
                                .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                                .child("Archived"),
                        )
                        .child(
                            div()
                                .flex_none()
                                .text_size(px(12.))
                                .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                                .child(archived.len().to_string()),
                        )
                        .on_click(cx.listener(|s, _, _, cx| {
                            s.archived_open = !s.archived_open;
                            s.folds.toggled("archived", s.archived_open, cx);
                            if let Err(e) = s
                                .client()
                                .set_preference("sidebar-archived-open", &s.archived_open)
                            {
                                s.fail(e)
                            }
                            cx.notify()
                        })),
                );
            // The open archived topic stays in view even while the group is folded.
            let current = self.topic_id();
            let folding = self.folds.progress("archived", open, cx) > 0.;
            for s in archived
                .into_iter()
                .filter(|s| folding || current == Some(s.topic.id))
            {
                let tid = s.topic.id;
                let name = s.topic.name.clone();
                let gname: SharedString = format!("row-archived-{tid}").into();
                let row = super::sidebar::MenuRow::Topic(tid);
                let row = nav_line(format!("archived-{tid}"), self.topic_id() == Some(tid))
                    .h(px(TOPIC_ROW_HEIGHT))
                    .mt(px(TOPIC_ROW_GAP - ui::nav::GAP))
                    .pr(px(TOPIC_ROW_TRAILING))
                    .rounded(px(TOPIC_ROW_RADIUS))
                    .relative()
                    .group(gname.clone())
                    .child(super::topic_icon::sidebar_tile(&s.topic.display_icon()).opacity(0.7))
                    .child(topic_row_text(s, &self.topic_previews[&tid], &gname).opacity(0.7))
                    .child(
                        div()
                            .id(SharedString::from(format!("archived-topic-slot-{tid}")))
                            .absolute()
                            .top(px(6.5))
                            .right(px(TOPIC_ROW_TRAILING))
                            .child(
                                row_actions(format!("topic-actions-{tid}"), &name, gname).on_click(
                                    cx.listener(move |s, e: &ClickEvent, w, cx| {
                                        cx.stop_propagation();
                                        s.show_row_menu(row, e.position(), w, cx);
                                    }),
                                ),
                            ),
                    )
                    .on_click(cx.listener(move |s, _, w, cx| {
                        s.go(Page::Topic(tid, Tab::Chat, None), w, cx)
                    }))
                    .on_mouse_down(
                        MouseButton::Right,
                        cx.listener(move |s, e: &MouseDownEvent, w, cx| {
                            cx.stop_propagation();
                            s.show_row_menu(row, e.position, w, cx);
                        }),
                    );
                group = if current == Some(tid) {
                    group.child(row)
                } else {
                    group.children(self.folds.reveal_as(
                        "archived",
                        &format!("archived-{tid}"),
                        open,
                        cx,
                        || row.into_any_element(),
                    ))
                };
            }
            tree = tree.child(group);
        }
        let status = match self.client().status() {
            Status::Offline { pending, .. } if pending > 0 => Some(
                ui::column()
                    .gap(px(2.))
                    .mx(px(2.))
                    .mb(px(6.))
                    .p(px(10.))
                    .rounded(px(8.))
                    .bg(ui::ink(0x0b))
                    .child(
                        ui::row()
                            .gap(px(6.))
                            .child(ui::nav::glyph(Glyph::CloudOff, false))
                            .child(
                                div()
                                    .font_weight(FontWeight::MEDIUM)
                                    .child(format!("Offline · {pending} pending")),
                            ),
                    )
                    .child(ui::caption("Saved on this Mac. Syncs when you reconnect.")),
            ),
            // A routine sync is not news: the row only appears when something is
            // wrong, so the sidebar does not shift on every pass.
            Status::Online | Status::Syncing => None,
            status => Some(
                ui::row()
                    .h(px(ui::nav::ROW))
                    .pl(px(ui::nav::PAD))
                    .gap(px(8.))
                    .child(ui::nav::glyph(Glyph::CloudOff, false))
                    .child(ui::caption(match status {
                        Status::Unauthorized => "Sign in to PostHog again",
                        _ => "Offline",
                    })),
            ),
        };
        let footer = ui::column().gap(px(ui::nav::GAP)).children(status).child(
            nav_line("settings", self.page == Page::Settings)
                .aria_label("Settings")
                .child(ui::nav::glyph(
                    Glyph::Settings2,
                    self.page == Page::Settings,
                ))
                .child(ui::nav::title("Settings"))
                .on_click(cx.listener(|s, _, w, cx| s.go(Page::Settings, w, cx))),
        );
        let mut side = meep_shell::sidebar(
            tree,
            top.into_any_element(),
            None,
            footer.into_any_element(),
        )
        .w(px(TOPIC_SIDEBAR_WIDTH))
        .child(
            meep_shell::titlebar::button("plus", Glyph::Plus, "New topic, view or section")
                .absolute()
                .top(px(
                    meep_shell::TRAFFIC_LIGHT_CENTER - meep_shell::titlebar::BUTTON / 2.
                ))
                .right(px(ui::nav::INSET + 2.))
                .tooltip(shortcuts::NEW_TOPIC.hint("New topic"))
                .on_click(cx.listener(|s, _, _, cx| {
                    s.menu = !s.menu;
                    cx.notify()
                })),
        );
        if self.menu {
            side = side.child(
                ui::column()
                    .absolute()
                    .top(px(meep_shell::TRAFFIC_LIGHT_CENTER + 16.))
                    .right(px(ui::nav::INSET))
                    .w(px(168.))
                    .p(px(4.))
                    .gap(px(1.))
                    .rounded(px(8.))
                    .bg(rgb(ui::theme::color(ui::CANVAS)))
                    .border_1()
                    .border_color(ui::ink(0x14))
                    .shadow_lg()
                    .occlude()
                    .child(
                        nav_line("new-topic", false)
                            .child(ui::nav::glyph(Glyph::AtSign, false))
                            .child(ui::nav::title("New topic"))
                            .child(ui::caption(shortcuts::NEW_TOPIC.label()).pr(px(6.)))
                            .on_click(cx.listener(|s, _, w, cx| {
                                s.menu = false;
                                s.open_sheet(Sheet::New, w, cx)
                            })),
                    )
                    .child(
                        nav_line("new-view", false)
                            .child(ui::nav::glyph(Glyph::LayoutDashboard, false))
                            .child(ui::nav::title("New view"))
                            .on_click(cx.listener(|s, _, w, cx| {
                                s.section = match s.page {
                                    Page::Topic(id, ..) => {
                                        s.layout.home(&super::sidebar::topic_key(id))
                                    }
                                    Page::View(id) => s.layout.home(&super::sidebar::view_key(id)),
                                    _ => None,
                                }
                                .unwrap_or_default();
                                s.go(Page::NewView, w, cx);
                                s.views.prompt.focus_handle(cx).focus(w, cx)
                            })),
                    )
                    .child(
                        nav_line("new-section", false)
                            .child(ui::nav::glyph(Glyph::FolderPlus, false))
                            .child(ui::nav::title("New section"))
                            .on_click(cx.listener(|s, _, w, cx| {
                                s.menu = false;
                                s.new_section_with(None, w, cx)
                            })),
                    ),
            )
        }
        side
    }
    /// New topic, shaped like New view: say what you want done, name it, create.
    /// It lands in the current section; the sidebar is where it gets moved.
    fn new_topic_page(&self, w: &Window, cx: &Context<Self>) -> Div {
        let ready = !self.name.read(cx).value().trim().is_empty()
            && !self.mission.read(cx).value().trim().is_empty();
        let section = self
            .layout
            .sections
            .iter()
            .find(|s| s.id == self.section)
            .map_or("Lands in the sidebar".to_owned(), |s| {
                format!("Lands in {}", s.name)
            });
        let focused = self.mission.focus_handle(cx).contains_focused(w, cx)
            || self.name.focus_handle(cx).contains_focused(w, cx);
        let card = meep_shell::composer::surface(focused)
            .id("new-topic-composer")
            .child(
                meep_shell::composer::input(&self.mission, "What do you want to get done?")
                    .min_h(px(84.)),
            )
            .child(
                ui::row()
                    .w_full()
                    .gap(px(4.))
                    .pl(px(10.))
                    .pt(px(6.))
                    .border_t_1()
                    .border_color(ui::ink(0x0d))
                    .child(
                        Icon::new(Glyph::AtSign)
                            .size(px(14.))
                            .text_color(rgb(ui::theme::color(ui::SECONDARY))),
                    )
                    .child(
                        Input::new(&self.name)
                            .aria_label("Name")
                            .appearance(false)
                            .bordered(false)
                            .px_0()
                            .flex_1(),
                    )
                    .child(
                        control("submit-sheet", "Create", true, cx, |s, w, cx| {
                            s.submit(w, cx)
                        })
                        .disabled(!ready),
                    ),
            );
        const IDEAS: [(Glyph, &str, &str); 3] = [
            (
                Glyph::Rocket,
                "Onboarding launch",
                "Ship the new onboarding and get activation above 40%",
            ),
            (
                Glyph::GitPullRequest,
                "PR reviews",
                "Keep every pull request review under a day",
            ),
            (
                Glyph::ChartColumn,
                "Retention",
                "Find out why weekly retention dropped and fix it",
            ),
        ];
        let mut ideas = ui::column().gap(px(2.)).mx(px(-10.));
        for (i, (glyph, name, goal)) in IDEAS.into_iter().enumerate() {
            ideas = ideas.child(starter(format!("topic-idea-{i}"), glyph, goal).on_click(
                cx.listener(move |s, _, w, cx| {
                    s.mission.update(cx, |e, cx| e.set_value(goal, w, cx));
                    s.name.update(cx, |e, cx| {
                        e.set_value(name, w, cx);
                        e.focus(w, cx)
                    });
                }),
            ));
        }
        ui::column()
            .size_full()
            .items_center()
            .justify_center()
            .p(px(24.))
            .child(
                ui::column()
                    .w_full()
                    .max_w(px(480.))
                    .gap_0()
                    .mb(px(48.))
                    .child(at_mark(36.))
                    .child(
                        div()
                            .mt(px(16.))
                            .text_size(px(20.))
                            .font_weight(FontWeight::SEMIBOLD)
                            .child("New topic"),
                    )
                    .child(
                        div()
                            .mt(px(6.))
                            .text_size(px(13.))
                            .line_height(relative(1.5))
                            .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                            .child(
                                "Say what you want done. It works toward it with your PostHog \
                                 data and tools, and asks you when it needs a decision.",
                            ),
                    )
                    .child(div().mt(px(20.)).child(card))
                    .child(
                        ui::row()
                            .pt(px(8.))
                            .gap(px(8.))
                            .child(
                                div()
                                    .flex_1()
                                    .text_size(px(ui::SMALL))
                                    .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                                    .child(format!(
                                        "{section}. Drag it anywhere in the sidebar later."
                                    )),
                            )
                            .child(
                                ui::row()
                                    .flex_none()
                                    .gap(px(5.))
                                    .child(
                                        ui::caption("Esc")
                                            .px(px(4.))
                                            .rounded(px(3.))
                                            .bg(ui::ink(16)),
                                    )
                                    .child(ui::caption("Cancel")),
                            ),
                    )
                    .child(
                        div()
                            .mt(px(24.))
                            .text_size(px(12.))
                            .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                            .pb(px(4.))
                            .child("Or start from one of these"),
                    )
                    .child(ideas),
            )
    }
    fn sheet_view(&self, sheet: &Sheet, progress: f32, w: &Window, cx: &Context<Self>) -> Div {
        let title = match sheet {
            Sheet::New => "New topic",
            Sheet::Bind => "Bind a PostHog workflow",
            Sheet::RenameTopic(_) => "Rename topic",
            Sheet::DeleteTopic(_) => "Delete topic?",
            Sheet::DeleteRoutine(..) => "Delete routine?",
            Sheet::Search => "Search",
        };
        let search = *sheet == Sheet::Search;
        let mut body = ui::column()
            .w(px(560.))
            .max_w(relative(0.94))
            .max_h(relative(if search { 0.94 } else { 0.78 }))
            .gap(px(if search { 4. } else { 14. }))
            .p(px(if search { 8. } else { 20. }))
            .rounded(px(12.))
            .bg(rgb(ui::theme::color(ui::CANVAS)))
            .border_1()
            .border_color(ui::ink(28))
            .shadow_lg()
            .occlude();
        body = if search {
            body.child(
                ui::row()
                    .px(px(8.))
                    .gap(px(7.))
                    .flex_none()
                    .border_b_1()
                    .border_color(ui::ink(18))
                    .child(ui::nav::glyph(Glyph::Search, false))
                    .child(
                        Input::new(&self.search)
                            .aria_label("Search")
                            .appearance(false)
                            .bordered(false)
                            .min_h(px(40.))
                            .text_size(px(15.)),
                    ),
            )
        } else if matches!(sheet, Sheet::DeleteTopic(_) | Sheet::DeleteRoutine(..)) {
            body.child(ui::heading("sheet-title", title))
        } else {
            body.child(ui::heading("sheet-title", title)).child(
                ui::field("Name", "", Input::new(&self.name).aria_label("Name"))
                    .max_w_full()
                    .pb_0(),
            )
        };
        match sheet {
            Sheet::New => {
                body = body
                    .child(
                        ui::field(
                            "Mission",
                            "",
                            Textarea::new(&self.mission).aria_label("Mission"),
                        )
                        .max_w_full()
                        .pb_0(),
                    )
                    .child(ui::section_label("Section"));
                let mut options = ui::row().flex_wrap();
                for section in &self.layout.sections {
                    let id = section.id;
                    options = options.child(control(
                        format!("pick-{id}"),
                        section.name.clone(),
                        self.section == id,
                        cx,
                        move |s, _, _| s.section = id,
                    ))
                }
                body=body.child(options).child(ui::caption("Give it a goal. It works toward it with your PostHog data and tools, and asks before it acts."));
            }
            Sheet::Bind => {
                body = body.child(
                    ui::field(
                        "Flow ID",
                        "From the workflow in PostHog.",
                        Textarea::new(&self.mission).aria_label("Flow ID"),
                    )
                    .max_w_full()
                    .pb_0(),
                )
            }
            Sheet::Search => {
                let mut rows = scroll("search-hits")
                    .track_scroll(&self.search_scroll)
                    .gap_0()
                    .max_h(px(420.))
                    .flex_initial();
                let hits = self.hits(cx);
                let has_hits = !hits.is_empty();
                if !has_hits {
                    rows = rows.child(
                        ui::caption("No matching topics, tasks, messages or facts.")
                            .px(px(9.))
                            .py(px(12.)),
                    )
                }
                let mut previous = String::new();
                for (i, (label, group, page)) in hits.into_iter().enumerate() {
                    let icon = div()
                        .flex_none()
                        .w(px(SEARCH_ICON))
                        .flex()
                        .justify_center()
                        .child(match &page {
                            Page::Topic(id, _, None) => self
                                .states
                                .iter()
                                .find(|s| s.topic.id == *id)
                                .map(|s| {
                                    super::topic_icon::small_sidebar_tile(
                                        &s.topic.display_icon(),
                                        SEARCH_ICON,
                                    )
                                })
                                .unwrap_or_else(|| ui::nav::glyph(Glyph::AtSign, false)),
                            Page::View(id) => self
                                .views
                                .rows
                                .iter()
                                .find(|v| v.id == *id)
                                .map(|v| meep_shell::icons::window(&v.icon, &v.color, SEARCH_ICON))
                                .unwrap_or_else(|| ui::nav::glyph(Glyph::LayoutDashboard, false)),
                            Page::Topic(_, Tab::Tasks, _) => ui::nav::glyph(Glyph::Circle, false),
                            Page::Topic(_, Tab::Inbox, _) => {
                                ui::nav::glyph(Glyph::MessageSquare, false)
                            }
                            _ => ui::nav::glyph(Glyph::FileText, false),
                        });
                    let context = match &page {
                        Page::Topic(id, _, Some(_)) => self
                            .states
                            .iter()
                            .find(|s| s.topic.id == *id)
                            .map(|s| format!("@{}", s.topic.name)),
                        _ => None,
                    }
                    // The group heading already names the kind.
                    .unwrap_or_default();
                    // Each scroll child corresponds to one keyboard destination.
                    rows = rows.child(
                        ui::column()
                            .gap_0()
                            .flex_none()
                            .when(previous != group, |el| {
                                el.child(
                                    ui::section_label(group.clone())
                                        .px(px(9.))
                                        .pt(px(if i == 0 { 6. } else { 14. }))
                                        .pb(px(5.)),
                                )
                            })
                            .child(
                                line(format!("hit-{i}"), i == self.search_index)
                                    .gap(px(8.))
                                    .child(icon)
                                    .child(ui::nav::title(label))
                                    .child(ui::caption(context).max_w(relative(0.45)).truncate())
                                    .on_click(
                                        cx.listener(move |s, _, w, cx| s.go(page.clone(), w, cx)),
                                    ),
                            ),
                    );
                    previous = group;
                }
                let hint = |key, label| {
                    ui::row()
                        .gap(px(5.))
                        .child(ui::caption(key).px(px(4.)).rounded(px(3.)).bg(ui::ink(16)))
                        .child(ui::caption(label))
                };
                body = body.child(rows).child(
                    ui::row()
                        .flex_none()
                        .border_t_1()
                        .border_color(ui::ink(24))
                        .gap(px(14.))
                        .px(px(9.))
                        .pt(px(9.))
                        .pb(px(2.))
                        .when(has_hits, |r| {
                            r.child(hint("↑ ↓", "Navigate")).child(hint("↵", "Open"))
                        })
                        .child(hint("Esc", "Close")),
                );
            }
            _ => {}
        }
        if let Sheet::DeleteRoutine(id, key, flow) = sheet.clone() {
            let name = self
                .states
                .iter()
                .find(|s| s.topic.id == id)
                .and_then(|s| s.topic.routines.iter().find(|r| r.binding.id == key))
                .map(|r| r.binding.name.as_str())
                .unwrap_or(&key);
            let message = format!(
                "Deleting “{name}” stops its source subscriptions. Meep also deletes the linked PostHog workflow once no other routine in this workspace uses it."
            );
            let delete = control(
                "confirm-delete-routine",
                "Delete routine",
                true,
                cx,
                move |s, w, cx| {
                    s.dismiss_sheet(w, cx);
                    let client = s.client().clone();
                    let routine = key.clone();
                    let page = Page::Topic(id, Tab::Routines, Some(Detail::Routine(key.clone())));
                    s.job(
                        async move { client.delete_workflow(id, &routine, flow).await },
                        w,
                        cx,
                        move |s, result, w, cx| match result {
                            Ok(()) => {
                                s.reload();
                                s.back.retain(|entry| entry != &page);
                                if s.page == page {
                                    s.navigate(Page::Topic(id, Tab::Routines, None), w, cx);
                                }
                            }
                            Err(e) => {
                                s.error =
                                    Some(format!("Routine deletion could not be confirmed. {e}"))
                            }
                        },
                    );
                },
            );
            body = body.child(ui::caption(message)).child(
                ui::row()
                    .justify_end()
                    .gap(px(6.))
                    .child(control("cancel-sheet", "Cancel", false, cx, |s, w, cx| {
                        s.dismiss_sheet(w, cx)
                    }))
                    .child(meep_shell::settings::danger(delete, cx)),
            );
        } else if let Sheet::DeleteTopic(id) = *sheet {
            let name = self
                .states
                .iter()
                .find(|s| s.topic.id == id)
                .map(|s| s.topic.name.clone())
                .unwrap_or_default();
            body = body
                .child(ui::caption(format!(
                    "“{name}” and its inbox, tasks, facts, files and routines will be deleted on every device. This can’t be undone. Archive it instead to keep everything."
                )))
                .child(
                    ui::row()
                        .justify_end()
                        .gap(px(6.))
                        .child(control("cancel-sheet", "Cancel", false, cx, |s, w, cx| {
                            s.dismiss_sheet(w, cx)
                        }))
                        .child(meep_shell::settings::danger(
                            control("confirm-delete-topic", "Delete topic", true, cx, move |s, w, cx| {
                                if s.issue(id, Command::DeleteTopic) {
                                    s.sheet = None;
                                    s.navigate(Page::Needs, w, cx)
                                }
                            }),
                            cx,
                        )),
                );
        } else if !search {
            body = body.child(
                ui::row()
                    .justify_end()
                    .child(control("cancel-sheet", "Cancel", false, cx, |s, w, cx| {
                        s.dismiss_sheet(w, cx)
                    }))
                    .child(
                        control(
                            "submit-sheet",
                            if *sheet == Sheet::New {
                                "Create topic"
                            } else if *sheet == Sheet::Bind {
                                "Bind workflow"
                            } else {
                                "Save"
                            },
                            true,
                            cx,
                            |s, w, cx| s.submit(w, cx),
                        )
                        .disabled(self.name.read(cx).value().trim().is_empty()),
                    ),
            );
        }
        div()
            .absolute()
            .inset_0()
            .flex()
            .items_center()
            .flex_col()
            .pt(px((f32::from(w.viewport_size().height) * 0.12).min(96.)))
            .bg(rgba(if ui::theme::is_dark() {
                0x00000080
            } else {
                0x00000030
            }))
            .occlude()
            .opacity(progress)
            .child(body.relative().top(px(ui::motion::travel(progress, 8.))))
    }
    pub(super) fn task_drag(
        &self,
        card: Stateful<Div>,
        id: TopicId,
        t: &meep_topic::Task,
    ) -> Stateful<Div> {
        let label = t.title.clone();
        card.on_drag(Drag::Task(id, t.id), move |_, _, _, cx| {
            cx.new(|_| DragLabel(label.clone()))
        })
    }
    pub(super) fn task_drop(
        &self,
        col: Stateful<Div>,
        id: TopicId,
        column: Column,
        cx: &Context<Self>,
    ) -> Stateful<Div> {
        col.drag_over::<Drag>(move |el, drag, _, _| {
            if matches!(drag, Drag::Task(from, _) if *from == id) {
                el.bg(ui::ink(24))
            } else {
                el
            }
        })
        .on_drop(cx.listener(move |s, d: &Drag, _, cx| {
            if let Drag::Task(from, task) = d
                && *from == id
            {
                s.issue(
                    id,
                    Command::MoveTask {
                        task: *task,
                        column,
                    },
                );
                cx.notify()
            }
        }))
    }
    /// The window before there is a topic: View's welcome, one column that
    /// says what a topic is and starts one.
    fn welcome(&self, cx: &Context<Self>) -> Div {
        let signed = self.identity.is_some();
        let muted = rgb(ui::theme::color(ui::SECONDARY));
        let column = ui::column()
            .w_full()
            .max_w(px(440.))
            .gap_0()
            .mb(px(48.))
            .child(div().mb(px(18.)).child(super::brand::wordmark(144.)))
            .child(
                div()
                    .text_size(px(20.))
                    .font_weight(FontWeight::SEMIBOLD)
                    .child(if signed {
                        "Start your first topic"
                    } else {
                        "Welcome to Meep"
                    }),
            )
            .child(
                div()
                    .mt(px(6.))
                    .text_size(px(13.))
                    .line_height(relative(1.5))
                    .text_color(muted)
                    .child(if signed {
                        "A topic is something you want to get done. Give it a goal and it works \
                         on it with your PostHog data and tools, asking you only when it needs \
                         a decision."
                    } else {
                        "Each topic works toward something you want done, using your PostHog \
                         data and tools, and asks you only when it needs a decision."
                    }),
            );
        let column = if signed {
            let field = div()
                .id("welcome-field")
                .role(Role::Button)
                .aria_label("Start a topic")
                .mt(px(20.))
                .w_full()
                .h(px(44.))
                .px(px(14.))
                .flex()
                .items_center()
                .gap(px(10.))
                .rounded(px(12.))
                .bg(rgb(ui::theme::color(ui::CANVAS)))
                .border_1()
                .border_color(ui::ink(0x17))
                .shadow(vec![BoxShadow {
                    color: rgba(0x0000000a).into(),
                    offset: point(px(0.), px(1.)),
                    blur_radius: px(2.),
                    spread_radius: px(0.),
                    inset: false,
                }])
                .cursor_text()
                .hover(|s| s.border_color(ui::ink(0x26)))
                .on_click(cx.listener(|s, _, w, cx| s.open_sheet(Sheet::New, w, cx)))
                .child(
                    div()
                        .flex_1()
                        .text_size(px(14.))
                        .text_color(muted)
                        .child("What do you want to get done?"),
                )
                .child(
                    div()
                        .text_size(px(12.))
                        .text_color(muted)
                        .child(shortcuts::NEW_TOPIC.label()),
                );
            const IDEAS: [(Glyph, &str, &str); 3] = [
                (
                    Glyph::Rocket,
                    "Onboarding launch",
                    "Ship the new onboarding and get activation above 40%",
                ),
                (
                    Glyph::GitPullRequest,
                    "PR reviews",
                    "Keep every pull request review under a day",
                ),
                (
                    Glyph::ChartColumn,
                    "Retention",
                    "Find out why weekly retention dropped and fix it",
                ),
            ];
            let mut ideas = ui::column().w_full().gap(px(2.)).child(
                div()
                    .text_size(px(12.))
                    .text_color(muted)
                    .px(px(10.))
                    .pb(px(4.))
                    .child("Or start from one of these"),
            );
            for (i, (glyph, name, goal)) in IDEAS.into_iter().enumerate() {
                ideas = ideas.child(starter(format!("welcome-idea-{i}"), glyph, goal).on_click(
                    cx.listener(move |s, _, w, cx| {
                        s.open_sheet(Sheet::New, w, cx);
                        s.name.update(cx, |e, cx| e.set_value(name, w, cx));
                        s.mission.update(cx, |e, cx| e.set_value(goal, w, cx));
                    }),
                ));
            }
            column
                .child(field)
                .child(div().mt(px(20.)).mx(px(-10.)).child(ideas))
                .child(
                    ui::row()
                        .mt(px(20.))
                        .gap(px(4.))
                        .child(
                            div()
                                .text_size(px(12.))
                                .text_color(muted)
                                .child("Topics work from what you connect to PostHog."),
                        )
                        .child(
                            div()
                                .id("welcome-connect")
                                .role(Role::Button)
                                .px(px(6.))
                                .py(px(2.))
                                .rounded(px(5.))
                                .text_size(px(12.))
                                .font_weight(FontWeight::MEDIUM)
                                .text_color(rgb(ui::theme::get(10)))
                                .cursor_pointer()
                                .hover(|s| s.bg(ui::ink(0x0a)))
                                .child("See connections →")
                                .on_click(cx.listener(|s, _, w, cx| {
                                    s.settings_page = SettingsPage::Connections;
                                    s.go(Page::Settings, w, cx)
                                })),
                        ),
                )
        } else {
            column
                .child(
                    ui::row()
                        .mt(px(20.))
                        .gap(px(10.))
                        .child(
                            ui::row()
                                .gap(px(6.))
                                .child(div().text_size(px(12.)).text_color(muted).child("Region"))
                                .child(self.region_picker(cx)),
                        )
                        .child(
                            control(
                                "welcome-action",
                                if self.login_busy {
                                    "Waiting for PostHog…"
                                } else {
                                    "Sign in to PostHog"
                                },
                                true,
                                cx,
                                |s, w, cx| s.login(w, cx),
                            )
                            .disabled(self.login_busy),
                        )
                        .when(self.login_busy, |r| {
                            r.child(meep_shell::puppet::opening(4, 38.))
                        }),
                )
                .child(
                    div()
                        .mt(px(14.))
                        .text_size(px(12.))
                        .text_color(muted)
                        .child("Sign-in opens PostHog in your browser."),
                )
        };
        ui::column()
            .size_full()
            .items_center()
            .justify_center()
            .p(px(24.))
            .child(column)
    }
    fn region_picker(&self, cx: &Context<Self>) -> Div {
        ui::row()
            .self_start()
            .gap(px(2.))
            .p(px(2.))
            .rounded(px(7.))
            .bg(ui::ink(12))
            .children(
                [
                    (Region::Us, "US"),
                    (Region::Eu, "EU"),
                    (Region::Local, "Local"),
                ]
                .into_iter()
                .filter(|(r, _)| {
                    *r != Region::Local || std::env::var("MEEP_POSTHOG_LOCAL").as_deref() == Ok("1")
                })
                .map(|(r, label)| {
                    control(label, label, false, cx, move |s, _, _| {
                        s.region = r;
                        if let Err(e) = s.client().set_preference("region", &r) {
                            s.fail(e)
                        }
                    })
                    .border_0()
                    // Sized so the switch matches a 28pt button beside it.
                    .h(px(24.))
                    .when(self.region == r, |btn| {
                        btn.bg(rgb(ui::theme::color(ui::CANVAS)))
                            .border_1()
                            .border_color(ui::ink(42))
                    })
                }),
            )
    }
    /// The settings sidebar: View swaps the source list for settings destinations.
    fn settings_rail(&self, cx: &Context<Self>) -> Div {
        let list = ui::column()
            .gap(px(ui::nav::GAP))
            .children(SettingsPage::ALL.into_iter().map(|page| {
                let active = self.settings_page == page;
                nav_line(format!("settings-{}", page.title().to_lowercase()), active)
                    .aria_label(page.title())
                    .child(ui::nav::glyph(page.glyph(), active))
                    .child(ui::nav::title(page.title()))
                    .on_click(cx.listener(move |s, _, w, cx| {
                        s.settings_page = page;
                        s.clear_confirm = false;
                        if page == SettingsPage::Connections {
                            s.mcp.screen = super::mcp_settings::Screen::List;
                            s.mcp_request(meep_wire::mcp_store::Operation::Browse, w, cx);
                        }
                        cx.notify()
                    }))
            }));
        let back = nav_line("close-settings", false)
            .aria_label("Back to topics")
            .child(ui::nav::glyph(Glyph::ArrowLeft, false))
            .child(ui::nav::title("Back"))
            .child(
                ui::caption("Esc")
                    .px(px(4.))
                    .mr(px(6.))
                    .rounded(px(3.))
                    .bg(ui::ink(16)),
            )
            .on_click(cx.listener(|s, _, w, cx| {
                let page = s.back.pop().unwrap_or(Page::Needs);
                s.navigate(page, w, cx)
            }));
        meep_shell::sidebar(
            list,
            div().into_any_element(),
            None,
            back.into_any_element(),
        )
    }
    fn settings(&self, w: &Window, cx: &mut Context<Self>) -> AnyElement {
        use meep_shell::settings::{group, header, item, section};
        let width =
            w.viewport_size().width - px(meep_ui::design::current().sidebar + meep_shell::GUTTER);
        let content = match self.settings_page {
            SettingsPage::Appearance => {
                fn select(
                    s: &mut Desktop,
                    choice: Option<&str>,
                    w: &mut Window,
                    cx: &mut Context<Desktop>,
                ) {
                    if let Err(e) = s.client().set_preference("appearance", &choice) {
                        s.fail(e);
                    } else {
                        s.scheme = choice.map(str::to_owned);
                        meep_shell::appearance::set_palette(
                            meep_shell::appearance::resolve(choice, w.appearance()),
                            cx,
                        );
                    }
                    cx.notify();
                }
                return meep_shell::appearance::picker(
                    self.scheme.as_deref(),
                    false,
                    width,
                    select,
                    w,
                    cx,
                );
            }
            SettingsPage::General => {
                let account = if let Some(a) = &self.identity {
                    item(
                        a.email.clone(),
                        format!("{} · {}", a.label, a.region.key().to_uppercase()),
                        control("logout", "Sign out", false, cx, |s, w, cx| {
                            let b = s.backend.clone();
                            s.job(async move { b.sign_out().await }, w, cx, |s, r, w, cx| {
                                // The Mac is signed out either way; a server error follows.
                                s.identity = None;
                                s.github = Default::default();
                                s.mcp = super::mcp_settings::McpSettings::new(w, cx);
                                s.error = None;
                                s.back.clear();
                                s.navigate(Page::Needs, w, cx);
                                if let Err(e) = r {
                                    s.fail(e)
                                }
                            })
                        })
                        .self_center(),
                    )
                } else {
                    item(
                        "Signed out",
                        "Choose your PostHog region, then sign in.",
                        ui::row()
                            .gap(px(8.))
                            .when(self.login_busy, |r| {
                                r.child(meep_shell::puppet::opening(4, 38.))
                            })
                            .child(self.region_picker(cx))
                            .child(
                                control(
                                    "settings-login",
                                    if self.login_busy {
                                        "Waiting for PostHog…"
                                    } else {
                                        "Sign in to PostHog"
                                    },
                                    true,
                                    cx,
                                    |s, w, cx| s.login(w, cx),
                                )
                                .disabled(self.login_busy),
                            ),
                    )
                };
                ui::column()
                    .gap_0()
                    .child(header(
                        "General",
                        "The PostHog account your topics work with.",
                        None,
                    ))
                    .child(section("Account", "", None, true))
                    .child(group([account.into_any_element()]))
                    .when(self.identity.is_some(), |column| {
                        column.child(self.github_settings(cx))
                    })
            }
            SettingsPage::Connections => self.mcp_page(cx),
            SettingsPage::Shortcuts => self.shortcuts_page(),
            SettingsPage::Permissions => self.permissions_page(cx),
            SettingsPage::Advanced => self.advanced_page(cx),
            SettingsPage::Notifications => self.notifications_page(cx),
        };
        meep_shell::appearance::settings_body("settings-scroll", width, content)
    }
}
pub(super) fn side_overlay(width: f32, progress: f32, content: Div) -> Div {
    div()
        .absolute()
        .top_0()
        .right(px(-ui::motion::travel(progress.clamp(0., 1.), width)))
        .bottom_0()
        .w(px(width))
        .border_l_1()
        .border_color(ui::ink(0x12))
        .bg(rgb(ui::theme::color(ui::CANVAS)))
        .shadow_lg()
        .occlude()
        .child(content.size_full())
}

pub(super) fn side_pane(
    id: &'static str,
    width: f32,
    progress: f32,
    content: Div,
) -> Stateful<Div> {
    div()
        .id(id)
        .h_full()
        .py(px(meep_shell::GUTTER))
        .overflow_hidden()
        .flex_shrink_0()
        .flex()
        .justify_end()
        .w(px((width + meep_shell::GUTTER) * progress.clamp(0., 1.)))
        .child(
            meep_shell::pane(content)
                .h_full()
                .mr(px(meep_shell::GUTTER))
                .w(px(width)),
        )
}

impl Render for Desktop {
    fn render(&mut self, w: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        // The sidebar spinner runs while any topic's or view's agent works.
        let working = self.states.iter().any(super::desktop::topic_working)
            || self
                .views
                .rows
                .iter()
                .any(|v| super::desktop::view_working(v));
        if self.folds.moving(cx) {
            w.request_animation_frame();
        }
        let reduced = cx.reduce_motion();
        self.sidebar_activity
            .update(cx, |a, cx| a.set_active(working, reduced, cx));
        if let Some((topic, task)) = self.chat_task()
            && let Some(t) = self
                .states
                .iter()
                .find(|s| s.topic.id == topic)
                .and_then(|s| s.tasks.iter().find(|t| t.id == task))
            && t.column == Column::NeedsYou
            && self.editing_review != Some((topic, task, t.review_version))
        {
            self.editing_review = Some((topic, task, t.review_version));
            self.send_back = false;
            self.draft.update(cx, |e, cx| {
                e.set_value(t.draft.clone().unwrap_or_default(), w, cx)
            });
        }
        if std::mem::take(&mut self.reveal_selection) {
            let row = self.selection_bounds.clone();
            let content = self.content_scroll.clone();
            let board = matches!(self.page, Page::Topic(_, Tab::Tasks, _))
                .then(|| self.board_scroll.clone());
            // The detail pane changes the available width. Measure the selected
            // row after layout, then move only as far as necessary on each axis.
            w.on_next_frame(move |w, _| {
                let row = row.bounds();
                let viewport = content.bounds();
                let adjustment = |start: Pixels, end: Pixels, low: Pixels, high: Pixels| {
                    if start < low {
                        low - start
                    } else {
                        (high - end).min(px(0.))
                    }
                };
                let dy = adjustment(row.top(), row.bottom(), viewport.top(), viewport.bottom());
                content.set_offset(content.offset() + point(px(0.), dy));
                if let Some(board) = board {
                    let viewport = board.bounds();
                    let dx = adjustment(row.left(), row.right(), viewport.left(), viewport.right());
                    board.set_offset(board.offset() + point(dx, px(0.)));
                }
                w.refresh();
            });
        }
        let settings_open = self.page == Page::Settings;
        let live = self.identity.is_some() && !(self.sidebar_hidden && !settings_open);
        let can_toggle = self.identity.is_some() && !settings_open;
        let sidebar_visible = !self.sidebar_hidden;
        // View's choreography: the sidebar slides in and out with its own
        // spring, and settings arrive with a short travel once opened.
        let rail_wanted = settings_open || live;
        let rail_motion = ui::motion::pane("host-sidebar", rail_wanted, w, cx);
        let rail = rail_motion.progress.clamp(0., 1.);
        let arrival = ui::motion::presence("host-settings", settings_open, w, cx)
            .progress
            .clamp(0., 1.);
        // The Overview: its own pane beside the topic, sliding in with View's presence spring.
        let overview_topic = match &self.page {
            Page::Topic(id, ..) if self.sheet != Some(Sheet::New) && self.overview_docked(w) => {
                self.states
                    .iter()
                    .find(|s| s.topic.id == *id)
                    .map(|s| s.topic.id)
            }
            _ => None,
        };
        let overview_presence =
            ui::motion::pane("topic-overview-pane", overview_topic.is_some(), w, cx);
        if overview_topic.is_some() {
            self.overview_leaving = overview_topic;
        } else if !overview_presence.should_render() {
            self.overview_leaving = None;
        }
        let overview = overview_presence.progress.clamp(0., 1.);
        let rail_target = if rail_wanted { 1. } else { 0. };
        let overview_target = if overview_topic.is_some() { 1. } else { 0. };
        self.pane_motion.set((rail, overview));
        self.pane_target.set((rail_target, overview_target));
        // The layout row stretches the pane; a full height plus its gutters
        // would push its bottom edge past the window.
        let mut main = ui::column()
            .flex_1()
            .min_w_0()
            .min_h_0()
            .gap(px(14.))
            .px(px(24.))
            .py(px(18.))
            .overflow_hidden();
        if self.sheet == Some(Sheet::New) && self.identity.is_some() {
            main = main.p_0().child(self.new_topic_page(w, cx))
        } else if self.page == Page::Settings {
            main = main.p_0().child(self.settings(w, cx))
        } else if self.identity.is_some() && matches!(self.page, Page::View(_) | Page::NewView) {
            main = main.p_0().child(self.view_page(w, cx));
        } else if self.identity.is_none() || self.states.is_empty() {
            main = main.p_0().child(self.welcome(cx));
        } else {
            match self.page.clone() {
                Page::Needs => main = main.child(self.attention_page(cx)),
                Page::Topic(id, tab, detail) => {
                    if let Some(state) = self.states.iter().find(|s| s.topic.id == id) {
                        main = main
                            .p_0()
                            .child(self.topic_view(state, tab, detail.as_ref(), w, cx))
                    }
                }
                Page::Settings | Page::View(_) | Page::NewView => {}
            }
        }
        let rejection = self
            .identity
            .as_ref()
            .and_then(|_| self.client().rejections().ok())
            .and_then(|r| r.into_iter().next());
        let dismissed = self
            .error
            .is_none()
            .then(|| rejection.as_ref().map(|r| r.0))
            .flatten();
        let recovery = dismissed.and_then(|id| {
            self.client()
                .rejected_file_path(id)
                .ok()
                .flatten()
                .map(|path| (id, path))
        });
        // Failures float as one of View's toast cards in the pane's corner:
        // a plain sentence first, what to do next beside it.
        let toast_key = self
            .error
            .as_deref()
            .or(rejection.as_ref().map(|r| r.1.as_str()))
            .map(|e| e.len())
            .unwrap_or(0);
        let toast = self
            .error
            .clone()
            .or_else(|| rejection.as_ref().map(|r| r.1.clone()))
            .map(|e| {
                let (title, body) = match &recovery {
                    Some((_, path)) => (
                        format!("Couldn't upload {path}"),
                        Some(format!("{e} A copy is saved on this Mac.")),
                    ),
                    None => (e, None),
                };
                let mut actions = ui::row().gap(px(6.)).pt(px(8.));
                if let Some((id, path)) = recovery.clone() {
                    actions = actions
                        .child(control(
                            "save-rejected-file",
                            "Save a copy…",
                            true,
                            cx,
                            move |s, w, cx| {
                                s.save_rejected_file(id, &path, w, cx);
                            },
                        ))
                        .child(control(
                            "discard-rejected-file",
                            "Discard",
                            false,
                            cx,
                            move |s, _, _| {
                                s.error = dismissed
                                    .and_then(|id| s.client().dismiss_rejection(id).err())
                                    .map(|e| e.to_string())
                            },
                        ));
                }
                let has_actions = recovery.is_some();
                ui::row()
                    .id("error-toast")
                    .role(Role::Alert)
                    .w(px(360.))
                    .items_start()
                    .gap(px(10.))
                    .py(px(12.))
                    .pl(px(14.))
                    .pr(px(6.))
                    .bg(rgb(ui::theme::color(ui::CANVAS)))
                    .border_1()
                    .border_color(ui::ink(0x14))
                    .rounded(px(10.))
                    .shadow(vec![BoxShadow {
                        color: rgba(0x00000024).into(),
                        offset: point(px(0.), px(8.)),
                        blur_radius: px(24.),
                        spread_radius: px(-6.),
                        inset: false,
                    }])
                    .child(
                        div()
                            .flex_none()
                            .size(px(16.))
                            .h(px(17.))
                            .flex()
                            .items_center()
                            .justify_center()
                            .child(
                                Icon::new(Glyph::TriangleAlert)
                                    .size(px(14.))
                                    .text_color(rgb(0xb4570a)),
                            ),
                    )
                    .child(
                        ui::column()
                            .flex_1()
                            .min_w_0()
                            .gap(px(2.))
                            .child(
                                div()
                                    .line_clamp(3)
                                    .line_height(px(17.))
                                    .font_weight(FontWeight::MEDIUM)
                                    .child(title),
                            )
                            .when_some(body, |c, body| {
                                c.child(
                                    div()
                                        .line_clamp(3)
                                        .text_size(px(12.))
                                        .line_height(px(16.))
                                        .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                                        .child(body),
                                )
                            })
                            .when(has_actions, |c| c.child(actions)),
                    )
                    .child(
                        ui::icon_button("dismiss-error", Glyph::X, "Dismiss")
                            .flex_none()
                            .mt(px(-6.))
                            .on_click(cx.listener(move |s, _, _, cx| {
                                s.error = dismissed
                                    .and_then(|id| s.client().dismiss_rejection(id).err())
                                    .map(|e| e.to_string());
                                cx.notify()
                            })),
                    )
            });
        // A view's composer offers the models a view can be built with.
        if self.identity.is_some() && matches!(self.page, Page::View(_) | Page::NewView) {
            self.ensure_view_models(w, cx);
        }
        let mut view_panel = None;
        let mut view_shift = 0.;
        if let Some((width, progress, target, content)) = self.active_view_panel(w, cx) {
            if w.viewport_size().width > px(super::overview::DOCK_MIN) {
                view_shift = (width + meep_shell::GUTTER) * (target - progress.clamp(0., 1.));
                view_panel = Some(side_pane("view-chat-slot", width, progress, content));
            } else {
                main = main
                    .relative()
                    .child(side_overlay(width, progress, content));
            }
        }
        let rail_list = (rail > 0.).then(|| {
            if settings_open {
                self.settings_rail(cx)
                    .relative()
                    .left(px(ui::motion::travel(arrival, 8.)))
                    .opacity(arrival)
            } else {
                self.sidebar(w, cx).opacity(rail)
            }
        });
        let overview_state = overview_presence
            .should_render()
            .then(|| overview_topic.or(self.overview_leaving))
            .flatten()
            .and_then(|topic| self.states.iter().find(|s| s.topic.id == topic).cloned());
        let overview_pane = overview_state.map(|state| {
            side_pane(
                "topic-overview-slot",
                super::overview::WIDTH,
                overview_presence.progress,
                self.overview(&state, cx),
            )
        });
        let sheet_open = self.sheet.clone().filter(|s| !matches!(s, Sheet::New));
        let sheet_presence = ui::motion::presence("sheet", sheet_open.is_some(), w, cx);
        if sheet_open.is_some() {
            self.sheet_leaving = sheet_open.clone();
        } else if !sheet_presence.should_render() {
            self.sheet_leaving = None;
        }
        let sheet_progress = sheet_presence.progress.clamp(0., 1.);
        let sheet_leaving = sheet_open.is_none();
        let sheet_shown = sheet_presence
            .should_render()
            .then(|| sheet_open.or(self.sheet_leaving.clone()))
            .flatten();
        let sidebar_width = if settings_open {
            meep_ui::design::current().sidebar
        } else {
            TOPIC_SIDEBAR_WIDTH
        };
        let main_shift = (sidebar_width - meep_shell::GUTTER) * (rail_target - rail)
            + view_shift
            + (super::overview::WIDTH + meep_shell::GUTTER) * (overview_target - overview);
        let root = meep_shell::root();
        #[cfg(feature = "demo-driver")]
        let root = root.children(super::demo_driver::cursor());
        root.track_focus(&self.focus)
            .on_action(cx.listener(Desktop::run_row_action))
            .capture_key_down(cx.listener(|s, e, w, cx| s.key(e, w, cx)))
            .on_action(
                cx.listener(|s, _: &meep_shell::workspace::OpenSettings, w, cx| {
                    s.go(Page::Settings, w, cx)
                }),
            )
            .on_action(
                cx.listener(|_, _: &meep_shell::workspace::CloseWindow, w, _| w.remove_window()),
            )
            .child(
                meep_shell::window_layout(rail)
                    .items_stretch()
                    .when_some(rail_list, |l, list| {
                        let slot = meep_shell::sidebar_slot(rail).when(!settings_open, |slot| {
                            slot.w(px(TOPIC_SIDEBAR_WIDTH * rail))
                        });
                        l.child(slot.child(list))
                    })
                    .child(
                        meep_shell::pane(div().flex().flex_1().min_w_0().min_h_0().child(
                            main.mr(px(main_shift)).when(settings_open, |m| {
                                m.relative()
                                    .left(px(ui::motion::travel(arrival, 8.)))
                                    .opacity(arrival)
                            }),
                        ))
                        .my(px(meep_shell::GUTTER))
                        .mr(px(meep_shell::GUTTER))
                        .ml(px(meep_shell::GUTTER * (1. - rail))),
                    )
                    .children(view_panel)
                    .children(overview_pane),
            )
            .when_some(toast, |root, toast| {
                // Each new message rises into place once.
                let arrived = ui::motion::arrival(
                    ElementId::from(SharedString::from(format!("error-toast-{}", toast_key))),
                    false,
                    w,
                    cx,
                )
                .progress
                .clamp(0., 1.);
                root.child(deferred(
                    div()
                        .absolute()
                        .bottom(px(24. - ui::motion::travel(arrived, 8.)))
                        .right(px(24.))
                        .opacity(arrived)
                        .occlude()
                        .child(toast),
                ))
            })
            .when(can_toggle, |root| {
                root.child(self.needs_button(cx)).child(
                    meep_shell::sidebar_toggle(sidebar_visible).on_click(cx.listener(
                        |s, _, _, cx| {
                            s.sidebar_hidden = !s.sidebar_hidden;
                            cx.notify()
                        },
                    )),
                )
            })
            .when_some(sheet_shown, |el, sh| {
                el.child(
                    self.sheet_view(&sh, sheet_progress, w, cx)
                        .when(sheet_leaving, |d| {
                            d.child(div().absolute().inset_0().occlude())
                        }),
                )
            })
    }
}

/// The "…" button View shows on a sidebar row while it is hovered.
fn row_actions(id: String, title: &str, group: SharedString) -> Button {
    ui::contextual_icon_button(
        SharedString::from(id),
        Glyph::Ellipsis,
        format!("Actions for {title}"),
        group,
        false,
    )
    .size(px(ui::nav::ACCESSORY))
    .rounded(px(5.))
}
