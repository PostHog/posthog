//! Workspace pages rendered by the shared View runtime.
use super::*;
use anyhow::Context as _;
use meep_protocol::sessions::{AgentMessage, AgentSession};
use meep_render::sdk::{MountedView, ViewContext, ViewHost};
use meep_ui::gpui_kit::component::{Disableable, Icon, Sizable, input::Enter};
use meep_wire::views::{Stage, View, ViewCommand};
use serde_json::{Value, json};

struct DataBridge {
    id: Uuid,
    client: Client,
}
#[async_trait::async_trait]
impl ViewHost for DataBridge {
    async fn request(&self, method: &str, params: Value) -> Result<Value, meep_render::HostError> {
        self.read(method, &params)
            .await
            .map_err(|e| e.to_string().into())
    }
}
impl DataBridge {
    async fn read(&self, method: &str, p: &Value) -> Result<Value> {
        if method == "views.state" {
            return Ok(Value::Null);
        }
        anyhow::ensure!(
            method == "sources.call",
            "Unavailable view operation {method}"
        );
        if p["source"] != "topics" {
            return self.client.view_source(self.id, p.clone()).await;
        }
        let args = &p["arguments"];
        let topic = args["topic"]
            .as_str()
            .context("Missing topic ID")?
            .parse()?;
        let tool = p["tool"].as_str().context("Missing tool")?;
        match tool {
            "files" => {
                if let Err(error) = self.client.refresh_files(topic).await
                    && !matches!(self.client.status(), Status::Offline { .. })
                {
                    return Err(error);
                }
                Ok(json!(self.client.cached_files(topic)?))
            }
            "file" | "table" => {
                let path = args["path"].as_str().context("Missing file path")?;
                let file = self.client.get_file(topic, path).await?;
                if tool == "file" {
                    Ok(json!(String::from_utf8(file.bytes)?))
                } else {
                    Ok(json!(meep_wire::table::read(path, &file.bytes)?))
                }
            }
            "routine_data" => Ok(self
                .client
                .topic(topic)?
                .context("Unknown topic")?
                .view_data
                .remove(&self.id)
                .unwrap_or_default()),
            _ => meep_wire::views::topic_rows(
                &self.client.topic(topic)?.context("Unknown topic")?,
                tool,
            ),
        }
    }
}

struct Mount {
    context: ViewContext,
    result: Result<MountedView, String>,
}
impl Drop for Mount {
    fn drop(&mut self) {
        self.context.retire()
    }
}
pub(super) struct ViewWorkspace {
    pub rows: Vec<Arc<View>>,
    pub prompt: Entity<TextareaState>,
    pub emoji_query: Entity<InputState>,
    pub panel: bool,
    pub settings: bool,
    pub history: bool,
    pub session: Option<Uuid>,
    pub tile: (String, String),
    pub confirm_delete: bool,
    /// The request's model and effort, picked from the views catalogue.
    pub models: Entity<meep_shell::model_picker::ModelPicker>,
    pub catalogue: meep_wire::ChatModels,
    pub models_loaded: bool,
    pub model: Option<String>,
    pub effort: Option<String>,
    /// Files staged on the server for the next request, by name.
    pub files: Vec<String>,
    pub uploading: usize,
    /// Where a new view's files are staged before the view exists.
    pub draft: Uuid,
    mount: Option<Mount>,
}
impl ViewWorkspace {
    pub fn new(w: &mut Window, cx: &mut Context<Desktop>) -> Self {
        let prompt = cx.new(|cx| TextareaState::new(w, cx).auto_grow(2, 7));
        prompt.update(cx, |e, cx| e.set_submit_on_enter(true, cx));
        let emoji_query = cx.new(|cx| InputState::new(w, cx).placeholder("Find an emoji"));
        cx.subscribe(&emoji_query, |_, _, _: &InputEvent, cx| cx.notify())
            .detach();
        cx.subscribe(&prompt, |_, _, _: &InputEvent, cx| cx.notify())
            .detach();
        let models =
            cx.new(|cx| meep_shell::model_picker::ModelPicker::new(prompt.focus_handle(cx), w, cx));
        cx.subscribe_in(&models, w, |s: &mut Desktop, _, change, w, cx| {
            use meep_shell::model_picker::Change;
            match change {
                Change::Model(model) => {
                    s.views.model = model.clone();
                    s.views.effort = None;
                }
                Change::Effort(effort) => s.views.effort = effort.clone(),
                Change::Refresh | Change::Recover => {
                    s.views.models_loaded = false;
                    s.ensure_view_models(w, cx);
                }
            }
            s.sync_view_selection(cx);
            cx.notify()
        })
        .detach();
        Self {
            rows: vec![],
            prompt,
            emoji_query,
            panel: false,
            settings: false,
            history: false,
            session: None,
            tile: Default::default(),
            confirm_delete: false,
            models,
            catalogue: Default::default(),
            models_loaded: false,
            model: None,
            effort: None,
            files: vec![],
            uploading: 0,
            draft: Uuid::new_v4(),
            mount: None,
        }
    }
    pub fn leave(&mut self) {
        self.mount = None;
        self.panel = false;
        self.settings = false;
        self.history = false;
        self.session = None;
        self.confirm_delete = false;
    }
    pub fn refresh(&self, w: &mut Window, cx: &mut App) {
        if let Some(Mount { result: Ok(m), .. }) = &self.mount {
            let _ = m.command("refresh", json!({}), w, cx);
        }
    }
}

pub(super) fn progress(stage: &Stage) -> String {
    match stage {
        Stage::Queued => "Waiting to start".into(),
        Stage::Starting => "Starting the agent".into(),
        // PostHog reports a run's raw status; say it in words.
        Stage::Working(p) => match p.as_str() {
            "queued" | "pending" => "Waiting to start".into(),
            "starting" | "Starting" => "Starting the agent".into(),
            p if p.contains(' ') && !p.contains('_') => p.to_owned(),
            _ => "Working on it".into(),
        },
        Stage::Finished(s) => s.clone(),
    }
}
impl Desktop {
    pub(super) fn send_view(&mut self, w: &mut Window, cx: &mut Context<Self>) {
        let prompt = self.views.prompt.read(cx).value().trim().to_owned();
        if prompt.is_empty() {
            return;
        }
        if self.views.uploading > 0 {
            return;
        }
        let options = meep_wire::views::TurnOptions {
            model: self.views.model.clone(),
            effort: self.views.effort.clone(),
            files: self.views.files.clone(),
        };
        let (id, cmd) = match self.page {
            Page::NewView => (self.views.draft, ViewCommand::Create { prompt, options }),
            Page::View(id) => {
                let session = self
                    .views
                    .session
                    .or_else(|| {
                        self.views
                            .rows
                            .iter()
                            .find(|v| v.id == id)?
                            .turns
                            .last()
                            .map(|t| t.session)
                    })
                    .unwrap_or_else(Uuid::new_v4);
                (
                    id,
                    ViewCommand::Ask {
                        session,
                        prompt,
                        options,
                    },
                )
            }
            _ => return,
        };
        if self.edit_view(id, cmd) {
            self.views.prompt.update(cx, |e, cx| e.set_value("", w, cx));
            // The files went with this request; the next new view stages anew.
            self.views.files.clear();
            self.views.draft = Uuid::new_v4();
            if self.page == Page::NewView {
                self.reload();
                let home = self.new_view_section().map(|s| s.id);
                if home.is_some() {
                    self.move_to_section(&super::sidebar::view_key(id), home, cx);
                }
                self.go(Page::View(id), w, cx);
                self.views.panel = true;
            }
        }
        cx.notify()
    }
    /// Load the models a view can be built with, once per catalogue.
    pub(super) fn ensure_view_models(&mut self, w: &Window, cx: &mut Context<Self>) {
        if std::mem::replace(&mut self.views.models_loaded, true) {
            return;
        }
        let c = self.client().clone();
        self.job(
            async move { c.view_models().await },
            w,
            cx,
            |s, r, _, cx| {
                match r {
                    Ok(catalogue) => {
                        s.views.models.update(cx, |p, cx| {
                            p.set_catalog(super::details::model_groups(&catalogue.models), cx);
                            p.set_trigger(catalogue.models.is_empty(), true, cx);
                        });
                        s.views.catalogue = catalogue;
                    }
                    Err(e) => s.views.models.update(cx, |p, cx| {
                        p.set_catalog_error(format!("{e:#}"), cx);
                        p.set_trigger(false, true, cx);
                    }),
                }
                s.sync_view_selection(cx);
            },
        );
    }
    /// Show the chosen model and the efforts it offers.
    pub(super) fn sync_view_selection(&self, cx: &mut Context<Self>) {
        let chosen = self
            .views
            .catalogue
            .models
            .iter()
            .find(|m| Some(&m.id) == self.views.model.as_ref());
        let effort = meep_shell::model_picker::Effort {
            levels: chosen
                .into_iter()
                .flat_map(|m| &m.supported_efforts)
                .map(|e| (e.clone(), e.clone()))
                .collect(),
            current: self.views.effort.clone(),
            can_reset: true,
            ..Default::default()
        };
        self.views.models.update(cx, |p, cx| {
            p.set_selection(self.views.model.as_deref(), effort, true, cx)
        });
    }
    /// The view a request's files are staged on: the open view, or the one
    /// about to be created.
    fn view_target(&self) -> Option<Uuid> {
        match self.page {
            Page::View(id) => Some(id),
            Page::NewView => Some(self.views.draft),
            _ => None,
        }
    }
    /// Pick files and stage each on the server for the next request.
    pub(super) fn choose_view_files(&mut self, w: &mut Window, cx: &mut Context<Self>) {
        let Some(view) = self.view_target() else {
            return;
        };
        let chosen = cx.prompt_for_paths(PathPromptOptions {
            files: true,
            directories: false,
            multiple: true,
            prompt: Some("Attach".into()),
        });
        self.job(
            async move { chosen.await? },
            w,
            cx,
            move |s, result, w, cx| match result {
                Ok(Some(paths)) if s.view_target() == Some(view) => {
                    s.upload_view_files(view, paths, w, cx)
                }
                Ok(_) => {}
                Err(error) => s.fail(error.context("Meep couldn’t open the file chooser.")),
            },
        );
    }
    pub(super) fn upload_view_files(
        &mut self,
        view: Uuid,
        paths: Vec<std::path::PathBuf>,
        w: &mut Window,
        cx: &mut Context<Self>,
    ) {
        for source in paths {
            let Some(base) = source.file_name().and_then(|n| n.to_str()) else {
                continue;
            };
            // Two files with one name stay apart: "notes 2.txt".
            let mut name = base.to_owned();
            let mut n = 2;
            while self.views.files.contains(&name) {
                let path = std::path::Path::new(base);
                name = match (path.file_stem(), path.extension()) {
                    (Some(stem), Some(ext)) => {
                        format!("{} {n}.{}", stem.to_string_lossy(), ext.to_string_lossy())
                    }
                    _ => format!("{base} {n}"),
                };
                n += 1;
            }
            self.views.files.push(name.clone());
            self.views.uploading += 1;
            let staged = name.clone();
            let c = self.client().clone();
            self.job(
                async move {
                    let bytes = tokio::task::spawn_blocking(move || std::fs::read(&source))
                        .await?
                        .map_err(|e| anyhow::anyhow!("Could not read the file to attach: {e}"))?;
                    c.put_view_file(view, &name, bytes).await?;
                    Ok::<_, anyhow::Error>(name)
                },
                w,
                cx,
                move |s, r, _, cx| {
                    s.views.uploading = s.views.uploading.saturating_sub(1);
                    if let Err(e) = r {
                        // An unstaged file leaves the draft; the error says why.
                        s.views.files.retain(|f| *f != staged);
                        s.fail(e)
                    }
                    cx.notify()
                },
            );
        }
        cx.notify()
    }
    /// Stop the view's running request; the server cancels its PostHog run.
    pub(super) fn stop_view(&mut self, cx: &mut Context<Self>) {
        let Page::View(id) = self.page else {
            return;
        };
        let Some(turn) = self
            .views
            .rows
            .iter()
            .find(|v| v.id == id)
            .and_then(|v| v.pending())
            .map(|t| t.id)
        else {
            return;
        };
        self.edit_view(id, ViewCommand::Stop { turn });
        cx.notify()
    }
    fn edit_view(&mut self, id: Uuid, cmd: ViewCommand) -> bool {
        match self.client().issue_view(id, cmd) {
            Ok(_) => {
                self.reload();
                true
            }
            Err(e) => {
                self.fail(e);
                false
            }
        }
    }
    /// The sidebar section a new view lands in: the one the composer was
    /// opened from, else the first. The hint names it and `send_view` files
    /// the view there, so both always agree.
    fn new_view_section(&self) -> Option<&Section> {
        self.layout.sections.iter().find(|s| s.id == self.section)
    }
    fn new_view_page(&self, w: &Window, cx: &Context<Self>) -> Div {
        let section = self
            .new_view_section()
            .map_or("Lands in the sidebar".to_owned(), |s| {
                format!("Lands in {}", s.name)
            });
        let field = meep_shell::composer::surface(
            self.views.prompt.focus_handle(cx).contains_focused(w, cx),
        )
        .id("new-view-composer")
        .on_action(cx.listener(|s, action: &Enter, w, cx| {
            if !action.shift {
                s.send_view(w, cx);
            }
        }))
        .child(
            meep_shell::composer::input(&self.views.prompt, "What would you like to see?")
                .min_h(px(80.)),
        )
        .child(
            self.view_controls(
                control("create-view", "Create", true, cx, |s, w, cx| {
                    s.send_view(w, cx)
                })
                .disabled(
                    self.views.prompt.read(cx).value().trim().is_empty()
                        || self.views.uploading > 0,
                )
                .into_any_element(),
                cx,
            ),
        );
        // The same hint row, label and suggestion spacing as New topic.
        let hints = ui::row()
            .pt(px(8.))
            .gap(px(8.))
            .child(
                div()
                    .flex_1()
                    .text_size(px(ui::SMALL))
                    .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                    .child(format!("{section}.")),
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
            );
        let mut ideas = ui::column().gap(px(2.)).mx(px(-10.));
        for (i, (glyph, prompt)) in [
            (Glyph::ListChecks, "A launch tracker across my topics"),
            (Glyph::Inbox, "Conversations that need my attention"),
            (Glyph::ChartColumn, "A dashboard of changes in my project"),
        ]
        .into_iter()
        .enumerate()
        {
            ideas = ideas.child(
                starter(format!("view-starter-{i}"), glyph, prompt).on_click(cx.listener(
                    move |s, _, w, cx| {
                        s.views.prompt.update(cx, |e, cx| {
                            e.set_value(prompt, w, cx);
                            e.focus(w, cx)
                        })
                    },
                )),
            );
        }
        let col = ui::column()
            .w_full()
            .max_w(px(480.))
            .gap_0()
            .mb(px(48.))
            // The same mark, title type and spacing as New topic's hero.
            .child(view_mark(36.))
            .child(
                ui::heading("new-view-heading", "Create a view")
                    .mt(px(16.))
                    .text_size(px(20.))
                    .line_height(relative(1.35)),
            )
            .child(
                ui::body(
                    "view-intro",
                    "An agent builds a page from your topics and connected tools.",
                )
                .mt(px(6.))
                .text_size(px(13.))
                .line_height(relative(1.5))
                .text_color(rgb(ui::theme::color(ui::SECONDARY))),
            )
            .child(div().mt(px(20.)).child(field))
            .child(hints)
            .child(
                div()
                    .mt(px(24.))
                    .text_size(px(12.))
                    .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                    .pb(px(4.))
                    .child("Or start from one of these"),
            )
            .child(ideas);
        ui::column()
            .size_full()
            .items_center()
            .justify_center()
            .p(px(24.))
            .child(col)
    }
    pub(super) fn open_view_settings(&mut self, id: Uuid, w: &mut Window, cx: &mut Context<Self>) {
        if let Some(v) = self.views.rows.iter().find(|v| v.id == id) {
            self.name
                .update(cx, |e, cx| e.set_value(v.title.clone(), w, cx));
            self.views.tile = (v.icon.clone(), v.color.clone());
            self.views
                .emoji_query
                .update(cx, |e, cx| e.set_value("", w, cx));
            self.views.confirm_delete = false;
            self.views.settings = true;
        }
    }
    pub(super) fn view_page(&mut self, w: &mut Window, cx: &mut Context<Self>) -> Div {
        let Page::View(id) = self.page else {
            return self.new_view_page(w, cx);
        };
        let Some(v) = self.views.rows.iter().find(|v| v.id == id).cloned() else {
            self.views.leave();
            return ui::column()
                .size_full()
                .items_center()
                .justify_center()
                .child(ui::empty(
                    "View removed",
                    "This page is no longer in your workspace.",
                ));
        };
        let head = self
            .header_row(cx)
            // The same toolbar height and rule as the conversation panel's
            // session header, so both bottom borders share one line.
            .h(px(meep_ui::design::current().toolbar))
            .flex_none()
            .px(px(12.))
            .gap(px(8.))
            .border_b_1()
            .border_color(rgb(ui::theme::color(ui::RULE)))
            .child(meep_shell::icons::window(&v.icon, &v.color, 24.))
            .child(
                div()
                    .flex_1()
                    .truncate()
                    .font_weight(FontWeight::SEMIBOLD)
                    .child(v.title.clone()),
            )
            .child(
                header_toggle(
                    ui::icon_button("view-settings", Glyph::Settings2, "View settings"),
                    Glyph::Settings2,
                    self.views.settings,
                )
                .on_click(cx.listener(move |s, _, w, cx| {
                    if s.views.settings {
                        s.views.settings = false
                    } else {
                        s.open_view_settings(id, w, cx)
                    }
                    cx.notify()
                })),
            )
            .child(
                header_toggle(
                    ui::icon_button("view-agent", Glyph::MessageCircle, "Conversation"),
                    Glyph::MessageCircle,
                    self.views.panel && !self.views.settings,
                )
                .on_click(cx.listener(|s, _, w, cx| {
                    s.views.panel = !s.views.panel;
                    s.views.settings = false;
                    if s.views.panel {
                        s.views.prompt.focus_handle(cx).focus(w, cx)
                    }
                    cx.notify()
                })),
            );
        let body = if self.views.settings {
            self.view_settings(&v, cx).into_any_element()
        } else if let Some(rev) = v.revisions.last() {
            let generation = rev.number.to_string();
            if self.views.mount.as_ref().is_none_or(|m| {
                m.context.revision != generation || m.context.view_id != id.to_string()
            }) {
                let context = ViewContext::new(
                    id.to_string(),
                    json!({}),
                    Arc::new(DataBridge {
                        id,
                        client: self.client().clone(),
                    }),
                    self.rt.clone(),
                    generation,
                    true,
                );
                let result = meep_render::mount(&rev.source, w, cx, context.clone())
                    .map_err(|e| e.to_string());
                self.views.mount = Some(Mount { context, result });
            }
            match &self.views.mount.as_ref().unwrap().result {
                // A centered reading column, the same way settings sits.
                Ok(m) => div()
                    .size_full()
                    .flex()
                    .justify_center()
                    .child(
                        div()
                            .w_full()
                            .max_w(px(720.))
                            .h_full()
                            .min_h_0()
                            .child(m.view.clone()),
                    )
                    .into_any_element(),
                Err(err) => {
                    let summary = meep_render::script_contract::diagnostic_summary(err);
                    ui::column()
                        .size_full()
                        .items_center()
                        .justify_center()
                        .gap(px(8.))
                        .p(px(24.))
                        .child(
                            Icon::new(Glyph::TriangleAlert)
                                .size(px(24.))
                                .text_color(rgb(ui::theme::color(ui::TERTIARY))),
                        )
                        .child(ui::heading("script-error", "This view couldn’t load"))
                        // The raw diagnostic goes only into the fix request.
                        .child(
                            ui::row()
                                .mt(px(6.))
                                .gap(px(8.))
                                .child(control(
                                    "error-ask-fix",
                                    "Ask to fix it",
                                    true,
                                    cx,
                                    move |s, w, cx| s.ask_to_fix_view(&summary, w, cx),
                                ))
                                .child(control(
                                    "error-checkpoints",
                                    "View history",
                                    false,
                                    cx,
                                    move |s, w, cx| s.open_view_settings(id, w, cx),
                                )),
                        )
                        .into_any_element()
                }
            }
        } else {
            building(&v).into_any_element()
        };
        ui::column()
            .size_full()
            .min_w_0()
            .min_h_0()
            .overflow_hidden()
            .child(head)
            .child(
                div()
                    .flex_1()
                    .min_h_0()
                    .size_full()
                    .overflow_hidden()
                    .child(body),
            )
    }
    /// Open the view's conversation with the render error drafted as a request.
    fn ask_to_fix_view(&mut self, error: &str, w: &mut Window, cx: &mut Context<Self>) {
        self.views.settings = false;
        self.views.history = false;
        self.views.panel = true;
        let draft = format!("The view couldn’t render: {error}\nPlease fix it.");
        self.views.prompt.update(cx, |e, cx| {
            e.set_value(draft, w, cx);
            e.focus(w, cx)
        });
        cx.notify()
    }
    pub(super) fn active_view_panel(
        &self,
        w: &mut Window,
        cx: &mut Context<Self>,
    ) -> Option<(f32, f32, Div)> {
        let Page::View(id) = self.page else {
            return None;
        };
        let view = self.views.rows.iter().find(|v| v.id == id)?;
        let wanted = self.identity.is_some() && self.views.panel && !self.views.settings;
        let motion = ui::motion::pane("view-chat-pane", wanted, w, cx);
        if self.identity.is_none() || !motion.should_render() {
            return None;
        }
        let width = meep_shell::agent_panel_width(
            w.viewport_size().width.into(),
            if self.sidebar_hidden {
                0.
            } else {
                super::navigation::TOPIC_SIDEBAR_WIDTH
            },
            None,
        );
        Some((width, motion.progress, self.view_panel(view, w, cx)))
    }
    fn view_panel(&self, v: &View, w: &mut Window, cx: &mut Context<Self>) -> Div {
        let selected = self
            .views
            .session
            .or_else(|| v.turns.last().map(|t| t.session));
        let turns = v
            .turns
            .iter()
            .filter(|t| Some(t.session) == selected)
            .collect::<Vec<_>>();
        let running = turns.last().is_some_and(|t| !t.stage.finished());
        let latest = v.turns.last().map(|t| t.session);
        let heading = if self.views.history {
            "Sessions".to_owned()
        } else if turns.is_empty() {
            "New session".to_owned()
        } else if selected == latest {
            // The current conversation carries the view's name, not a raw prompt.
            v.title.clone()
        } else {
            turns
                .first()
                .map_or_else(String::new, |t| short_title(&t.prompt))
        };
        let chevron = ui::motion::reveal("view-session-history", self.views.history, w, cx);
        let panel = ui::column()
            .min_h_0()
            .child(meep_shell::agent_panel::session_header(
                heading,
                chevron,
                |s, _, cx| {
                    s.views.history = !s.views.history;
                    cx.notify()
                },
                |s, w, cx| {
                    s.views.session = Some(Uuid::new_v4());
                    s.views.history = false;
                    s.views.prompt.update(cx, |e, cx| {
                        e.set_value("", w, cx);
                        e.focus(w, cx)
                    });
                    cx.notify()
                },
                |s, w, cx| {
                    s.views.panel = false;
                    s.focus.focus(w, cx);
                    cx.notify()
                },
                cx,
            ));
        if self.views.history {
            let mut seen = HashSet::new();
            let mut list = scroll("view-sessions").p(px(8.));
            for t in v.turns.iter().filter(|t| seen.insert(t.session)) {
                let session = t.session;
                list = list.child(
                    nav_line(format!("session-{session}"), Some(session) == selected)
                        .child(ui::nav::glyph(Glyph::MessageCircle, false))
                        .child(ui::nav::title(t.prompt.clone()))
                        .on_click(cx.listener(move |s, _, w, cx| {
                            s.views.session = Some(session);
                            s.views.history = false;
                            s.views.prompt.update(cx, |e, cx| e.set_value("", w, cx));
                            cx.notify()
                        })),
                );
            }
            return panel.child(list);
        }
        let mut messages = vec![];
        for t in turns {
            let message = |role: &str, text: String| AgentMessage {
                role: role.into(),
                agent_name: "PostHog Tasks".into(),
                text,
                created_at: t.at.timestamp_millis(),
                ..Default::default()
            };
            messages.push(message("user", t.prompt.clone()));
            messages.extend(t.messages.iter().cloned());
            // Work in flight shows the transcript's working indicator; PostHog's
            // run status ("in_progress") is not a reply. Only a finished turn's
            // result stands in for a reply that never arrived.
            if let Stage::Finished(result) = &t.stage
                && t.messages.last().is_none_or(|m| m.text != *result)
            {
                messages.push(message("assistant", result.clone()));
            }
        }
        let reduced = cx.reduce_motion();
        self.activity
            .update(cx, |a, cx| a.set_active(running, reduced, cx));
        let session = AgentSession {
            id: selected.unwrap_or_default().to_string(),
            view_id: v.id.to_string(),
            topic: None,
            title: v.title.clone(),
            status: if running { "running" } else { "idle" }.into(),
            messages,
            error: None,
            agent_command: "PostHog Tasks".into(),
            provider_session_id: None,
            secure_launcher_version: None,
            model_id: None,
            effort: None,
            approvals: vec![],
        };
        panel
            .child(
                scroll("view-transcript")
                    .flex_1()
                    .p(px(12.))
                    .child(self.chat_transcript(Some(&session), w, cx)),
            )
            .child(
                div()
                    .px(px(10.))
                    .pb(px(10.))
                    .child(self.view_composer(w, cx)),
            )
    }
    /// Below a view request: its attached files, then attach and the model and
    /// effort picker, then the action that sends (or stops) it.
    fn view_controls(&self, action: AnyElement, cx: &Context<Self>) -> Div {
        let has_chips = !self.views.files.is_empty() || self.views.uploading > 0;
        ui::column()
            .w_full()
            .gap(px(6.))
            .when(has_chips, |c| {
                c.child(self.file_chips(&self.views.files, super::details::Attach::View, cx))
            })
            .child(
                ui::row()
                    .gap(px(2.))
                    .child(
                        ui::icon_button("attach-view-files", Glyph::Paperclip, "Attach files")
                            .tooltip("Attach images or text for the agent to use")
                            .on_click(cx.listener(|s, _, w, cx| s.choose_view_files(w, cx))),
                    )
                    .child(
                        div()
                            .min_w_0()
                            .flex_shrink(1.)
                            .child(self.views.models.clone()),
                    )
                    .child(div().flex_1())
                    .child(action),
            )
    }
    /// The view's composer, laid out like a topic's: the draft, its files, the
    /// model and effort the request runs on, and send or stop.
    fn view_composer(&self, w: &mut Window, cx: &mut Context<Self>) -> Stateful<Div> {
        let input = &self.views.prompt;
        w.use_keyed_state(("view-input-events", input.entity_id()), cx, |_, cx| {
            input.update(cx, |e, cx| e.set_submit_on_enter(true, cx));
            cx.subscribe(input, |_: &mut gpui::Subscription, _, event, cx| {
                if matches!(
                    event,
                    meep_ui::gpui_kit::component::input::InputEvent::Change
                        | meep_ui::gpui_kit::component::input::InputEvent::Focus
                        | meep_ui::gpui_kit::component::input::InputEvent::Blur
                ) {
                    cx.notify();
                }
            })
        });
        let empty = input.read(cx).value().trim().is_empty();
        // While a request runs, the send button stops it, as in a topic's chat.
        let running = match self.page {
            Page::View(id) => self
                .views
                .rows
                .iter()
                .find(|v| v.id == id)
                .and_then(|v| v.pending())
                .is_some_and(|t| !t.stop),
            _ => false,
        };
        let action = if running {
            ui::icon_button("stop-view", Glyph::Square, "Stop")
                .tooltip("Stop · cancels the run in PostHog")
                .on_click(cx.listener(|s, _, _, cx| s.stop_view(cx)))
                .into_any_element()
        } else {
            meep_ui::composer::submit("send-chat-message", "Send message")
                .tooltip("Send · ↵")
                .disabled(empty || self.views.uploading > 0)
                .on_click(cx.listener(|s, _, w, cx| s.send_view(w, cx)))
                .into_any_element()
        };
        meep_ui::composer::surface(input.focus_handle(cx).contains_focused(w, cx))
            .id("view-composer")
            .on_action(cx.listener(
                |s, action: &meep_ui::gpui_kit::component::input::Enter, w, cx| {
                    if !action.shift {
                        s.send_view(w, cx);
                    }
                },
            ))
            .child(meep_ui::composer::input(
                input,
                "Ask, or tell it what to do",
            ))
            .child(self.view_controls(action, cx))
    }
    fn view_settings(&self, v: &View, cx: &Context<Self>) -> Stateful<Div> {
        let id = v.id;
        let (emoji, color) = &self.views.tile;
        let catalog = meep_render::emoji::catalog();
        let q = self.views.emoji_query.read(cx).value();
        let choices = if q.trim().is_empty() {
            [
                "✨", "🚀", "📊", "🗂️", "📌", "📅", "🌿", "📝", "💡", "🔭", "🧭", "🎯",
            ]
            .into_iter()
            .map(str::to_owned)
            .collect::<Vec<_>>()
        } else {
            catalog
                .search(q.as_ref())
                .iter()
                .take(24)
                .map(|i| catalog.entries[*i].emoji.to_owned())
                .collect()
        };
        // Colors and emoji share one grid: same cell, same gap, same left edge.
        const CELL: f32 = 34.;
        const GAP: f32 = 6.;
        let mut tiles = ui::row().flex_wrap().gap(px(GAP));
        let accent = rgb(ui::theme::color(ui::theme::DEFAULT[10]));
        for (i, icon) in choices.into_iter().enumerate() {
            let chosen = icon == *emoji;
            tiles = tiles.child(
                div()
                    .id(("emoji", i))
                    .size(px(CELL))
                    .flex()
                    .items_center()
                    .justify_center()
                    .border_2()
                    .rounded(px(12.))
                    .border_color(if chosen {
                        accent
                    } else {
                        gpui::transparent_black().into()
                    })
                    .cursor_pointer()
                    .child(meep_shell::icons::icon(&icon, color, 28.))
                    .on_click(cx.listener(move |s, _, _, cx| {
                        s.views.tile.0 = icon.clone();
                        cx.notify()
                    })),
            );
        }
        let palettes = ui::row().gap(px(GAP)).children(
            ["ink", "orange", "teal", "plum", "mustard", "moss", "brick"].map(|c| {
                div()
                    .id(c)
                    .size(px(CELL))
                    .flex()
                    .items_center()
                    .justify_center()
                    .rounded_full()
                    .border_2()
                    .border_color(if color == c {
                        rgb(ui::theme::color(ui::INK))
                    } else {
                        gpui::transparent_black().into()
                    })
                    .cursor_pointer()
                    .child(
                        div()
                            .size(px(22.))
                            .rounded_full()
                            .bg(rgb(meep_shell::icons::inks(c).1)),
                    )
                    .on_click(cx.listener(move |s, _, _, cx| {
                        s.views.tile.1 = c.into();
                        cx.notify()
                    }))
            }),
        );
        use meep_shell::settings::{ROW_X, danger, empty, group, item, section};
        let changed =
            self.name.read(cx).value().trim() != v.title || *emoji != v.icon || *color != v.color;
        let save = control("save-view", "Save changes", true, cx, move |s, _, cx| {
            let cmd = ViewCommand::Settings {
                title: s.name.read(cx).value().into(),
                icon: s.views.tile.0.clone(),
                color: s.views.tile.1.clone(),
            };
            if s.edit_view(id, cmd) {
                s.views.settings = false;
            }
        })
        .disabled(!changed);
        let mut settings = ui::column()
            .max_w(px(510.))
            .w_full()
            .gap_0()
            .child(
                ui::heading("view-settings-title", "View settings")
                    .text_size(px(22.))
                    .line_height(px(28.))
                    .pb(px(28.)),
            )
            .child(section("Name and icon", "", None, true))
            .child(group([
                item("Name", "", div().w(px(260.)).child(Input::new(&self.name)))
                    .into_any_element(),
                // Colors start at the left edge with the emoji grid below them.
                ui::column()
                    .px(px(ROW_X))
                    .py(px(12.))
                    .gap(px(10.))
                    .child(
                        ui::row()
                            .gap(px(10.))
                            .child(meep_shell::icons::window(emoji, color, 44.))
                            .child(
                                div().flex_1().child(
                                    Input::new(&self.views.emoji_query).prefix(
                                        Icon::new(Glyph::Search)
                                            .size(px(14.))
                                            .text_color(rgb(ui::theme::color(ui::SECONDARY))),
                                    ),
                                ),
                            ),
                    )
                    .child(palettes)
                    .child(tiles)
                    .into_any_element(),
                ui::row()
                    .justify_end()
                    .px(px(ROW_X))
                    .py(px(10.))
                    .child(save)
                    .into_any_element(),
            ]))
            .child(section("Version history", "", None, false));
        let expected = v.generation();
        if expected == 0 {
            settings = settings.child(empty(
                "No versions yet",
                "The first checkpoint appears when the agent publishes the view.",
            ));
        } else {
            let rows = v.revisions.iter().rev().map(|r| {
                let n = r.number;
                let when =
                    r.at.with_timezone(&chrono::Local)
                        .format("%b %-d · %H:%M")
                        .to_string();
                let trailing = if n == expected {
                    div()
                        .flex_none()
                        .px(px(6.))
                        .py(px(1.))
                        .rounded(px(4.))
                        .bg(ui::ink(0x0c))
                        .text_size(px(11.))
                        .font_weight(FontWeight::MEDIUM)
                        .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                        .child("Current")
                        .into_any_element()
                } else {
                    control(
                        format!("restore-{n}"),
                        "Restore",
                        false,
                        cx,
                        move |s, _, _| {
                            s.edit_view(
                                id,
                                ViewCommand::Restore {
                                    number: n,
                                    expected,
                                },
                            );
                        },
                    )
                    .into_any_element()
                };
                item(format!("Version {n}"), when, trailing).into_any_element()
            });
            settings = settings.child(group(rows));
        }
        let delete = if self.views.confirm_delete {
            ui::row()
                .gap(px(8.))
                .child(control(
                    "cancel-delete-view",
                    "Cancel",
                    false,
                    cx,
                    |s, _, _| s.views.confirm_delete = false,
                ))
                .child(danger(
                    control(
                        "delete-view",
                        "Confirm deletion",
                        true,
                        cx,
                        move |s, w, cx| {
                            if s.edit_view(id, ViewCommand::Delete) {
                                s.go(Page::Needs, w, cx)
                            }
                        },
                    ),
                    cx,
                ))
                .into_any_element()
        } else {
            let tone = rgb(ui::theme::color(ui::DANGER));
            control("delete-view", "Delete view", false, cx, |s, _, _| {
                s.views.confirm_delete = true
            })
            .text_color(tone)
            .border_color(gpui::Rgba { a: 0.45, ..tone })
            .into_any_element()
        };
        settings = settings.child(
            div().pt(px(16.)).child(group([item(
                "Delete this view permanently",
                "Removes the page and its version history.",
                delete,
            )
            .into_any_element()])),
        );
        ui::column()
            .id("view-settings-scroll")
            .size_full()
            .overflow_y_scroll()
            .items_center()
            .p(px(28.))
            .child(settings)
    }
}
/// A session's first prompt, shortened to a title.
fn short_title(prompt: &str) -> String {
    let line = prompt.lines().next().unwrap_or_default().trim();
    if line.chars().count() <= 48 {
        return line.to_owned();
    }
    let cut: String = line.chars().take(47).collect();
    format!("{}…", cut.trim_end())
}
/// A header icon button at the shared 16pt glyph size, filled while its pane is open.
fn header_toggle(button: Button, glyph: Glyph, on: bool) -> Button {
    let icon = Icon::new(glyph).size(px(16.));
    if on {
        button
            .icon(icon.text_color(rgb(ui::theme::color(ui::INK))))
            .bg(ui::ink(0x0c))
    } else {
        button.icon(icon)
    }
}
/// New view's mark: New topic's tile with the views glyph.
fn view_mark(size: f32) -> Div {
    div()
        .flex_none()
        .size(px(size))
        .rounded(px(size * 0.27))
        .bg(ui::ink(0x0b))
        .flex()
        .items_center()
        .justify_center()
        .child(
            Icon::new(Glyph::LayoutDashboard)
                .size(px(size * 0.56))
                .text_color(rgb(ui::theme::color(ui::SECONDARY))),
        )
}
fn building(v: &View) -> Div {
    let bar = |x, y| div().w(relative(x)).h(px(y)).rounded_full().bg(ui::ink(28));
    let outline = ui::column()
        .w_full()
        .p(px(20.))
        .gap(px(10.))
        .rounded(px(12.))
        .border_1()
        .border_color(ui::ink(16))
        .child(bar(0.42, 12.))
        .child(bar(0.7, 8.))
        .child(div().h(px(6.)))
        .children([0.82, 0.64, 0.74].map(|w| {
            ui::row()
                .gap(px(10.))
                .child(bar(0.035, 10.))
                .child(bar(w, 8.))
        }));
    let current = v.turns.last();
    let running = current.is_some_and(|t| !t.stage.finished());
    let outline = if running {
        outline
            .with_animation(
                "building-outline",
                Animation::new(std::time::Duration::from_millis(1800))
                    .repeat()
                    .with_easing(pulsating_between(0.6, 1.)),
                |el, t| el.opacity(t),
            )
            .into_any_element()
    } else {
        outline.into_any_element()
    };
    ui::column()
        .size_full()
        .items_center()
        .justify_center()
        .child(
            ui::column()
                .w_full()
                .max_w(px(360.))
                .mb(px(48.))
                .items_center()
                .child(outline)
                .when_some(
                    current.map(|t| t.prompt.clone()).filter(|p| !p.is_empty()),
                    |c, prompt| {
                        // What was asked, as a quiet caption under the outline;
                        // the header carries the name.
                        c.child(ui::caption(prompt).mt(px(20.)).text_center().line_clamp(3))
                    },
                )
                .child(
                    ui::row()
                        .mt(px(10.))
                        .gap(px(8.))
                        .justify_center()
                        .when(running, |r| {
                            r.child(meep_ui::gpui_kit::component::spinner::Spinner::new().small())
                        })
                        .child(ui::caption(
                            current.map(|t| progress(&t.stage)).unwrap_or_default(),
                        )),
                ),
        )
}
