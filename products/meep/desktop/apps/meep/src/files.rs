//! The Files tab: the topic's own files and everything its task runs produced,
//! browsed as one folder tree. Task artifacts stay in PostHog; the app lists them
//! live and the client keeps a size-capped cache of the versions opened.
use super::pages::{human_size, short_subject};
use super::*;
use meep_ui::gpui_kit::component::Icon;
use meep_wire::TaskArtifact;
use std::collections::{BTreeMap, BTreeSet};

/// The folder that holds one folder per task.
pub(super) const TASKS: &str = "tasks";
/// A listing younger than this is reused when the tab opens again.
const FRESH: std::time::Duration = std::time::Duration::from_secs(30);

/// What a path in the tree holds.
#[derive(Clone)]
pub(super) enum Entry {
    /// A synced topic file.
    File,
    /// An artifact one of the topic's task runs produced in PostHog.
    Artifact(Box<TaskArtifact>),
}

/// One folder of the tree.
#[derive(Default)]
struct Folder {
    folders: BTreeMap<String, Folder>,
    files: Vec<String>,
    count: usize,
}

impl Folder {
    fn insert(&mut self, path: &str) {
        self.count += 1;
        match path.split_once('/') {
            Some((head, rest)) => self
                .folders
                .entry(head.to_owned())
                .or_default()
                .insert(rest),
            None => self.files.push(path.to_owned()),
        }
    }
    /// Paths in display order: folders first, then files, each by name.
    fn walk(&self, prefix: &str, out: &mut Vec<String>) {
        let mut folders: Vec<_> = self.folders.iter().collect();
        folders.sort_by_key(|(name, _)| name.to_lowercase());
        for (name, folder) in folders {
            folder.walk(&join(prefix, name), out);
        }
        let mut files: Vec<_> = self.files.iter().collect();
        files.sort_by_key(|name| name.to_lowercase());
        out.extend(files.into_iter().map(|name| join(prefix, name)));
    }
}

const STACK_BELOW: f32 = 760.;

fn join(prefix: &str, name: &str) -> String {
    if prefix.is_empty() {
        name.to_owned()
    } else {
        format!("{prefix}/{name}")
    }
}

/// A file or folder name with no path separators.
fn segment(name: &str) -> String {
    let clean: String = name
        .trim()
        .chars()
        .map(|c| if matches!(c, '/' | '\\') { '-' } else { c })
        .collect();
    if clean.is_empty() {
        "Untitled".into()
    } else {
        clean
    }
}

/// `report.md` → `report (2).md`.
fn numbered(name: &str, n: usize) -> String {
    match name.rsplit_once('.') {
        Some((stem, ext)) if !stem.is_empty() => format!("{stem} ({n}).{ext}"),
        _ => format!("{name} ({n})"),
    }
}

/// One folder name per task: its title, told apart by a short id when titles repeat.
fn task_folders(state: &TopicState, artifacts: &[TaskArtifact]) -> BTreeMap<TaskId, String> {
    let ids: BTreeSet<TaskId> = artifacts.iter().map(|a| a.task).collect();
    let title = |id: TaskId| {
        state
            .tasks
            .iter()
            .find(|t| t.id == id)
            .map_or_else(|| "Removed task".into(), |t| segment(&t.title))
    };
    let mut seen: BTreeMap<String, usize> = BTreeMap::new();
    for id in &ids {
        *seen.entry(title(*id).to_lowercase()).or_default() += 1;
    }
    ids.into_iter()
        .map(|id| {
            let name = title(id);
            let name = if seen[&name.to_lowercase()] > 1 {
                let short = id.to_string();
                format!("{name} · {}", &short[..short.len().min(6)])
            } else {
                name
            };
            (id, name)
        })
        .collect()
}

/// Where each artifact sits: `tasks/<task>/<name>`, numbered past any path already taken.
fn place_artifacts(
    state: &TopicState,
    artifacts: &[TaskArtifact],
    out: &mut BTreeMap<String, Entry>,
) {
    let folders = task_folders(state, artifacts);
    for a in artifacts {
        let base = segment(&a.name);
        let folder = format!("{TASKS}/{}", folders[&a.task]);
        let mut path = join(&folder, &base);
        let mut n = 2;
        while out.contains_key(&path) {
            path = join(&folder, &numbered(&base, n));
            n += 1;
        }
        out.insert(path, Entry::Artifact(Box::new(a.clone())));
    }
}

fn kind_label(kind: &str) -> &str {
    match kind {
        "document" => "Document",
        "spreadsheet" => "Spreadsheet",
        "dashboard" => "Dashboard",
        "slack_canvas" => "Slack canvas",
        "slack_message" => "Slack message",
        "github_pr" => "Pull request",
        "plan" => "Plan",
        _ => "File",
    }
}

fn glyph_for(path: &str, entry: &Entry) -> Glyph {
    match entry {
        Entry::Artifact(a) if a.kind.starts_with("slack_") || a.kind == "github_pr" => {
            Glyph::ExternalLink
        }
        Entry::Artifact(a) if a.kind == "spreadsheet" => Glyph::Table2,
        _ => super::previews::glyph(path),
    }
}

impl Desktop {
    /// Every file in the topic's tree and what it holds.
    pub(super) fn file_entries(&self, state: &TopicState) -> BTreeMap<String, Entry> {
        let mut out = self.topic_file_entries(state);
        if let Some(Ok(artifacts)) = self.artifacts.get(&state.topic.id) {
            place_artifacts(state, artifacts, &mut out);
        }
        out
    }

    pub(super) fn file_count(&self, state: &TopicState) -> usize {
        let artifacts = self
            .artifacts
            .get(&state.topic.id)
            .and_then(|result| result.as_ref().ok());
        self.topic_file_entries(state).len() + artifacts.map_or(0, Vec::len)
    }

    fn topic_file_entries(&self, state: &TopicState) -> BTreeMap<String, Entry> {
        let mut out: BTreeMap<String, Entry> = self
            .client()
            .cached_files(state.topic.id)
            .unwrap_or_default()
            .into_iter()
            .map(|p| (p, Entry::File))
            .collect();
        for thread in &state.threads {
            for outcome in &thread.outcomes {
                if let Outcome::File(p) = outcome {
                    out.entry(p.clone()).or_insert(Entry::File);
                }
            }
        }
        out
    }

    /// Whether a Files path names a task artifact rather than a topic file.
    pub(super) fn is_artifact(&self, topic: TopicId, path: &str) -> bool {
        self.states
            .iter()
            .find(|s| s.topic.id == topic)
            .is_some_and(|state| {
                matches!(self.file_entries(state).get(path), Some(Entry::Artifact(_)))
            })
    }

    /// File paths in the order the tree shows them.
    pub(super) fn file_order(&self, state: &TopicState) -> Vec<String> {
        let mut root = Folder::default();
        for path in self.file_entries(state).keys() {
            root.insert(path);
        }
        let mut out = vec![];
        root.walk("", &mut out);
        out
    }

    /// Top-level folders start open; deeper ones start closed. A click flips either.
    fn folder_open(&self, topic: TopicId, path: &str) -> bool {
        let toggled = self
            .file_folders
            .get(&topic)
            .is_some_and(|t| t.contains(path));
        !path.contains('/') ^ toggled
    }

    fn toggle_folder(&mut self, topic: TopicId, path: &str) {
        let toggled = self.file_folders.entry(topic).or_default();
        if !toggled.remove(path) {
            toggled.insert(path.to_owned());
        }
    }

    /// Open every folder above a file so selecting it shows it.
    pub(super) fn reveal_file(&mut self, topic: TopicId, path: &str) {
        let mut at = 0;
        while let Some(i) = path[at..].find('/') {
            let folder = &path[..at + i];
            if !self.folder_open(topic, folder) {
                self.toggle_folder(topic, folder);
            }
            at += i + 1;
        }
    }

    /// List the topic's task artifacts unless a recent listing is still fresh.
    pub(super) fn refresh_artifacts(
        &mut self,
        topic: TopicId,
        force: bool,
        w: &Window,
        cx: &mut Context<Self>,
    ) {
        if !force
            && self
                .artifacts_at
                .get(&topic)
                .is_some_and(|at| at.elapsed() < FRESH)
        {
            return;
        }
        self.artifacts_at.insert(topic, std::time::Instant::now());
        let c = self.client().clone();
        self.job(
            async move { c.task_artifacts(topic).await },
            w,
            cx,
            move |s, r, w, cx| {
                let r = r.map(|mut list| {
                    list.sort_by(|a, b| {
                        (a.task, a.name.to_lowercase(), &a.updated_at).cmp(&(
                            b.task,
                            b.name.to_lowercase(),
                            &b.updated_at,
                        ))
                    });
                    list
                });
                if r.is_err() {
                    // Let the next visit try again.
                    s.artifacts_at.remove(&topic);
                }
                s.artifacts.insert(topic, r.map_err(|e| format!("{e:#}")));
                s.open_artifact(w, cx);
            },
        );
    }

    /// Read the selected artifact, from the device cache or PostHog.
    pub(super) fn open_artifact(&mut self, w: &Window, cx: &mut Context<Self>) {
        let Page::Topic(topic, Tab::Files, Some(Detail::File(ref path))) = self.page else {
            return;
        };
        let Some(state) = self.states.iter().find(|s| s.topic.id == topic) else {
            return;
        };
        let Some(Entry::Artifact(artifact)) = self.file_entries(state).remove(path) else {
            return;
        };
        let key = artifact.cache_key();
        if self.artifact_open.as_ref().is_some_and(|(k, _)| *k == key) {
            return;
        }
        if let Ok(Some(bytes)) = self.client().cached_artifact(&artifact) {
            self.artifact_open = Some((key, Ok(bytes)));
            return;
        }
        self.artifact_open = Some((key.clone(), Err(String::new())));
        let c = self.client().clone();
        self.job(
            async move { c.artifact(topic, &artifact).await },
            w,
            cx,
            move |s, r, _, _| {
                if s.artifact_open.as_ref().is_some_and(|(k, _)| *k == key) {
                    s.artifact_open = Some((
                        key,
                        r.map_err(|e| {
                            let text = format!("{e:#}");
                            if text.contains("too large") {
                                "This file is too large to preview here.".into()
                            } else {
                                text
                            }
                        }),
                    ));
                }
            },
        );
    }

    /// The folder tree beside the open file.
    fn file_tree(
        &self,
        state: &TopicState,
        entries: &BTreeMap<String, Entry>,
        chosen: &str,
        cx: &Context<Self>,
    ) -> Div {
        let id = state.topic.id;
        let mut root = Folder::default();
        for path in entries.keys() {
            root.insert(path);
        }
        let mut list = ui::column().gap(px(1.));
        let mut rows = vec![];
        self.tree_rows(state, &root, "", 0, entries, chosen, &mut rows, cx);
        list = list.children(rows);
        match self.artifacts.get(&id) {
            None => list.child(ui::caption("Listing task files…").px(px(8.)).pt(px(10.))),
            Some(Err(error)) => list.child(
                ui::column()
                    .gap(px(6.))
                    .px(px(8.))
                    .pt(px(12.))
                    .child(ui::caption(format!("Task files unavailable · {error}")))
                    .child(control(
                        "retry-artifacts",
                        "Try again",
                        false,
                        cx,
                        move |s, w, cx| s.refresh_artifacts(id, true, w, cx),
                    )),
            ),
            Some(Ok(_)) => list,
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn tree_rows(
        &self,
        state: &TopicState,
        folder: &Folder,
        prefix: &str,
        depth: usize,
        entries: &BTreeMap<String, Entry>,
        chosen: &str,
        rows: &mut Vec<AnyElement>,
        cx: &Context<Self>,
    ) {
        let id = state.topic.id;
        let indent = px(8. + depth as f32 * 16.);
        let mut folders: Vec<_> = folder.folders.iter().collect();
        folders.sort_by_key(|(name, _)| name.to_lowercase());
        for (name, child) in folders {
            let path = join(prefix, name);
            let open = self.folder_open(id, &path);
            // A task's folder says where that task stands.
            let status = (prefix == TASKS)
                .then(|| {
                    entries.iter().find_map(|(p, e)| match e {
                        Entry::Artifact(a) if p.starts_with(&format!("{path}/")) => {
                            state.tasks.iter().find(|t| t.id == a.task)
                        }
                        _ => None,
                    })
                })
                .flatten()
                .map(|t| t.column);
            let toggle = path.clone();
            rows.push(
                line(format!("folder-{path}"), false)
                    .h(px(30.))
                    .py_0()
                    .pl(indent)
                    .gap(px(6.))
                    .child(
                        div().flex_none().w(px(12.)).child(
                            Icon::new(if open {
                                Glyph::ChevronDown
                            } else {
                                Glyph::ChevronRight
                            })
                            .size(px(12.))
                            .text_color(rgb(ui::theme::color(ui::TERTIARY))),
                        ),
                    )
                    .child(ui::nav::glyph(
                        if open {
                            Glyph::FolderOpen
                        } else {
                            Glyph::Folder
                        },
                        false,
                    ))
                    .child(ui::nav::title(name.clone()))
                    .children(status.filter(|c| *c != Column::Done).map(|c| {
                        div()
                            .flex_none()
                            .text_size(px(11.5))
                            .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                            .child(column_name(c))
                    }))
                    .child(badge(child.count))
                    .on_click(cx.listener(move |s, _, _, cx| {
                        s.toggle_folder(id, &toggle);
                        let open = s.folder_open(id, &toggle);
                        s.folds.toggled(format!("folder-{id}-{toggle}"), open, cx);
                        cx.notify()
                    }))
                    .into_any_element(),
            );
            let fold = format!("folder-{id}-{path}");
            if open || self.folds.progress(&fold, open, cx) > 0. {
                let mut inner = vec![];
                self.tree_rows(
                    state,
                    child,
                    &path,
                    depth + 1,
                    entries,
                    chosen,
                    &mut inner,
                    cx,
                );
                rows.extend(self.folds.reveal(&fold, open, cx, || {
                    ui::column().gap(px(1.)).children(inner).into_any_element()
                }));
            }
        }
        let mut files: Vec<_> = folder.files.iter().collect();
        files.sort_by_key(|name| name.to_lowercase());
        for name in files {
            let path = join(prefix, name);
            let active = path == chosen;
            let glyph = entries
                .get(&path)
                .map_or(Glyph::FileText, |e| glyph_for(&path, e));
            let go = path.clone();
            rows.push(
                line(format!("file-{path}"), active)
                    .h(px(30.))
                    .py_0()
                    .pl(indent)
                    .gap(px(6.))
                    // Files line up with folder names, past the chevron column.
                    .child(div().flex_none().w(px(12.)))
                    .child(ui::nav::glyph(glyph, active))
                    .child(ui::nav::title(name.clone()))
                    .on_click(cx.listener(move |s, _, w, cx| {
                        s.go(
                            Page::Topic(id, Tab::Files, Some(Detail::File(go.clone()))),
                            w,
                            cx,
                        )
                    }))
                    .into_any_element(),
            );
        }
    }

    pub(super) fn shown_file(&self, state: &TopicState) -> Option<String> {
        match &self.page {
            Page::Topic(_, Tab::Files, Some(Detail::File(p) | Detail::Table(p)))
                if self.file_entries(state).contains_key(p) =>
            {
                Some(p.clone())
            }
            _ => None,
        }
    }

    pub(super) fn file_meta(&self, state: &TopicState, path: &str) -> String {
        let id = state.topic.id;
        let parts = match self.file_entries(state).get(path) {
            Some(Entry::Artifact(a)) => vec![
                match kind_label(&a.kind) {
                    "File" => String::new(),
                    k => k.to_owned(),
                },
                a.size.map(|n| human_size(n as usize)).unwrap_or_default(),
                if a.version > 1 {
                    format!("v{}", a.version)
                } else {
                    String::new()
                },
            ],
            _ => match self.client().cached_file(id, path) {
                Ok(Some(f)) => vec![
                    if f.revision == 0 {
                        "Queued for upload".into()
                    } else {
                        String::new()
                    },
                    human_size(f.bytes.len()),
                ],
                Ok(None) => vec!["Fetching…".into()],
                Err(e) => vec![e.to_string()],
            },
        };
        parts
            .into_iter()
            .filter(|part| !part.is_empty())
            .collect::<Vec<_>>()
            .join(" · ")
    }

    pub(super) fn file_tools(
        &self,
        state: &TopicState,
        path: &str,
        split: bool,
        cx: &Context<Self>,
    ) -> Vec<AnyElement> {
        let id = state.topic.id;
        let artifact = match self.file_entries(state).get(path) {
            Some(Entry::Artifact(a)) => Some(a.clone()),
            _ => None,
        };
        let task = state.tasks.iter().find(|t| match &artifact {
            Some(a) => t.id == a.task,
            None => t.files.iter().any(|f| f == path),
        });
        let mut tools = vec![];
        if split {
            let hidden = self.files_tree_hidden;
            let label = if hidden {
                "Show file tree"
            } else {
                "Hide file tree"
            };
            tools.push(
                ui::icon_button(
                    "toggle-file-tree",
                    if hidden {
                        Glyph::PanelLeftOpen
                    } else {
                        Glyph::PanelLeftClose
                    },
                    label,
                )
                .tooltip(label)
                .on_click(cx.listener(|s, _, _, cx| {
                    s.files_tree_hidden = !s.files_tree_hidden;
                    cx.notify()
                }))
                .into_any_element(),
            );
        }
        if let Some(t) = task {
            let task = t.id;
            tools.push(
                ui::button(format!("file-task-{task}"), "Open task")
                    .icon(Glyph::Kanban)
                    .self_center()
                    .tooltip(short_subject(&t.title))
                    .on_click(cx.listener(move |s, _, w, cx| {
                        s.go(Page::Topic(id, Tab::Tasks, Some(Detail::Task(task))), w, cx)
                    }))
                    .into_any_element(),
            );
        }
        match artifact {
            Some(a) => {
                if let Some(url) = a.url {
                    tools.push(
                        ui::icon_button("open-artifact", Glyph::ExternalLink, "Open in PostHog")
                            .tooltip("Open in PostHog")
                            .on_click(move |_, _, cx| cx.open_url(&url))
                            .into_any_element(),
                    );
                }
            }
            None => {
                let path = path.to_owned();
                tools.push(
                    ui::icon_button("delete-file", Glyph::Trash, "Delete file")
                        .tooltip("Delete file")
                        .on_click(cx.listener(move |s, _, w, cx| {
                            if s.issue(id, Command::DeleteFile { path: path.clone() }) {
                                s.go(Page::Topic(id, Tab::Files, None), w, cx)
                            }
                        }))
                        .into_any_element(),
                );
            }
        }
        tools
    }

    /// One place for everything the topic and its tasks wrote: a folder tree on
    /// the left, the selected file on the right. Tables open as a grid.
    pub(super) fn files_stacked(&self, w: &Window) -> bool {
        self.topic_pane_width(w) < px(STACK_BELOW)
    }

    pub(super) fn data_page(&self, state: &TopicState, cx: &Context<Self>) -> Div {
        let id = state.topic.id;
        let entries = self.file_entries(state);
        if entries.is_empty() {
            let empty = deck(
                Glyph::FileText,
                0x9a9a9a,
                "Nothing written yet",
                "Files",
                [
                    "Notes, reports and tables this topic and its tasks write are kept here.",
                    "Ask it for one in chat.",
                ],
            );
            return match self.artifacts.get(&id) {
                Some(Err(_)) => ui::column()
                    .gap(px(16.))
                    .child(empty)
                    .child(self.file_tree(state, &entries, "", cx)),
                _ => empty,
            };
        }
        match self.shown_file(state) {
            Some(chosen) => self.file_body(state, &chosen, cx).w_full(),
            None => self
                .file_tree(state, &entries, "", cx)
                .w_full()
                .max_w(px(720.))
                .mx_auto(),
        }
    }

    fn file_body(&self, state: &TopicState, chosen: &str, cx: &Context<Self>) -> Div {
        match self.file_entries(state).get(chosen) {
            Some(Entry::Artifact(a)) => self.artifact_view(chosen, a, cx),
            _ => self.topic_file_view(state, chosen, cx),
        }
    }

    pub(super) fn files_split(
        &self,
        state: &TopicState,
        w: &Window,
        cx: &Context<Self>,
    ) -> Option<Div> {
        if self.files_stacked(w) {
            return None;
        }
        let chosen = self.shown_file(state)?;
        let entries = self.file_entries(state);
        let hidden = self.files_tree_hidden;
        Some(
            ui::row()
                .size_full()
                .min_h_0()
                .items_start()
                .when(!hidden, |row| {
                    row.child(
                        scroll("files-tree")
                            .flex_none()
                            .flex_grow_0()
                            .h_full()
                            .w(px(250. + super::details::PAGE_X))
                            .pl(px(super::details::PAGE_X))
                            .pt(px(super::details::PAGE_TOP))
                            .pb(px(12.))
                            .child(self.file_tree(state, &entries, &chosen, cx).w_full()),
                    )
                })
                .child(
                    scroll("files-content")
                        .track_scroll(&self.content_scroll)
                        .h_full()
                        .min_w_0()
                        .pl(px(if hidden { super::details::PAGE_X } else { 24. }))
                        .pr(px(super::details::PAGE_X))
                        .pt(px(super::details::PAGE_TOP))
                        .pb(px(12.))
                        .child(self.review_links(state, Tab::Files, cx))
                        .child(self.file_body(state, &chosen, cx).w_full()),
                ),
        )
    }

    fn topic_file_view(&self, state: &TopicState, chosen: &str, cx: &Context<Self>) -> Div {
        match self.client().cached_file(state.topic.id, chosen) {
            Ok(Some(f)) => super::previews::render(chosen, &f.bytes, cx),
            _ => div(),
        }
    }

    fn artifact_view(&self, chosen: &str, a: &TaskArtifact, cx: &Context<Self>) -> Div {
        match &self.artifact_open {
            Some((key, Ok(bytes))) if *key == a.cache_key() => {
                super::previews::render(chosen, bytes, cx)
            }
            Some((key, Err(e))) if *key == a.cache_key() && !e.is_empty() => ui::caption(e.clone()),
            _ => ui::caption("Fetching from PostHog…"),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[core::prelude::v1::test]
    fn tree_orders_folders_first_and_numbers_clashing_names() {
        let mut root = Folder::default();
        for p in [
            "notes.md",
            "tasks/B/x.md",
            "tasks/A/y.md",
            "reports/w.md",
            "a.md",
        ] {
            root.insert(p);
        }
        let mut out = vec![];
        root.walk("", &mut out);
        assert_eq!(
            out,
            [
                "reports/w.md",
                "tasks/A/y.md",
                "tasks/B/x.md",
                "a.md",
                "notes.md"
            ]
        );
        assert_eq!(root.folders["tasks"].count, 2);
        assert_eq!(numbered("report.md", 2), "report (2).md");
        assert_eq!(numbered("README", 3), "README (3)");
        assert_eq!(segment(" a/b "), "a-b");
    }
}
