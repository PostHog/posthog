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
        _ if super::tables::tabular(path) => Glyph::Table2,
        _ => Glyph::FileText,
    }
}

impl Desktop {
    /// Every file in the topic's tree and what it holds.
    pub(super) fn file_entries(&self, state: &TopicState) -> BTreeMap<String, Entry> {
        let id = state.topic.id;
        let mut out: BTreeMap<String, Entry> = self
            .client()
            .cached_files(id)
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
        if let Some(Ok(artifacts)) = self.artifacts.get(&id) {
            place_artifacts(state, artifacts, &mut out);
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
        let mut list = ui::column().w(px(260.)).flex_none().gap(px(1.));
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
                .map(|t| column_name(t.column));
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
                    .children(status.map(|s| {
                        div()
                            .flex_none()
                            .text_size(px(11.5))
                            .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                            .child(s)
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

    /// `tasks › Funnel drop-off › findings.md`, each folder a way back into the tree.
    fn file_crumbs(&self, topic: TopicId, path: &str, cx: &Context<Self>) -> Div {
        let mut row = ui::row().min_w_0().flex_wrap().gap(px(6.));
        let parts: Vec<&str> = path.split('/').collect();
        let mut at = String::new();
        for (i, part) in parts.iter().enumerate() {
            if i > 0 {
                at.push('/');
                row = row.child(
                    Icon::new(Glyph::ChevronRight)
                        .size(px(11.))
                        .text_color(rgb(ui::theme::color(ui::TERTIARY))),
                );
            }
            at.push_str(part);
            if i + 1 == parts.len() {
                row = row.child(
                    div()
                        .text_size(px(15.))
                        .font_weight(FontWeight::SEMIBOLD)
                        .truncate()
                        .child(part.to_string()),
                );
            } else {
                let folder = at.clone();
                row = row.child(
                    div()
                        .id(SharedString::from(format!("crumb-{folder}")))
                        .role(Role::Link)
                        .cursor_pointer()
                        .text_size(px(13.))
                        .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                        .hover(|s| s.text_color(rgb(ui::theme::color(ui::INK))))
                        .child(part.to_string())
                        .on_click(cx.listener(move |s, _, _, cx| {
                            s.reveal_file(topic, &format!("{folder}/"));
                            cx.notify()
                        })),
                );
            }
        }
        row
    }

    /// A link to the task a file came from.
    fn task_link(
        &self,
        topic: TopicId,
        task: &meep_topic::Task,
        verb: &str,
        cx: &Context<Self>,
    ) -> Button {
        let id = task.id;
        control(
            format!("file-task-{id}"),
            format!("{verb} “{}”", short_subject(&task.title)),
            false,
            cx,
            move |s, w, cx| {
                s.go(
                    Page::Topic(topic, Tab::Tasks, Some(Detail::Task(id))),
                    w,
                    cx,
                )
            },
        )
        .icon(Glyph::Kanban)
    }

    /// One place for everything the topic and its tasks wrote: a folder tree on
    /// the left, the selected file on the right. Tables open as a grid.
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
        let chosen = match &self.page {
            Page::Topic(_, _, Some(Detail::File(p) | Detail::Table(p)))
                if entries.contains_key(p) =>
            {
                p.clone()
            }
            _ => self
                .file_order(state)
                .into_iter()
                .next()
                .unwrap_or_default(),
        };
        let tree = self.file_tree(state, &entries, &chosen, cx);
        let (head, content) = match entries.get(&chosen) {
            Some(Entry::Artifact(a)) => self.artifact_view(state, &chosen, a, cx),
            _ => self.topic_file_view(state, &chosen, cx),
        };
        ui::row()
            .items_start()
            .gap(px(28.))
            .w_full()
            .child(tree)
            .child(
                ui::column()
                    .flex_1()
                    .min_w_0()
                    .gap(px(16.))
                    .child(head)
                    .child(content),
            )
    }

    fn file_head(&self, topic: TopicId, path: &str, meta: String, cx: &Context<Self>) -> Div {
        ui::column()
            .gap(px(10.))
            .pb(px(14.))
            .border_b_1()
            .border_color(ui::ink(0x0f))
            .child(
                ui::column()
                    .min_w_0()
                    .gap(px(4.))
                    .child(self.file_crumbs(topic, path, cx))
                    .child(ui::caption(meta)),
            )
    }

    fn topic_file_view(&self, state: &TopicState, chosen: &str, cx: &Context<Self>) -> (Div, Div) {
        let id = state.topic.id;
        let file = self.client().cached_file(id, chosen);
        let meta = match &file {
            Ok(Some(f)) => [
                if f.revision == 0 {
                    "Queued for upload".into()
                } else {
                    String::new()
                },
                human_size(f.bytes.len()),
            ]
            .into_iter()
            .filter(|part| !part.is_empty())
            .collect::<Vec<_>>()
            .join(" · "),
            Ok(None) => "Fetching…".into(),
            Err(e) => e.to_string(),
        };
        let path = chosen.to_owned();
        let writer = state
            .tasks
            .iter()
            .find(|t| t.files.iter().any(|f| f == chosen));
        let head = self.file_head(id, chosen, meta, cx).child(
            ui::row()
                .flex_wrap()
                .gap(px(8.))
                .child(
                    control(
                        "chat-file",
                        "Ask about this file",
                        false,
                        cx,
                        move |s, w, cx| {
                            s.chat_reference = Some(path.clone());
                            s.open_chat(w, cx);
                            s.composer.focus_handle(cx).focus(w, cx);
                        },
                    )
                    .icon(Glyph::MessageCircle),
                )
                .children(writer.map(|t| self.task_link(id, t, "Written by", cx)))
                .child({
                    let path = chosen.to_owned();
                    control("delete-file", "Delete", false, cx, move |s, w, cx| {
                        if s.issue(id, Command::DeleteFile { path: path.clone() }) {
                            s.go(Page::Topic(id, Tab::Files, None), w, cx)
                        }
                    })
                }),
        );
        let content = match &file {
            Ok(Some(f)) => preview(chosen, &f.bytes),
            _ => div(),
        };
        (head, content)
    }

    fn artifact_view(
        &self,
        state: &TopicState,
        chosen: &str,
        a: &TaskArtifact,
        cx: &Context<Self>,
    ) -> (Div, Div) {
        let id = state.topic.id;
        let meta = [
            kind_label(&a.kind).to_owned(),
            a.size.map(|n| human_size(n as usize)).unwrap_or_default(),
            if a.version > 1 {
                format!("v{}", a.version)
            } else {
                String::new()
            },
        ]
        .into_iter()
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join(" · ");
        let task = state.tasks.iter().find(|t| t.id == a.task);
        let head = self.file_head(id, chosen, meta, cx).child(
            ui::row()
                .flex_wrap()
                .gap(px(8.))
                .children(task.map(|t| self.task_link(id, t, "From task", cx)))
                .children(a.url.clone().map(|url| {
                    control("open-artifact", "Open", false, cx, move |_, _, cx| {
                        cx.open_url(&url)
                    })
                    .icon(Glyph::ExternalLink)
                })),
        );
        let content = match &self.artifact_open {
            Some((key, Ok(bytes))) if *key == a.cache_key() => preview(chosen, bytes),
            Some((key, Err(e))) if *key == a.cache_key() && !e.is_empty() => ui::caption(e.clone()),
            _ => ui::caption("Fetching from PostHog…"),
        };
        (head, content)
    }
}

/// A file's contents: a grid for tables, text otherwise.
fn preview(path: &str, bytes: &[u8]) -> Div {
    if super::tables::tabular(path) {
        return super::tables::render(path, bytes);
    }
    match std::str::from_utf8(bytes) {
        Ok(text) => div()
            .max_w(px(ui::READING_MEASURE))
            .line_height(relative(1.6))
            .whitespace_normal()
            .child(text.chars().take(80_000).collect::<String>()),
        Err(_) => ui::caption("This file can’t be previewed here."),
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
