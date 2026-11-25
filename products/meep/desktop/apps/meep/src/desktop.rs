use super::*;
use std::collections::BTreeSet;
use tokio::sync::broadcast::error::RecvError;

/// What fills a topic's main pane. The conversation is home; every other
/// section opens in its place from the Overview, under a breadcrumb.
#[derive(Default, Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub(super) enum Tab {
    #[default]
    Chat,
    Needs,
    Inbox,
    Tasks,
    /// Saved layouts from before the rename say `Data`.
    #[serde(alias = "Data")]
    Files,
    Routines,
    Mission,
    Goals,
    Facts,
    /// Passive context references.
    Linked,
    Rules,
}
impl Tab {
    /// The Overview's sections, top to bottom.
    pub(super) const OVERVIEW: [Self; 10] = [
        Self::Needs,
        Self::Tasks,
        Self::Inbox,
        Self::Files,
        Self::Routines,
        Self::Mission,
        Self::Goals,
        Self::Facts,
        Self::Linked,
        Self::Rules,
    ];
    pub(super) fn label(self) -> &'static str {
        match self {
            Self::Chat => "Chat",
            Self::Needs => "Needs you",
            Self::Inbox => "Inbox",
            Self::Tasks => "Tasks",
            Self::Files => "Files",
            Self::Routines => "Routines",
            Self::Mission => "Mission",
            Self::Goals => "Goals",
            Self::Facts => "Facts",
            Self::Linked => "Linked",
            Self::Rules => "Rules",
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub(super) enum Detail {
    Goal(GoalId),
    /// A linked context source, by its watch key.
    Linked(String),
    Thread(ThreadId),
    Task(TaskId),
    Fact(FactId),
    File(String),
    Table(String),
    Routine(String),
    Problem(String),
}
/// Scroll state and measurements for the current topic's conversation.
pub(super) struct TopicChatList {
    pub topic: TopicId,
    pub list: ListState,
    pub messages: Vec<meep_protocol::sessions::AgentMessage>,
    pub linked: Option<TaskId>,
    pub running: bool,
    /// Keep selected text mounted until the selection is cleared.
    pub full_selection: bool,
    /// Row bounds preserve the reader's place when changing selection mode.
    pub selection_rows: Vec<std::rc::Rc<std::cell::Cell<Bounds<Pixels>>>>,
}

pub(super) struct PendingTurn {
    pub message: meep_protocol::sessions::AgentMessage,
    pub after_messages: usize,
    pub previous_matches: usize,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub(super) enum Page {
    #[default]
    Needs,
    NewView,
    View(Uuid),
    Topic(TopicId, Tab, Option<Detail>),
    Settings,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub(super) enum Sheet {
    New,
    Search,
    Bind,
    RenameTopic(TopicId),
    DeleteTopic(TopicId),
    DeleteRoutine(TopicId, String, Uuid),
}
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub(super) struct Section {
    pub id: Uuid,
    pub name: String,
    pub collapsed: bool,
    /// Topic and view keys in this section, top to bottom.
    #[serde(default)]
    pub items: Vec<String>,
}
/// The sidebar's arrangement, kept on this Mac: loose items above the
/// sections, then each section's items. See `sidebar.rs`.
#[derive(Default, Clone, Serialize, Deserialize)]
pub(super) struct Layout {
    pub sections: Vec<Section>,
    /// Items in no section, in their order.
    #[serde(default)]
    pub loose: Vec<String>,
    /// Older layouts: each topic's section. Read once by `migrate`.
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub homes: BTreeMap<TopicId, Uuid>,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub view_homes: BTreeMap<Uuid, Uuid>,
    /// Whether the older homes have been folded into the sections.
    #[serde(default)]
    pub arranged: bool,
}
/// Destinations in the settings sidebar.
#[derive(Clone, Copy, PartialEq, Eq)]
pub(super) enum SettingsPage {
    General,
    Connections,
    Notifications,
    Permissions,
    Shortcuts,
    Advanced,
    Appearance,
}
impl SettingsPage {
    pub(super) const ALL: [Self; 7] = [
        Self::General,
        Self::Connections,
        Self::Notifications,
        Self::Permissions,
        Self::Appearance,
        Self::Shortcuts,
        Self::Advanced,
    ];
    pub(super) fn title(self) -> &'static str {
        match self {
            Self::General => "General",
            Self::Connections => "MCP servers",
            Self::Notifications => "Notifications",
            Self::Shortcuts => "Shortcuts",
            Self::Permissions => "Permissions",
            Self::Advanced => "Advanced",
            Self::Appearance => "Appearance",
        }
    }
    pub(super) fn glyph(self) -> Glyph {
        match self {
            Self::General => Glyph::CircleUser,
            Self::Connections => Glyph::Plug,
            Self::Notifications => Glyph::Bell,
            Self::Shortcuts => Glyph::Keyboard,
            Self::Permissions => Glyph::Shield,
            Self::Advanced => Glyph::Wrench,
            Self::Appearance => Glyph::Palette,
        }
    }
}
pub(super) struct Desktop {
    pub views: super::views::ViewWorkspace,
    pub mcp: super::mcp_settings::McpSettings,
    pub alerts: super::preferences::Alerts,
    pub clear_confirm: bool,
    pub settings_page: SettingsPage,
    /// Whether the user has hidden the sidebar with the titlebar toggle.
    pub sidebar_hidden: bool,
    pub backend: Backend,
    pub rt: Arc<Runtime>,
    pub identity: Option<Identity>,
    pub region: Region,
    pub scheme: Option<String>,
    pub login_busy: bool,
    pub states: Vec<TopicState>,
    pub needs: Vec<NeedsYouItem>,
    /// Service names from the replica, keyed by connection ID.
    pub services: BTreeMap<String, String>,
    pub layout: Layout,
    pub page: Page,
    pub back: Vec<Page>,
    pub focus: FocusHandle,
    pub sheet: Option<Sheet>,
    pub menu: bool,
    pub section: Uuid,
    /// Where a sidebar drag would land, and what is being dragged.
    pub drop_hint: Option<super::sidebar::Drop>,
    /// How the Tasks tab shows its work.
    pub task_display: super::tasks_view::TaskDisplay,
    /// Whether the sidebar's Archived group is open. Closed by default.
    pub archived_open: bool,
    /// Task groups folded or unfolded against their default.
    pub toggled_groups: std::collections::BTreeSet<String>,
    pub drag_source: Option<String>,
    /// The section being renamed in place, and its name field.
    pub renaming_section: Option<Uuid>,
    pub section_name: Entity<InputState>,
    /// The Overview beside a topic: whether it is tucked away, and which of
    /// its sections are folded open.
    pub overview_hidden: bool,
    /// In a narrow window, whether the Overview is shown over the page.
    pub overview_overlay: bool,
    pub overview_open: BTreeSet<(TopicId, Tab)>,
    /// Topics whose “needs you” briefing was put away this session.
    pub briefing_dismissed: BTreeSet<TopicId>,
    pub files: bool,
    pub folder: Option<String>,
    /// Each topic's task artifacts, listed live from PostHog.
    pub artifacts: std::collections::HashMap<TopicId, Result<Vec<meep_wire::TaskArtifact>, String>>,
    /// When each topic's artifacts were last listed.
    pub artifacts_at: std::collections::HashMap<TopicId, std::time::Instant>,
    /// The open artifact's cache key and bytes; an empty error while fetching.
    pub artifact_open: Option<(String, Result<Vec<u8>, String>)>,
    /// Folders in the Files tree the person opened or closed, against the default.
    pub file_folders: std::collections::HashMap<TopicId, std::collections::BTreeSet<String>>,
    pub chat_reference: Option<String>,
    /// Topic files uploaded from the composer, sent with the next message.
    pub chat_files: Vec<String>,
    /// Uploads from the composer still being read or saved.
    pub chat_uploading: usize,
    /// Model choice for the topic chat, fed by the topic's PostHog catalogue.
    pub chat_models: Entity<meep_shell::model_picker::ModelPicker>,
    /// Topic whose model catalogue the picker holds or is loading.
    pub chat_models_topic: std::cell::Cell<Option<TopicId>>,
    /// When the catalogue last failed to load; the chat retries a few seconds later,
    /// for example once a new topic's PostHog grant lands.
    pub chat_models_failed: std::cell::Cell<Option<std::time::Instant>>,
    /// Routine templates offered by the server, loading while `None`.
    pub templates: Option<Result<Vec<meep_wire::RoutineTemplate>, String>>,
    /// The New routine composer replaces the routine list while open.
    pub new_routine: bool,
    /// Template whose text fills the routine composer, used if left unchanged.
    pub routine_template: Option<String>,
    /// Template being created, so the composer shows progress.
    pub creating_template: Option<String>,
    pub skipped: bool,
    pub done: bool,
    pub adding: bool,
    /// The next added task goes to the agent instead of the person.
    pub task_for_agent: bool,
    pub editing: bool,
    pub send_back: bool,
    pub search_index: usize,
    /// Keeps the highlighted search result inside the visible list.
    pub search_scroll: ScrollHandle,
    /// Vertical viewport for topic rows.
    pub content_scroll: ScrollHandle,
    /// Horizontal viewport for task columns.
    pub board_scroll: ScrollHandle,
    /// Rendered bounds of the selected inbox row, card or routine.
    pub selection_bounds: ScrollHandle,
    /// Scroll the next keyboard selection into view after layout.
    pub reveal_selection: bool,
    /// Editor to refocus after dismissing a sheet.
    pub sheet_return_focus: Option<FocusHandle>,
    pub just_approved: Option<(TopicId, TaskId, RuleId)>,
    pub(super) editing_review: Option<(TopicId, TaskId, u64)>,
    /// Dedicated query editor for the global search sheet.
    pub search: Entity<InputState>,
    pub name: Entity<InputState>,
    /// Public HTTPS address typed in Advanced settings.
    pub public_url: Entity<InputState>,
    /// Outcome of the last public address save.
    pub public_url_note: Option<String>,
    /// Inline board editor, independently of the new-topic sheet.
    pub routine_prompt: Entity<TextareaState>,
    /// Follow-up question about the open handled thread.
    pub run_input: Entity<TextareaState>,
    pub run_revision: u64,
    pub run_status: String,
    pub run_messages: Vec<meep_protocol::sessions::AgentMessage>,
    pub run_notice: Option<String>,
    pub sending_runs: HashSet<TaskId>,
    pub run_scroll: ScrollHandle,
    pub chat_list: std::cell::RefCell<Option<TopicChatList>>,
    pub pending_turns: std::collections::HashMap<TaskId, Vec<PendingTurn>>,
    pub run_models: Entity<meep_shell::model_picker::ModelPicker>,
    pub run_model: Option<String>,
    pub run_files: Vec<String>,
    /// Files attached to the task being created.
    pub task_files: Vec<String>,
    pub task_description: Entity<TextareaState>,
    pub task_models: Entity<meep_shell::model_picker::ModelPicker>,
    pub catalogue: meep_wire::ChatModels,
    pub billing: Option<String>,
    pub task_model: Option<String>,
    pub task_effort: Option<String>,
    pub mission: Entity<TextareaState>,
    /// Single-line editor for the existing topic mission.
    pub mission_edit: Entity<TextareaState>,
    /// Feedback to send with a task returned for revision.
    pub note: Entity<TextareaState>,
    pub draft: Entity<TextareaState>,
    pub composer: Entity<TextareaState>,
    pub error: Option<String>,
    pub expanded: HashSet<String>,
    pub activity: Entity<ActivityIndicator>,
    /// Spins in a sidebar row while that topic's or view's agent works.
    pub sidebar_activity: Entity<ActivityIndicator>,
    /// The topic status card shown beside a hovered sidebar row.
    pub topic_card: super::topic_card::TopicCard,
    sync: tokio::task::JoinHandle<()>,
}

impl Drop for Desktop {
    fn drop(&mut self) {
        self.sync.abort();
    }
}
impl Desktop {
    pub(super) fn new(
        backend: Backend,
        rt: Arc<Runtime>,
        notice: Option<String>,
        w: &mut Window,
        cx: &mut Context<Self>,
    ) -> Self {
        let client = backend.client.clone();
        let focus = cx.focus_handle();
        focus.focus(w, cx);
        cx.observe_window_appearance(w, |s: &mut Self, w, cx| {
            meep_shell::appearance::set_palette(
                meep_shell::appearance::resolve(s.scheme.as_deref(), w.appearance()),
                cx,
            );
            cx.notify()
        })
        .detach();
        cx.observe_window_activation(w, |s: &mut Self, w, cx| {
            if w.is_window_active()
                && s.page == Page::Settings
                && s.settings_page == SettingsPage::Connections
                && s.mcp.screen == super::mcp_settings::Screen::List
            {
                s.mcp_request(meep_wire::mcp_store::Operation::Browse, w, cx);
            }
        })
        .detach();
        let mut events = client.subscribe();
        cx.spawn_in(w, async move |this, cx| {
            loop {
                let event = events.recv().await;
                if matches!(event, Err(RecvError::Closed)) {
                    break;
                }
                if this
                    .update_in(cx, |s, w, cx| {
                        let topic_changed = matches!(
                            event,
                            Ok(meep_client::Event::TopicChanged(_)) | Err(RecvError::Lagged(_))
                        );
                        let previous = s.needs.clone();
                        match event {
                            Ok(meep_client::Event::TopicChanged(id)) => {
                                s.reload_topic(id);
                                if s.topic_id() == Some(id) {
                                    s.load_run(w, cx);
                                }
                            }
                            Ok(meep_client::Event::ViewsChanged) => s.reload_views(),
                            Err(RecvError::Lagged(_)) => {
                                s.reload();
                                s.load_run(w, cx);
                            }
                            _ => s.reload_attention(),
                        }
                        s.deliver_alerts(&previous, w, cx);
                        if topic_changed {
                            s.views.refresh(w, cx);
                        }
                        cx.notify();
                    })
                    .is_err()
                {
                    break;
                }
            }
        })
        .detach();
        let sync = rt.spawn(async move {
            if let Err(error) = client.run().await {
                eprintln!("Topics synchronization stopped: {error}");
            }
        });
        let search = cx.new(|cx| InputState::new(w, cx).placeholder("Search Meep"));
        let name = cx.new(|cx| InputState::new(w, cx));
        let public_url =
            cx.new(|cx| InputState::new(w, cx).placeholder("https://meep.example.com"));
        let mission = cx.new(|cx| {
            TextareaState::new(w, cx)
                .auto_grow(2, 5)
                .placeholder("What should it get done?")
        });
        let draft = cx.new(|cx| TextareaState::new(w, cx).auto_grow(2, 30));
        let composer = cx.new(|cx| {
            let mut input = TextareaState::new(w, cx)
                .auto_grow(2, 5)
                .placeholder("Ask, or tell it what to do");
            input.set_submit_on_enter(true, cx);
            input
        });
        cx.subscribe(&search, |s: &mut Self, _, e: &InputEvent, cx| {
            if matches!(e, InputEvent::Change) {
                s.search_index = 0;
                s.search_scroll.scroll_to_item(0);
                cx.notify()
            }
        })
        .detach();
        cx.subscribe(&name, |_: &mut Self, _, _: &InputEvent, cx| cx.notify())
            .detach();
        cx.subscribe(&composer, |_: &mut Self, _, _: &InputEvent, cx| cx.notify())
            .detach();
        let chat_models = cx
            .new(|cx| meep_shell::model_picker::ModelPicker::new(composer.focus_handle(cx), w, cx));
        cx.subscribe_in(&chat_models, w, |s: &mut Self, _, change, w, cx| {
            s.chat_model_changed(change, w, cx)
        })
        .detach();
        let run_input = cx.new(|cx| {
            let mut e = TextareaState::new(w, cx)
                .auto_grow(1, 5)
                .placeholder("Message the agent");
            e.set_submit_on_enter(true, cx);
            e
        });
        cx.subscribe(&run_input, |_: &mut Self, _, _: &InputEvent, cx| {
            cx.notify()
        })
        .detach();
        let run_models = cx.new(|cx| {
            meep_shell::model_picker::ModelPicker::new(run_input.focus_handle(cx), w, cx)
        });
        cx.subscribe_in(&run_models, w, |s: &mut Self, _, change, w, cx| {
            use meep_shell::model_picker::Change;
            let Some((topic, _)) = s.chat_task() else {
                return;
            };
            match change {
                Change::Model(model) => s.run_model = model.clone(),
                Change::Refresh => s.load_chat_models(topic, w, cx),
                Change::Recover => s.connect_model_topic(topic, w, cx),
                Change::Effort(_) => {}
            }
            cx.notify();
        })
        .detach();
        // A new task is just its brief: PostHog names it when it starts.
        let task_description = cx.new(|cx| {
            let mut input = TextareaState::new(w, cx)
                .auto_grow(3, 8)
                .placeholder("What should the agent do?");
            input.set_submit_on_enter(true, cx);
            input
        });
        cx.subscribe(&task_description, |_: &mut Self, _, _: &InputEvent, cx| {
            cx.notify()
        })
        .detach();
        let section_name = cx.new(|cx| InputState::new(w, cx));
        // Enter keeps the new name, Esc keeps the old one, and leaving the field keeps it too.
        cx.subscribe_in(
            &section_name,
            w,
            |s: &mut Self, _, e: &InputEvent, w, cx| match e {
                InputEvent::PressEnter { .. } => s.finish_section_rename(true, w, cx),
                InputEvent::Blur => s.finish_section_rename(true, w, cx),
                _ => {}
            },
        )
        .detach();
        let task_models = cx.new(|cx| {
            meep_shell::model_picker::ModelPicker::new(task_description.focus_handle(cx), w, cx)
        });
        cx.subscribe_in(&task_models, w, |s: &mut Self, _, change, w, cx| {
            use meep_shell::model_picker::Change;
            match change {
                Change::Model(model) => {
                    s.task_model = model.clone();
                    s.task_effort = None;
                    s.billing = None;
                }
                Change::Effort(effort) => s.task_effort = effort.clone(),
                Change::Recover => {
                    if let Some(id) = s.topic_id()
                        && s.chat_models_topic.get() == Some(id)
                    {
                        s.connect_model_topic(id, w, cx);
                    }
                }
                Change::Refresh => {
                    if let Some(id) = s.topic_id() {
                        s.load_chat_models(id, w, cx);
                    }
                }
            }
            s.sync_task_selection(cx);
        })
        .detach();
        let mut s = Self {
            backend,
            rt,
            identity: None,
            region: Region::Us,
            scheme: None,
            login_busy: false,
            views: super::views::ViewWorkspace::new(w, cx),
            states: vec![],
            needs: vec![],
            services: BTreeMap::new(),
            layout: Layout::default(),
            page: Page::Needs,
            back: vec![],
            focus,
            sheet: None,
            menu: false,
            mcp: super::mcp_settings::McpSettings::new(w, cx),
            alerts: Default::default(),
            clear_confirm: false,
            settings_page: SettingsPage::General,
            sidebar_hidden: false,
            section: Uuid::nil(),
            drop_hint: None,
            task_display: Default::default(),
            archived_open: false,
            toggled_groups: Default::default(),
            drag_source: None,
            renaming_section: None,
            section_name,
            overview_hidden: false,
            overview_overlay: false,
            overview_open: BTreeSet::new(),
            briefing_dismissed: BTreeSet::new(),
            files: false,
            folder: None,
            artifacts: Default::default(),
            artifacts_at: Default::default(),
            artifact_open: None,
            file_folders: Default::default(),
            chat_reference: None,
            chat_files: vec![],
            chat_uploading: 0,
            chat_models,
            chat_models_topic: Default::default(),
            chat_models_failed: Default::default(),
            templates: None,
            new_routine: false,
            routine_template: None,
            creating_template: None,
            skipped: false,
            done: false,
            adding: false,
            task_for_agent: false,
            editing: false,
            send_back: false,
            search_index: 0,
            search_scroll: ScrollHandle::new(),
            content_scroll: ScrollHandle::new(),
            board_scroll: ScrollHandle::new(),
            selection_bounds: ScrollHandle::new(),
            reveal_selection: false,
            sheet_return_focus: None,
            just_approved: None,
            editing_review: None,
            search,
            name,
            public_url,
            public_url_note: None,
            routine_prompt: cx.new(|cx| {
                let mut input = TextareaState::new(w, cx).auto_grow(2, 5);
                input.set_placeholder("Describe the routine…", w, cx);
                input.set_submit_on_enter(true, cx);
                input
            }),
            task_models,
            catalogue: Default::default(),
            billing: None,
            task_model: None,
            task_effort: None,
            run_revision: 0,
            run_status: String::new(),
            run_input,
            run_messages: vec![],
            run_notice: None,
            sending_runs: Default::default(),
            run_scroll: ScrollHandle::new(),
            chat_list: std::cell::RefCell::new(None),
            pending_turns: Default::default(),
            run_models,
            run_model: None,
            run_files: vec![],
            task_files: vec![],
            task_description,
            mission,
            mission_edit: cx.new(|cx| {
                // Long goals wrap instead of scrolling out of a one-line field.
                let mut input = TextareaState::new(w, cx).auto_grow(1, 4);
                input.set_submit_on_enter(true, cx);
                input
            }),
            note: cx.new(|cx| {
                TextareaState::new(w, cx)
                    .auto_grow(2, 8)
                    .placeholder("Describe the change you need")
            }),
            draft,
            composer,
            error: notice,
            expanded: Default::default(),
            activity: cx.new(|_| ActivityIndicator::default()),
            sidebar_activity: cx.new(|_| ActivityIndicator::sidebar()),
            topic_card: Default::default(),
            sync,
        };
        if let Err(e) = s.restore() {
            s.fail(e)
        }
        meep_shell::appearance::set_palette(
            meep_shell::appearance::resolve(s.scheme.as_deref(), w.appearance()),
            cx,
        );
        s.reload();
        s
    }
    fn restore(&mut self) -> Result<()> {
        self.scheme = self
            .client()
            .preference::<Option<String>>("appearance")?
            .flatten();
        self.alerts = self
            .client()
            .preference("notifications")?
            .unwrap_or_default();
        self.task_display = self
            .client()
            .preference("task-display")?
            .unwrap_or_default();
        self.archived_open = self
            .client()
            .preference("sidebar-archived-open")?
            .unwrap_or(false);
        self.layout = self
            .client()
            .preference::<Layout>("sidebar")?
            .map(Layout::migrate)
            .unwrap_or(Layout {
                arranged: true,
                ..Default::default()
            });
        if self.client().preference("signed-in")? == Some(true) {
            self.identity = self.client().preference("posthog-project")?;
        }
        self.region = self
            .identity
            .as_ref()
            .map(|a| a.region)
            .unwrap_or(self.client().preference("region")?.unwrap_or_default());
        Ok(())
    }
    pub(super) fn client(&self) -> &Client {
        &self.backend.client
    }
    pub(super) fn reload(&mut self) {
        // Archived topics stay in the sidebar's Archived group, where they can be restored.
        match self.client().topics().and_then(|mut v| {
            v.extend(self.client().archived_topics()?);
            v.sort_by_key(|s| s.topic.id);
            Ok(v)
        }) {
            Ok(states) => self.states = states,
            Err(e) => self.fail(e),
        }
        self.reload_views();
        self.reload_attention();
    }

    fn reload_topic(&mut self, id: TopicId) {
        match self.client().topic(id) {
            Ok(topic) => {
                let topic = topic.filter(|t| !t.deleted);
                match (self.states.binary_search_by_key(&id, |s| s.topic.id), topic) {
                    (Ok(i), Some(t)) => self.states[i] = t,
                    (Err(i), Some(t)) => self.states.insert(i, t),
                    (Ok(i), None) => {
                        self.states.remove(i);
                    }
                    (Err(_), None) => {}
                }
            }
            Err(e) => self.fail(e),
        }
        self.reload_attention();
    }

    fn reload_views(&mut self) {
        match self.client().views() {
            Ok(rows) => self.views.rows = rows.into_iter().map(Arc::new).collect(),
            Err(e) => self.fail(e),
        }
    }

    fn reload_attention(&mut self) {
        if let Ok(list) = self.client().connections() {
            self.services = list
                .connections
                .into_iter()
                .map(|c| (c.id, c.label))
                .collect();
        }
        match self.client().needs_you_for(&self.states) {
            Ok(items) => self.needs = items.items,
            Err(e) => self.fail(e),
        }
    }
    pub(super) fn save_layout(&mut self) {
        if let Err(e) = self.client().set_preference("sidebar", &self.layout) {
            self.fail(e)
        }
    }
    pub(super) fn issue(&mut self, id: TopicId, cmd: Command) -> bool {
        match self.client().issue(id, cmd) {
            Ok(_) => {
                self.reload_topic(id);
                true
            }
            Err(e) => {
                self.fail(e);
                false
            }
        }
    }
    pub(super) fn job<T: Send + 'static>(
        &self,
        job: impl Future<Output = Result<T>> + Send + 'static,
        w: &Window,
        cx: &mut Context<Self>,
        done: impl FnOnce(&mut Self, Result<T>, &mut Window, &mut Context<Self>) + 'static,
    ) {
        let handle = self.rt.spawn(job);
        cx.spawn_in(w, async move |this, cx| {
            let res = handle.await.map_err(anyhow::Error::from).and_then(|r| r);
            let _ = this.update_in(cx, |s, w, cx| {
                done(s, res, w, cx);
                cx.notify()
            });
        })
        .detach()
    }
    /// Send the typed key (or clear it) to the server; the field empties either way.
    pub(super) fn save_public_url(&mut self, w: &mut Window, cx: &mut Context<Self>) {
        let base = self.public_url.read(cx).value().trim().to_owned();
        if base.is_empty() {
            return;
        }
        let c = self.client().clone();
        self.job(
            async move { c.set_public_base_url(&base).await },
            w,
            cx,
            |s, r, _, _| {
                // Which models get Meep tools depends on the address; load them again.
                if r.is_ok() {
                    s.chat_models_topic.set(None);
                }
                s.public_url_note = Some(match r {
                    Ok(a) => format!(
                        "Saved. PostHog will reach this server at {}.",
                        a.public_base_url
                    ),
                    Err(e) => e.to_string(),
                })
            },
        );
    }
    /// Report a failure to the person. A server that is briefly unreachable is
    /// not news: the sidebar already says offline and work resumes on its own.
    pub(super) fn fail(&mut self, e: impl Into<anyhow::Error>) {
        let e: anyhow::Error = e.into();
        let transport = e
            .chain()
            .find_map(|c| c.downcast_ref::<meep_client::TransportError>());
        self.error = match transport {
            Some(meep_client::TransportError::Unavailable(_)) => return,
            Some(meep_client::TransportError::Unauthorized) => {
                Some("This Mac needs to sign in to the Meep server again.".into())
            }
            Some(meep_client::TransportError::Api { message, .. }) if !message.is_empty() => {
                Some(message.clone())
            }
            Some(meep_client::TransportError::Protocol(_)) => {
                Some("The Meep server sent something this version of Meep can't read.".into())
            }
            // The outermost context is the sentence written for people.
            _ => Some(e.to_string()),
        };
    }
    /// Open the topic's chat with a started sentence, ready to finish and send.
    pub(super) fn ask_in_chat(&mut self, start: &str, w: &mut Window, cx: &mut Context<Self>) {
        self.open_chat(w, cx);
        self.composer.update(cx, |e, cx| {
            e.set_value(start, w, cx);
            e.focus(w, cx)
        });
        cx.notify()
    }
    pub(super) fn login(&mut self, w: &Window, cx: &mut Context<Self>) {
        if self.login_busy {
            return;
        }
        self.login_busy = true;
        self.error = None;
        let b = self.backend.clone();
        let r = self.region;
        self.job(async move { b.login(r).await }, w, cx, |s, res, _, _| {
            s.login_busy = false;
            match res {
                Ok(i) => {
                    s.identity = Some(i);
                    s.page = Page::Needs;
                }
                Err(e) => s.fail(e),
            }
        });
    }
    /// The task whose conversation the page shows.
    pub(super) fn chat_task(&self) -> Option<(TopicId, TaskId)> {
        match self.page {
            Page::Topic(id, _, Some(Detail::Task(task))) => Some((id, task)),
            _ => None,
        }
    }
    /// Whether the page is the topic's conversation.
    pub(super) fn on_chat(&self) -> bool {
        matches!(self.page, Page::Topic(_, Tab::Chat, None))
    }
    /// Open a task's conversation in the side chat and keep the page as it is.
    pub(super) fn open_beside(
        &mut self,
        id: TopicId,
        task: TaskId,
        w: &mut Window,
        cx: &mut Context<Self>,
    ) {
        // A task is a page of its own in the topic's main pane.
        self.go(Page::Topic(id, Tab::Tasks, Some(Detail::Task(task))), w, cx);
        cx.notify()
    }
    pub(super) fn load_run(&mut self, w: &Window, cx: &mut Context<Self>) {
        let Some((id, task)) = self.chat_task() else {
            return;
        };
        self.run_revision += 1;
        let revision = self.run_revision;
        let c = self.client().clone();
        self.job(
            async move { c.task_conversation(id, task).await },
            w,
            cx,
            move |s, r, _, _| {
                if revision != s.run_revision || s.chat_task() != Some((id, task)) {
                    return;
                }
                match r {
                    Ok(c) => {
                        s.run_status = c.status;
                        if let Some(turns) = s.pending_turns.get_mut(&task) {
                            turns.retain(|turn| {
                                c.messages
                                    .iter()
                                    .filter(|m| m.role == "user" && m.text == turn.message.text)
                                    .count()
                                    <= turn.previous_matches
                            });
                            if turns.is_empty() {
                                s.pending_turns.remove(&task);
                            }
                        }
                        s.run_messages = c
                            .messages
                            .into_iter()
                            .map(|mut m| {
                                if m.role == "assistant" {
                                    m.text = super::details::readable_answer(&m.text);
                                }
                                m
                            })
                            .collect();
                        s.run_notice = None
                    }
                    Err(e) => s.run_notice = Some(format!("Couldn’t load the conversation. {e}")),
                }
            },
        );
    }
    pub(super) fn send_run_message(&mut self, w: &mut Window, cx: &mut Context<Self>) {
        let Some((id, task)) = self.chat_task() else {
            return;
        };
        let draft = self.run_input.read(cx).value().to_string();
        let queued = self
            .states
            .iter()
            .find(|s| s.topic.id == id)
            .and_then(|s| s.tasks.iter().find(|t| t.id == task))
            .is_some_and(|t| t.queued && t.column == Column::Todo);
        if self.sending_runs.contains(&task) || self.chat_uploading > 0 {
            return;
        }
        let mut parts = vec![draft.trim().to_owned()];
        for path in &self.run_files {
            let Some(excerpt) = self.chat_file_excerpt(id, path) else {
                self.error = Some(format!("{path} is not available in this replica yet."));
                cx.notify();
                return;
            };
            parts.push(excerpt);
        }
        let message = parts.join("\n\n").trim().to_owned();
        if queued {
            if self.issue(
                id,
                Command::StartTaskWithInput {
                    task,
                    message,
                    model: self.run_model.clone(),
                },
            ) {
                self.run_input.update(cx, |e, cx| e.set_value("", w, cx));
                self.run_files.clear();
                self.run_model = None;
            }
            return;
        }
        if message.is_empty() {
            return;
        }
        self.sending_runs.insert(task);
        let c = self.client().clone();
        let model = self.run_model.take();
        let files = std::mem::take(&mut self.run_files);
        let seen = self
            .run_messages
            .iter()
            .filter(|m| m.role == "user" && m.text == message)
            .count();
        let pending = self.pending_turns.entry(task).or_default();
        pending.push(PendingTurn {
            previous_matches: seen + pending.iter().filter(|p| p.message.text == message).count(),
            after_messages: self.run_messages.len() + pending.len(),
            message: meep_protocol::sessions::AgentMessage {
                role: "user".into(),
                text: message.clone(),
                created_at: chrono::Utc::now().timestamp_millis(),
                ..Default::default()
            },
        });
        self.run_scroll.scroll_to_bottom();
        self.run_input.update(cx, |e, cx| e.set_value("", w, cx));
        cx.notify();
        let requested = model.clone();
        self.job(
            async move {
                c.send_task_message_on_model(id, task, &message, requested.as_deref())
                    .await
            },
            w,
            cx,
            move |s, r, w, cx| {
                s.sending_runs.remove(&task);
                if s.chat_task() != Some((id, task)) {
                    if let Err(e) = r {
                        if let Some(turns) = s.pending_turns.get_mut(&task) {
                            turns.pop();
                        }
                        s.fail(e.context(format!("Couldn’t send “{draft}”")));
                    }
                    return;
                }
                match r {
                    Ok(()) => s.load_run(w, cx),
                    Err(e) => {
                        if let Some(turns) = s.pending_turns.get_mut(&task) {
                            turns.pop();
                        }
                        if s.run_model.is_none() {
                            s.run_model = model;
                        }
                        s.run_files.extend(files);
                        let current = s.run_input.read(cx).value().to_string();
                        let restored = if current.is_empty() {
                            draft
                        } else {
                            format!("{draft}\n{current}")
                        };
                        s.run_input
                            .update(cx, |input, cx| input.set_value(restored, w, cx));
                        s.fail(e)
                    }
                }
            },
        );
    }
    pub(super) fn go(&mut self, page: Page, w: &mut Window, cx: &mut Context<Self>) {
        if self.page != page {
            self.back.push(self.page.clone());
        }
        self.navigate(page, w, cx)
    }
    pub(super) fn navigate(&mut self, page: Page, w: &mut Window, cx: &mut Context<Self>) {
        // Older saved layouts and links may still address a review as an inbox
        // thread. Preserve access to it on the appropriate review surface.
        let page = match page {
            Page::Topic(topic, Tab::Inbox, Some(Detail::Thread(thread))) => {
                let tab = self
                    .states
                    .iter()
                    .find(|state| state.topic.id == topic)
                    .and_then(|state| state.threads.iter().find(|item| item.id == thread))
                    .map_or(Tab::Facts, super::pages::thread_tab);
                Page::Topic(topic, tab, Some(Detail::Thread(thread)))
            }
            other => other,
        };
        if self.page != page
            && (matches!(self.page, Page::View(_) | Page::NewView)
                || matches!(page, Page::View(_) | Page::NewView))
        {
            self.views.leave();
            self.views.prompt.update(cx, |e, cx| e.set_value("", w, cx));
        }
        if self.topic_id()
            != match page {
                Page::Topic(id, ..) => Some(id),
                _ => None,
            }
        {
            self.composer.update(cx, |e, cx| e.set_value("", w, cx));
            self.folder = None;
            self.chat_reference = None;
            // Uploaded files stay in the topic they were saved to; only the draft lets go.
            self.chat_files.clear();
        }
        if page == Page::Settings
            && self.page != Page::Settings
            && let Some(account) = self.identity.clone().filter(|a| a.email.is_none())
        {
            let backend = self.backend.clone();
            self.job(
                async move { backend.restore_email(account.region).await },
                w,
                cx,
                move |s, result, _, _| {
                    if let Ok(email) = result
                        && s.identity.as_ref() == Some(&account)
                    {
                        let mut updated = account;
                        updated.email = Some(email);
                        if let Err(e) = s.client().set_preference("posthog-project", &updated) {
                            s.fail(e);
                        }
                        s.identity = Some(updated);
                    }
                },
            );
        }
        if page == Page::Settings && self.settings_page == SettingsPage::Connections {
            self.mcp_request(meep_wire::mcp_store::Operation::Browse, w, cx);
        }
        if matches!(page, Page::View(_) | Page::NewView) {
            self.views.prompt.update(cx, |e, cx| {
                e.set_placeholder(
                    if page == Page::NewView {
                        "What would you like to see?"
                    } else {
                        "Ask, or tell it what to do"
                    },
                    w,
                    cx,
                )
            });
        }
        // Composers belong to the page they were opened on.
        let (Page::Topic(a, ta, _), Page::Topic(b, tb, _)) = (&self.page, &page) else {
            self.new_routine = false;
            self.adding = false;
            self.page = page.clone();
            return self.after_navigate(page, w, cx);
        };
        if a != b || ta != tb {
            self.new_routine = false;
            self.adding = false;
        }
        self.page = page.clone();
        self.after_navigate(page, w, cx)
    }
    /// A task opens as its conversation in the side chat.
    fn begin_task_chat(
        &mut self,
        id: TopicId,
        task: TaskId,
        w: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.ensure_chat_models(id, w, cx);
        self.run_input.update(cx, |e, cx| e.set_value("", w, cx));
        self.run_model = None;
        self.run_files.clear();
        self.run_scroll = ScrollHandle::new();
        self.run_messages.clear();
        self.run_notice = Some("Loading conversation…".into());
        self.run_status.clear();
        self.load_run(w, cx);
        let t = self
            .states
            .iter()
            .find(|s| s.topic.id == id)
            .and_then(|s| s.tasks.iter().find(|t| t.id == task));
        if t.is_some_and(|t| t.column == Column::Done) {
            self.done = true;
        }
        self.task_model = t.and_then(|t| t.model.clone());
        self.task_effort = t.and_then(|t| t.reasoning_effort.clone());
        self.billing = t.and_then(|t| t.billing.clone());
        self.editing_review = t.map(|t| (id, task, t.review_version));
        self.draft.update(cx, |e, cx| {
            e.set_value(t.and_then(|t| t.draft.clone()).unwrap_or_default(), w, cx)
        });
    }
    /// What the open page is about, attached to anything written from it: its
    /// icon, the chip's label and the context the agent receives.
    pub(super) fn page_subject(&self) -> Option<(Glyph, String, String)> {
        let Page::Topic(id, tab, detail) = &self.page else {
            return None;
        };
        let state = self.states.iter().find(|s| s.topic.id == *id)?;
        let t = &state.topic;
        Some(match (tab, detail) {
            (Tab::Mission, None) => (
                Glyph::Flag,
                "Mission".into(),
                format!("About this topic's mission: \"{}\"", t.mission),
            ),
            (_, Some(Detail::Goal(g))) => {
                let g = t.goals.iter().find(|x| x.id == *g)?;
                let (label, ..) = super::overview::goal_measure(g);
                (
                    Glyph::Target,
                    g.text.clone(),
                    format!("About the goal \"{}\" ({label})", g.text),
                )
            }
            (_, Some(Detail::Fact(f))) => {
                let f = t.facts.iter().find(|x| x.id == *f)?;
                (
                    Glyph::Pencil,
                    meep_topic::title_line(&f.text),
                    format!(
                        "About the fact \"{}\" ({} · {})",
                        f.text, f.provenance.author, f.provenance.via
                    ),
                )
            }
            (_, Some(Detail::Linked(key))) => {
                let w = t.context_sources.iter().find(|x| x.key == *key)?;
                (
                    super::overview::source_glyph(&w.kind),
                    w.label.clone(),
                    format!(
                        "About the linked {} \"{}\" ({})",
                        super::overview::source_kind(&w.kind),
                        w.label,
                        w.key
                    ),
                )
            }
            (_, Some(Detail::Thread(th))) => {
                let th = state.threads.iter().find(|x| x.id == *th)?;
                (
                    Glyph::Inbox,
                    th.subject.clone(),
                    format!("About the inbox report \"{}\": {}", th.subject, th.summary),
                )
            }
            (_, Some(Detail::File(path))) => (
                Glyph::FileText,
                path.rsplit('/').next().unwrap_or(path).to_owned(),
                String::new(),
            ),
            (_, Some(Detail::Routine(key))) => {
                let r = t.routines.iter().find(|x| x.binding.id == *key)?;
                (
                    Glyph::Repeat,
                    r.binding.name.clone(),
                    format!("About the routine \"{}\"", r.binding.name),
                )
            }
            _ => return None,
        })
    }
    /// The composer's prompt for the open page.
    fn composer_placeholder(&self) -> &'static str {
        match &self.page {
            Page::Topic(_, tab, detail) => match (tab, detail) {
                (_, Some(Detail::File(_))) => "Ask about this file",
                (_, Some(Detail::Thread(_))) => "Discuss this report",
                (_, Some(Detail::Routine(_))) => "Ask to change this routine",
                (_, Some(Detail::Goal(_))) => "Change the target, or how it's measured",
                (_, Some(Detail::Fact(_))) => "Correct this, or ask where it came from",
                (_, Some(Detail::Linked(_))) => "Ask about it, or what to use it for",
                (Tab::Tasks, None) => "Ask about tasks, or start a new one",
                (Tab::Inbox, None) => "Ask about the inbox",
                (Tab::Files, None) => "Ask about these files",
                (Tab::Routines, None) => "Ask for a new routine",
                (Tab::Mission, None) => "Tell it how the mission should change",
                (Tab::Goals, None) => "Ask for a new goal, or change one",
                (Tab::Facts, None) => "Tell it something it should know",
                (Tab::Linked, None) => "Link a dashboard, flag or channel",
                (Tab::Rules, None) => "Ask it to always, or never, do something",
                _ => "Ask, or tell it what to do",
            },
            _ => "Ask, or tell it what to do",
        }
    }
    /// Bring the topic's conversation into the main pane.
    pub(super) fn open_chat(&mut self, w: &mut Window, cx: &mut Context<Self>) {
        if let Some(id) = self.topic_id()
            && !matches!(self.page, Page::Topic(_, Tab::Chat, None))
        {
            self.go(Page::Topic(id, Tab::Chat, None), w, cx);
        }
    }
    /// One level up: an item to its section, a section to the conversation.
    pub(super) fn up(&mut self, w: &mut Window, cx: &mut Context<Self>) {
        let Page::Topic(id, tab, detail) = self.page.clone() else {
            return;
        };
        let target = match (tab, detail) {
            (Tab::Chat, None) => return,
            (Tab::Chat, Some(_)) => Page::Topic(id, Tab::Chat, None),
            (tab, Some(_)) => Page::Topic(id, tab, None),
            (_, None) => Page::Topic(id, Tab::Chat, None),
        };
        if self.back.last() == Some(&target) {
            self.back.pop();
        } else {
            self.back.push(self.page.clone());
        }
        self.navigate(target, w, cx);
    }
    fn after_navigate(&mut self, page: Page, w: &mut Window, cx: &mut Context<Self>) {
        self.overview_overlay = false;
        let placeholder = self.composer_placeholder();
        self.composer
            .update(cx, |e, cx| e.set_placeholder(placeholder, w, cx));
        self.reveal_selection = false;
        self.sheet_return_focus = None;
        self.sheet = None;
        self.menu = false;
        self.adding = false;
        self.editing = false;
        self.send_back = false;
        // The conversation is ready to be written in as soon as it opens.
        if self.on_chat() {
            self.composer.focus_handle(cx).focus(w, cx);
        } else {
            self.focus.focus(w, cx);
        }
        if let Page::Topic(id, tab, detail) = page {
            match detail {
                Some(Detail::Thread(thread)) => {
                    if self
                        .states
                        .iter()
                        .find(|s| s.topic.id == id)
                        .and_then(|s| s.threads.iter().find(|t| t.id == thread))
                        .is_some_and(|t| t.unseen)
                    {
                        self.issue(id, Command::MarkSeen { thread });
                    }
                }
                Some(Detail::Routine(ref key)) => self.fetch_workflow(id, key.clone(), None, w, cx),
                Some(Detail::Task(task)) => self.begin_task_chat(id, task, w, cx),
                Some(Detail::File(ref path)) if tab == Tab::Files && self.is_artifact(id, path) => {
                    self.files = true;
                    self.reveal_file(id, path);
                    self.open_artifact(w, cx);
                }
                Some(Detail::File(ref path) | Detail::Table(ref path)) => {
                    self.files = matches!(detail, Some(Detail::File(_)));
                    if self.files {
                        self.folder =
                            Some(path.rsplit_once('/').map_or("", |(dir, _)| dir).to_owned());
                        self.reveal_file(id, path);
                    }
                    let path = path.clone();
                    let c = self.client().clone();
                    self.job(
                        async move { c.get_file(id, &path).await },
                        w,
                        cx,
                        |s, r, _, _| {
                            if let Err(e) = r {
                                s.fail(e)
                            }
                        },
                    );
                }
                _ => {}
            }
            if tab == Tab::Files {
                self.refresh_artifacts(id, false, w, cx);
                let c = self.client().clone();
                self.job(
                    async move { c.refresh_files(id).await },
                    w,
                    cx,
                    |s, r, _, _| {
                        if let Err(e) = r {
                            s.fail(e)
                        }
                    },
                );
            }
        }
        cx.notify()
    }
    pub(super) fn topic_id(&self) -> Option<TopicId> {
        if let Page::Topic(id, ..) = self.page {
            Some(id)
        } else {
            None
        }
    }
    /// Fetch the server's routine templates for the routine sheet.
    pub(super) fn load_templates(&mut self, w: &Window, cx: &mut Context<Self>) {
        self.templates = None;
        let c = self.client().clone();
        self.job(
            async move { c.routine_templates().await },
            w,
            cx,
            |s, r, _, _| s.templates = Some(r.map_err(|e| e.to_string())),
        )
    }
    /// Create a routine from a template in the open topic, then show it.
    pub(super) fn add_template(&mut self, template: String, w: &Window, cx: &mut Context<Self>) {
        let Some(id) = self.topic_id() else { return };
        self.creating_template = Some(template.clone());
        let c = self.client().clone();
        let req = meep_wire::CreateTemplateRoutine {
            template,
            sources: vec![],
        };
        self.job(
            async move { c.create_template_routine(id, &req).await },
            w,
            cx,
            move |s, r, w, cx| {
                s.creating_template = None;
                match r {
                    Ok(routine) => {
                        s.new_routine = false;
                        s.routine_template = None;
                        s.routine_prompt.update(cx, |e, cx| e.set_value("", w, cx));
                        s.reload();
                        s.go(
                            Page::Topic(
                                id,
                                Tab::Routines,
                                Some(Detail::Routine(routine.binding.id)),
                            ),
                            w,
                            cx,
                        )
                    }
                    Err(e) => s.error = Some(e.to_string()),
                }
            },
        )
    }
    /// Open the New task composer in place of the board, cleared.
    pub(super) fn begin_task(&mut self, id: TopicId, w: &mut Window, cx: &mut Context<Self>) {
        self.billing = None;
        self.task_files.clear();
        // Start is the default; Queue holds it in To do.
        self.task_for_agent = true;
        self.task_model = None;
        self.task_effort = None;
        self.sync_task_selection(cx);
        self.ensure_chat_models(id, w, cx);
        self.adding = true;
        self.task_description.update(cx, |e, cx| {
            e.set_value("", w, cx);
            e.focus(w, cx)
        });
        cx.notify()
    }
    /// Open the New routine composer in place of the routine list.
    pub(super) fn compose_routine(&mut self, w: &mut Window, cx: &mut Context<Self>) {
        self.new_routine = true;
        self.routine_prompt.update(cx, |e, cx| e.focus(w, cx));
        self.load_templates(w, cx);
        cx.notify()
    }
    pub(super) fn open_sheet(&mut self, sheet: Sheet, w: &mut Window, cx: &mut Context<Self>) {
        if sheet == Sheet::New && self.identity.is_none() {
            self.go(Page::Settings, w, cx);
            return;
        }
        if self.sheet.is_none() {
            self.sheet_return_focus = w.focused(cx);
        }
        let val = match &sheet {
            Sheet::RenameTopic(id) => self
                .states
                .iter()
                .find(|s| s.topic.id == *id)
                .map(|s| s.topic.name.clone())
                .unwrap_or_default(),
            _ => String::new(),
        };
        let input = if sheet == Sheet::Search {
            &self.search
        } else {
            &self.name
        };
        input.update(cx, |e, cx| {
            e.set_value(val, w, cx);
            e.focus(w, cx)
        });
        if matches!(sheet, Sheet::Bind | Sheet::New) {
            self.mission.update(cx, |e, cx| {
                e.set_placeholder(
                    if sheet == Sheet::Bind {
                        "PostHog workflow UUID"
                    } else {
                        "What do you want to get done?"
                    },
                    w,
                    cx,
                );
                e.set_value("", w, cx);
            });
        }
        if sheet == Sheet::New {
            self.name.update(cx, |e, cx| {
                e.set_placeholder("Name it", w, cx);
                e.set_value("", w, cx);
            });
            // The goal comes first; the name follows it.
            self.mission.update(cx, |e, cx| e.focus(w, cx));
        }
        self.search_index = 0;
        // A new topic lands in the open topic's section, or loose.
        self.section = self
            .topic_id()
            .and_then(|id| self.layout.home(&super::sidebar::topic_key(id)))
            .unwrap_or_default();
        self.sheet = Some(sheet);
        self.menu = false;
        cx.notify()
    }
    pub(super) fn submit(&mut self, w: &mut Window, cx: &mut Context<Self>) {
        let name = if self.sheet.is_none() && self.adding {
            self.task_description.read(cx).value().trim().to_owned()
        } else {
            self.name.read(cx).value().trim().to_owned()
        };
        if self.sheet != Some(Sheet::Search) && name.is_empty() {
            return;
        }
        match self.sheet.clone() {
            Some(Sheet::Search) => {
                if let Some((_, _, page)) = self.hits(cx).get(self.search_index) {
                    self.go(page.clone(), w, cx)
                }
            }
            Some(Sheet::New) => {
                let id = TopicId(Uuid::new_v4());
                let mission = self.mission.read(cx).value().trim().to_owned();
                // Its Sort inbox starts as an ordinary routine; changing or
                // removing it is something to ask for in the topic's chat.
                match self.client().create_topic(id, name, mission, "posthog") {
                    Err(e) => self.fail(e),
                    Ok(_) => {
                        self.reload();
                        let section = Some(self.section).filter(|s| !s.is_nil());
                        if section.is_some() {
                            self.move_to_section(&super::sidebar::topic_key(id), section, cx);
                        }
                        self.go(Page::Topic(id, Tab::Chat, None), w, cx);
                    }
                }
            }
            Some(Sheet::RenameTopic(id)) => {
                if self.issue(id, Command::RenameTopic { name }) {
                    self.sheet = None;
                    self.focus.focus(w, cx)
                }
            }
            Some(Sheet::Bind) => {
                if let Some(id) = self.topic_id() {
                    let flow = self.mission.read(cx).value().trim().to_owned();
                    if Uuid::parse_str(&flow).is_err() {
                        self.error = Some("Enter the PostHog workflow’s flow ID (UUID).".into());
                        return;
                    }
                    let routine = RoutineBinding {
                        watches: vec![],
                        id: flow.clone(),
                        name,
                        backend: "posthog".into(),
                        external_id: flow,
                        trigger: "PostHog workflow".into(),
                    };
                    if self.issue(id, Command::SetRoutine { routine }) {
                        self.sheet = None;
                        self.focus.focus(w, cx)
                    }
                }
            }
            None if self.adding => {
                let task = TaskId(Uuid::new_v4());
                let mut description = name.clone();
                if self.chat_uploading > 0 {
                    return;
                }
                // Attached files ride in the brief, as they do with a chat message.
                if let Some(id) = self.topic_id() {
                    for path in &self.task_files {
                        let Some(excerpt) = self.chat_file_excerpt(id, path) else {
                            self.error =
                                Some(format!("{path} is not available in this replica yet."));
                            cx.notify();
                            return;
                        };
                        description = format!("{description}\n\n{excerpt}").trim().to_owned();
                    }
                }
                // Tasks are the agent's: Start runs it now, Queue holds it in To do.
                // Either way it keeps the chosen model, effort and billing.
                let agent = self.task_for_agent;
                let codex = self
                    .chosen_task_model()
                    .is_some_and(|m| m.runtime.as_deref() == Some("codex"));
                let command = Command::AddConfiguredTask {
                    start: agent,
                    id: task,
                    // A stand-in until PostHog names the task from its brief.
                    title: meep_topic::title_line(&name),
                    untitled: true,
                    model: self.task_model.clone(),
                    reasoning_effort: self.task_effort.clone(),
                    instructions: (!description.is_empty()).then_some(description),
                    billing: codex.then(|| {
                        self.billing
                            .clone()
                            .unwrap_or_else(|| "posthog-gateway".into())
                    }),
                };
                if let Some(id) = self.topic_id()
                    && self.issue(id, command)
                {
                    self.adding = false;
                    self.task_files.clear();
                    self.focus.focus(w, cx);
                    // A started task opens as its conversation right away.
                    if agent {
                        self.go(Page::Topic(id, Tab::Tasks, Some(Detail::Task(task))), w, cx);
                    }
                }
            }
            _ => {}
        }
    }
    pub(super) fn hits(&self, cx: &App) -> Vec<(String, String, Page)> {
        let value = self.search.read(cx).value();
        let q = value.trim();
        if q.is_empty() {
            // A few topics, so recent tasks and messages stay in view.
            let mut hits: Vec<_> = self
                .states
                .iter()
                .take(4)
                .map(|s| {
                    (
                        s.topic.name.clone(),
                        "Topics".into(),
                        Page::Topic(s.topic.id, Tab::Chat, None),
                    )
                })
                .collect();
            let mut tasks: Vec<_> = self
                .states
                .iter()
                .flat_map(|s| s.tasks.iter().map(|t| (s.topic.id, t)))
                .collect();
            tasks.sort_by_key(|(_, t)| std::cmp::Reverse(t.updated_at));
            hits.extend(tasks.into_iter().take(3).map(|(id, t)| {
                (
                    t.title.clone(),
                    "Tasks".into(),
                    Page::Topic(id, Tab::Tasks, Some(Detail::Task(t.id))),
                )
            }));
            let mut threads: Vec<_> = self
                .states
                .iter()
                .flat_map(|s| {
                    s.threads
                        .iter()
                        .filter(|t| t.is_agent_report())
                        .map(|t| (s.topic.id, t))
                })
                .collect();
            threads.sort_by_key(|(_, t)| std::cmp::Reverse(super::pages::message_time(t)));
            hits.extend(threads.into_iter().take(3).map(|(id, t)| {
                (
                    t.subject.clone(),
                    "Reports".into(),
                    Page::Topic(id, Tab::Inbox, Some(Detail::Thread(t.id))),
                )
            }));
            return hits;
        }
        let Ok(res) = self.client().search(q, 50) else {
            return vec![];
        };
        let mut hits: Vec<_> = res
            .hits
            .into_iter()
            .filter_map(|h| {
                let state = self.states.iter().find(|s| s.topic.id == h.topic)?;
                let (group, label, tab, detail) = match h.kind.as_str() {
                    "topic" => ("Topics", state.topic.name.clone(), Tab::Chat, None),
                    "thread" => {
                        let id = h.id.parse().ok()?;
                        (
                            "Reports",
                            state
                                .threads
                                .iter()
                                .find(|t| t.id == id && t.is_agent_report())?
                                .subject
                                .clone(),
                            Tab::Inbox,
                            Some(Detail::Thread(id)),
                        )
                    }
                    "task" => {
                        let id = h.id.parse().ok()?;
                        (
                            "Tasks",
                            state.tasks.iter().find(|t| t.id == id)?.title.clone(),
                            Tab::Tasks,
                            Some(Detail::Task(id)),
                        )
                    }
                    "fact" => {
                        let id = h.id.parse().ok()?;
                        (
                            "Facts",
                            state.topic.facts.iter().find(|t| t.id == id)?.text.clone(),
                            Tab::Facts,
                            Some(Detail::Fact(id)),
                        )
                    }
                    _ => return None,
                };
                Some((label, group.to_owned(), Page::Topic(h.topic, tab, detail)))
            })
            .collect();
        hits.sort_by_key(|(_, _, p)| match p {
            Page::Topic(_, _, None) => 0,
            Page::Topic(_, Tab::Tasks, _) => 1,
            Page::Topic(_, Tab::Inbox, _) => 2,
            _ => 3,
        });
        hits
    }
    pub(super) fn approve(
        &mut self,
        id: TopicId,
        task: TaskId,
        review: u64,
        draft: Option<String>,
    ) {
        let rule_id = RuleId(Uuid::new_v4());
        if self.issue(
            id,
            Command::Approve {
                task,
                expected_review: Some(review),
                edited_draft: draft,
                always: false,
                rule_id,
            },
        ) {
            self.just_approved = self
                .states
                .iter()
                .find(|s| s.topic.id == id)
                .and_then(|s| {
                    s.tasks
                        .iter()
                        .find(|t| t.id == task && t.approval_rule == Some(rule_id))
                })
                .map(|_| (id, task, rule_id));
            self.done = true;
        }
    }
}

pub(super) fn control(
    id: impl Into<SharedString>,
    label: impl Into<SharedString>,
    primary: bool,
    cx: &Context<Desktop>,
    f: impl Fn(&mut Desktop, &mut Window, &mut Context<Desktop>) + 'static,
) -> Button {
    let id = id.into();
    let label = label.into();
    let b = if primary {
        ui::primary_button(id, label)
    } else {
        ui::button(id, label).border_1().border_color(ui::ink(43))
    };
    b.h(px(28.))
        .px(px(10.))
        .rounded(px(6.))
        .self_start()
        .on_click(cx.listener(move |s, _, w, cx| {
            cx.stop_propagation();
            f(s, w, cx);
            cx.notify()
        }))
}
/// Quiet trailing count, as View's source list draws it.
pub(super) fn badge(n: usize) -> Div {
    ui::nav::count(n.to_string())
}

/// A topic's mark. Topics are addressed with @; only views carry icons.
/// A topic's @ in a list row. It keeps the 16pt icon column so names line up
/// with views, but draws smaller and leans toward the name so the two read
/// as one handle.
pub(super) fn row_at(selected: bool) -> Div {
    div()
        .flex_none()
        .size(px(ui::nav::ICON_BOX))
        .flex()
        .items_center()
        .justify_center()
        .child(
            meep_ui::gpui_kit::component::Icon::new(Glyph::AtSign)
                .size(px(13.5))
                .text_color(rgb(ui::theme::color(if selected {
                    ui::INK
                } else {
                    ui::SECONDARY
                }))),
        )
}
pub(super) fn at_mark(size: f32) -> Div {
    div()
        .flex_none()
        .size(px(size))
        .rounded(px(size * 0.27))
        .bg(ui::ink(0x0b))
        .flex()
        .items_center()
        .justify_center()
        .child(
            meep_ui::gpui_kit::component::Icon::new(Glyph::AtSign)
                .size(px(size * 0.56))
                .text_color(rgb(ui::theme::color(ui::SECONDARY))),
        )
}
/// A selectable content row: hover and selection fills, height from its content.
pub(super) fn line(id: impl Into<SharedString>, selected: bool) -> Stateful<Div> {
    ui::row()
        .id(id.into())
        .role(Role::Button)
        .w_full()
        .px(px(8.))
        .py(px(6.))
        .rounded(px(6.))
        .cursor_pointer()
        .hover(|s| s.bg(ui::ink(ui::nav::HOVER & 0xff)))
        .when(selected, |el| el.bg(rgb(ui::theme::get(7))))
}
/// A source-list row with View's sidebar geometry: 28pt on a 30pt pitch.
/// The way back from an item to its list, the same everywhere: the list's name
/// as a link, a chevron, then the item's name. "Inbox › Keyboard focus",
/// "Routines › Pilot pulse", "MCP servers › Linear".
pub(super) fn crumbs(
    id: impl Into<SharedString>,
    parent: impl Into<SharedString>,
    current: impl Into<SharedString>,
    back: impl Fn(&mut Desktop, &mut Window, &mut Context<Desktop>) + 'static,
    cx: &Context<Desktop>,
) -> Div {
    ui::row()
        .min_w_0()
        .gap(px(8.))
        .child(
            div()
                .id(id.into())
                .role(Role::Link)
                .flex_none()
                .cursor_pointer()
                .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                .hover(|s| s.text_color(rgb(ui::theme::color(ui::INK))))
                .child(parent.into())
                .on_click(cx.listener(move |s, _, w, cx| back(s, w, cx))),
        )
        .child(
            meep_ui::gpui_kit::component::Icon::new(Glyph::ChevronRight)
                .size(px(12.))
                .text_color(rgb(ui::theme::color(ui::TERTIARY))),
        )
        .child(
            div()
                .min_w_0()
                .truncate()
                .font_weight(FontWeight::SEMIBOLD)
                .child(current.into()),
        )
}
/// A topic page's way home: `@ Topic › Section › Item`. Each segment but the
/// last is a link up; the conversation itself is just the topic's name.
pub(super) fn topic_crumbs(
    topic: TopicId,
    name: &str,
    tab: Tab,
    current: Option<(Option<AnyElement>, String)>,
    cx: &Context<Desktop>,
) -> Div {
    let link = |id: String, label: String, glyph: Option<Glyph>, page: Page| {
        ui::row()
            .id(SharedString::from(id))
            .role(Role::Link)
            .flex_none()
            .max_w(px(200.))
            .gap(px(6.))
            .px(px(6.))
            .py(px(3.))
            .ml(px(-6.))
            .rounded(px(6.))
            .cursor_pointer()
            .text_color(rgb(ui::theme::color(ui::SECONDARY)))
            .hover(|s| {
                s.bg(ui::ink(0x08))
                    .text_color(rgb(ui::theme::color(ui::INK)))
            })
            .children(glyph.map(|g| ui::nav::glyph(g, false)))
            .child(div().min_w_0().truncate().child(label))
            .on_click(cx.listener(move |s, _, w, cx| s.go(page.clone(), w, cx)))
    };
    let chevron = || {
        div().flex_none().child(
            meep_ui::gpui_kit::component::Icon::new(Glyph::ChevronRight)
                .size(px(12.))
                .text_color(rgb(ui::theme::color(ui::TERTIARY))),
        )
    };
    let here = |icon: Option<AnyElement>, label: String| {
        ui::row().min_w_0().gap(px(7.)).children(icon).child(
            div()
                .min_w_0()
                .truncate()
                .font_weight(FontWeight::SEMIBOLD)
                .child(label),
        )
    };
    let mut row = ui::row().min_w_0().gap(px(6.));
    if tab == Tab::Chat && current.is_none() {
        return row.child(here(
            Some(ui::nav::glyph(Glyph::AtSign, true).into_any_element()),
            name.to_owned(),
        ));
    }
    row = row
        .child(link(
            "crumb-topic".into(),
            name.to_owned(),
            Some(Glyph::AtSign),
            Page::Topic(topic, Tab::Chat, None),
        ))
        .child(chevron());
    match current {
        Some((icon, label)) => row
            .child(link(
                "crumb-section".into(),
                tab.label().into(),
                None,
                Page::Topic(topic, tab, None),
            ))
            .child(chevron())
            .child(here(icon, label)),
        None => row.child(here(None, tab.label().into())),
    }
}
/// A page that replaces its tab's list opens under this bar: the crumbs, a
/// quiet line of context, and the page's own tools at the end.
pub(super) fn crumb_bar(
    crumbs: Div,
    meta: Option<String>,
    tools: impl IntoIterator<Item = AnyElement>,
) -> Div {
    ui::row()
        .h(px(CRUMB_BAR))
        .pl(px(super::details::PAGE_X - 4.))
        .pr(px(12.))
        .gap(px(8.))
        .flex_none()
        .child(crumbs.flex_shrink(1.))
        .child(
            ui::caption(meta.unwrap_or_default())
                .flex_1()
                .min_w(px(40.))
                .truncate(),
        )
        .children(tools)
}
pub(super) const CRUMB_BAR: f32 = 46.;
pub(super) fn nav_line(id: impl Into<SharedString>, selected: bool) -> Stateful<Div> {
    ui::row()
        .id(id.into())
        .role(Role::Button)
        .w_full()
        .flex_none()
        .h(px(ui::nav::ROW))
        .gap(px(8.))
        .pl(px(ui::nav::PAD))
        .pr(px(ui::nav::TRAIL))
        .rounded(px(ui::nav::RADIUS))
        .hover(|s| s.bg(ui::ink(ui::nav::HOVER & 0xff)))
        .active(|s| s.bg(ui::ink(ui::nav::PRESSED & 0xff)))
        .when(selected, |el| el.bg(rgb(ui::theme::get(7))))
}
pub(super) fn column_name(c: Column) -> &'static str {
    match c {
        Column::Todo => "To do",
        Column::InProgress => "In progress",
        Column::NeedsYou => "Needs you",
        Column::Done => "Done",
    }
}
/// View's empty-state illustration: a short deck whose front card is a real
/// row of the list it stands in for, with two calm lines underneath.
pub(super) fn deck(
    glyph: Glyph,
    marker: u32,
    title: impl Into<SharedString>,
    meta: impl Into<SharedString>,
    lines: [&'static str; 2],
) -> Div {
    const W: f32 = 280.;
    const H: f32 = 56.;
    const PEEK: f32 = 8.;
    let meta: SharedString = meta.into();
    let canvas = rgb(ui::theme::color(ui::CANVAS));
    let card = |depth: usize| {
        let inset = depth as f32 * 12.;
        div()
            .absolute()
            .left(px(inset))
            .top(px((2 - depth) as f32 * PEEK))
            .w(px(W - inset * 2.))
            .h(px(H))
            .rounded(px(10.))
            .border_1()
            .border_color(ui::ink(0x14))
            .bg(canvas)
            .overflow_hidden()
            .child(div().size_full().bg(ui::ink(depth as u32 * 0x05)))
    };
    let front = card(0)
        .shadow(vec![BoxShadow {
            color: ui::ink(0x0c).into(),
            offset: point(px(0.), px(4.)),
            blur_radius: px(10.),
            spread_radius: px(-4.),
            inset: false,
        }])
        .child(
            ui::row()
                .absolute()
                .inset_0()
                .items_center()
                .gap(px(8.))
                .px(px(12.))
                .child(
                    div()
                        .size(px(6.))
                        .flex_none()
                        .rounded_full()
                        .bg(rgb(marker)),
                )
                .child(ui::nav::glyph(glyph, false))
                .child(
                    ui::column()
                        .flex_1()
                        .min_w_0()
                        .gap(px(1.))
                        .child(
                            ui::row().gap(px(8.)).child(
                                div()
                                    .flex_1()
                                    .min_w_0()
                                    .truncate()
                                    .line_height(px(17.))
                                    .font_weight(FontWeight::MEDIUM)
                                    .child(title.into()),
                            ),
                        )
                        // An empty meta line would still take 16pt and lift the
                        // title off the card's centre.
                        .when(!meta.is_empty(), |c| {
                            c.child(
                                div()
                                    .truncate()
                                    .text_size(px(12.))
                                    .line_height(px(16.))
                                    .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                                    .child(meta),
                            )
                        }),
                ),
        );
    ui::column()
        .size_full()
        .min_h(px(320.))
        .items_center()
        .justify_center()
        // Optically centred: the header above already shifts the eye up.
        .pb(px(96.))
        .px(px(24.))
        .child(
            div()
                .relative()
                .flex_none()
                .w(px(W))
                .h(px(H + 2. * PEEK))
                .child(card(2))
                .child(card(1))
                .child(front),
        )
        .child(
            div()
                .pt(px(28.))
                .max_w(px(420.))
                .text_center()
                .text_size(px(12.))
                .line_height(px(17.))
                .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                // Two thoughts, one per line, so neither breaks mid-phrase.
                .child(div().child(lines[0]))
                .child(div().child(lines[1])),
        )
}
/// A suggestion row: View's starter, a glyph and a sentence the user can send.
pub(super) fn starter(
    id: impl Into<SharedString>,
    glyph: Glyph,
    text: impl Into<SharedString>,
) -> Stateful<Div> {
    let text = text.into();
    div()
        .id(id.into())
        .role(Role::Button)
        .aria_label(text.clone())
        .flex()
        .items_center()
        .gap(px(10.))
        .h(px(34.))
        .px(px(10.))
        .rounded(px(8.))
        .cursor_pointer()
        .hover(|s| s.bg(ui::ink(0x0a)))
        .child(ui::nav::glyph(glyph, false))
        .child(ui::nav::title(text))
}
pub(super) fn scroll(id: &'static str) -> Stateful<Div> {
    ui::column().id(id).flex_1().min_h_0().overflow_y_scroll()
}

/// The New view layout, shared by every "describe what you want" page: a mark,
/// a title and one line, the composer, a quiet hint row, then starters.
pub(super) struct Creation {
    pub glyph: Glyph,
    pub id: &'static str,
    pub title: &'static str,
    pub intro: &'static str,
    /// Left side of the hint row under the composer.
    pub hint: Option<AnyElement>,
    /// Whether there is anything to go back to.
    pub cancel: bool,
    /// Label above the starters.
    pub ideas_label: &'static str,
    pub ideas: Vec<AnyElement>,
    /// A secondary way in, under the starters.
    pub footer: Option<AnyElement>,
}
pub(super) fn creation_page(c: Creation, field: impl IntoElement) -> Div {
    let mark = div()
        .flex_none()
        .size(px(36.))
        .rounded(px(36. * 0.27))
        .bg(ui::ink(0x0b))
        .flex()
        .items_center()
        .justify_center()
        .child(
            meep_ui::gpui_kit::component::Icon::new(c.glyph)
                .size(px(20.))
                .text_color(rgb(ui::theme::color(ui::SECONDARY))),
        );
    let hints = ui::row()
        .pt(px(8.))
        .gap(px(8.))
        .child(
            div()
                .flex_1()
                .min_w_0()
                .text_size(px(ui::SMALL))
                .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                .children(c.hint),
        )
        .when(c.cancel, |r| {
            r.child(
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
            )
        });
    let has_ideas = !c.ideas.is_empty();
    // Centred when it fits; on a short window it scrolls from the top instead of clipping.
    div().size_full().child(
        ui::column()
            .id(SharedString::from(format!("{}-scroll", c.id)))
            .size_full()
            .overflow_y_scroll()
            .child(
                ui::column()
                    .min_h_full()
                    .w_full()
                    .flex_none()
                    .items_center()
                    .justify_center()
                    .p(px(24.))
                    .child(
                        ui::column()
                            .w_full()
                            .max_w(px(520.))
                            .gap_0()
                            .mb(px(48.))
                            .child(mark)
                            .child(
                                ui::heading(c.id, c.title)
                                    .mt(px(16.))
                                    .text_size(px(20.))
                                    .line_height(relative(1.35)),
                            )
                            .child(
                                div()
                                    .mt(px(6.))
                                    .text_size(px(13.))
                                    .line_height(relative(1.5))
                                    .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                                    .child(c.intro),
                            )
                            .child(div().mt(px(20.)).child(field))
                            .child(hints)
                            .when(has_ideas, |col| {
                                col.child(
                                    div()
                                        .mt(px(24.))
                                        .text_size(px(12.))
                                        .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                                        .pb(px(4.))
                                        .child(c.ideas_label),
                                )
                                .child(ui::column().gap(px(2.)).mx(px(-10.)).children(c.ideas))
                            })
                            .when_some(c.footer, |col, f| col.child(div().mt(px(16.)).child(f))),
                    ),
            ),
    )
}

/// Whether a topic's agent is at work: its conversation answering, or any agent run.
pub(super) fn topic_working(s: &TopicState) -> bool {
    s.tasks.iter().any(|t| {
        t.column == Column::InProgress
            && (t.is_session() || t.worker.is_some())
            && t.assignment != Some(InboxAssignment::Human)
    })
}

/// Whether a view's agent is building it.
pub(super) fn view_working(v: &meep_wire::views::View) -> bool {
    v.turns.last().is_some_and(|t| !t.stage.finished())
}
