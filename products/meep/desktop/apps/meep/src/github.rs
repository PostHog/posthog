use super::*;
use meep_shell::settings::{self as set, Tone, group, section};
use meep_ui::gpui_kit::component::Disableable;

#[derive(Default)]
pub(super) struct Github {
    pub data: Option<backend::GithubAccount>,
    busy: bool,
    failed: bool,
    refresh_requested: bool,
    browser_open: bool,
    picker: Option<TopicId>,
    shown: usize,
}

const PAGE: usize = 20;

fn github_tile() -> Div {
    set::logo_tile().child(meep_render::brands::logo("github", 16.))
}

fn account_row(title: impl Into<SharedString>, detail: &str, trailing: impl IntoElement) -> Div {
    ui::row()
        .w_full()
        .min_h(px(60.))
        .px(px(set::ROW_X))
        .py(px(12.))
        .gap(px(12.))
        .child(github_tile())
        .child(set::copy(title, detail.to_owned()).min_w(px(64.)))
        .child(div().flex_none().child(trailing))
}

impl Desktop {
    pub(super) fn refresh_github(&mut self, w: &Window, cx: &mut Context<Self>) {
        if self.identity.is_none() {
            return;
        }
        if self.github.busy {
            self.github.refresh_requested = true;
            return;
        }
        self.github.busy = true;
        let backend = self.backend.clone();
        let repositories = self.github.picker.is_some();
        self.job(
            async move { backend.github_account(repositories).await },
            w,
            cx,
            |s, result, w, cx| {
                s.github.busy = false;
                if s.identity.is_none() {
                    return;
                }
                if std::mem::take(&mut s.github.refresh_requested) {
                    s.refresh_github(w, cx);
                    return;
                }
                match result {
                    Ok(data) => {
                        s.github.failed = false;
                        s.github.data = Some(data);
                    }
                    Err(_) => {
                        s.github.failed = true;
                        s.github.data = None;
                    }
                }
            },
        );
    }

    pub(super) fn github_return(&mut self, w: &Window, cx: &mut Context<Self>) {
        if self.github.browser_open {
            self.github.browser_open = false;
            self.refresh_github(w, cx);
        }
    }

    fn attach_repository(&mut self, topic: TopicId, previous: Option<WatchId>, repository: String) {
        self.issue(
            topic,
            Command::SelectGithubRepository {
                previous,
                id: Uuid::new_v4().into(),
                repository,
            },
        );
        self.github.picker = None;
    }

    fn open_github_settings(&mut self, cx: &mut Context<Self>) {
        if let Some(identity) = &self.identity {
            self.github.picker = None;
            self.github.browser_open = true;
            cx.open_url(&identity.github_settings_url());
        }
    }

    fn checking_github(&self) -> bool {
        self.github.busy && self.github.data.is_none()
    }

    pub(super) fn github_settings(&self, cx: &Context<Self>) -> Div {
        let data = self.github.data.as_ref();
        let connected = data.is_some_and(|d| !d.accounts.is_empty());
        let waiting = self.github.browser_open;
        let action = (!self.checking_github() && !self.github.failed).then(|| {
            let label = match (waiting, connected) {
                (true, _) => "Waiting for PostHog…",
                (false, true) => "Manage in PostHog",
                (false, false) => "Connect GitHub",
            };
            control(
                "github-connect",
                label,
                !connected && !waiting,
                cx,
                |s, _, cx| s.open_github_settings(cx),
            )
            .disabled(waiting)
            .into_any_element()
        });
        let mut rows = Vec::new();
        if self.checking_github() {
            rows.push(account_row("Checking GitHub…", "", div()));
        } else if self.github.failed {
            rows.push(account_row(
                "Couldn’t check GitHub",
                "PostHog didn’t answer. Your connection is unchanged.",
                control("github-retry", "Try again", false, cx, |s, w, cx| {
                    s.refresh_github(w, cx)
                }),
            ));
        } else if let Some(data) = data {
            for login in &data.accounts {
                rows.push(account_row(
                    login.clone(),
                    "Topics can read the repositories it shares",
                    set::status("Connected", Tone::Positive),
                ));
            }
            if data.needs_reconnect {
                rows.push(account_row(
                    "Connection expired",
                    "Reconnect in PostHog to restore repository access.",
                    control("github-reconnect", "Reconnect", false, cx, |s, _, cx| {
                        s.open_github_settings(cx)
                    }),
                ));
            }
            if data.pending {
                rows.push(account_row(
                    "Waiting for approval",
                    "An organization owner must approve the PostHog app on GitHub.",
                    set::status("Pending", Tone::Warning),
                ));
            }
            if rows.is_empty() {
                rows.push(account_row(
                    "No GitHub account linked",
                    "Connect one so topics can read a repository.",
                    div(),
                ));
            }
        }
        ui::column()
            .child(section(
                "GitHub",
                "Your GitHub account, for repository context in every topic.",
                action,
                false,
            ))
            .child(group(rows.into_iter().map(IntoElement::into_any_element)))
            .when(waiting, |col| {
                col.child(set::note("Finish in your browser, then come back to Meep."))
            })
    }

    pub(super) fn github_selected(topic: &Topic) -> Option<&Watch> {
        topic
            .context_sources
            .iter()
            .find(|s| s.connection == "github" && s.kind == "repository")
    }

    fn open_picker(&mut self, id: TopicId, w: &Window, cx: &mut Context<Self>) {
        self.github.picker = Some(id);
        self.github.shown = PAGE;
        self.refresh_github(w, cx);
    }

    pub(super) fn github_section(&self, topic: &Topic, cx: &Context<Self>) -> Div {
        let id = topic.id;
        let selected = Self::github_selected(topic);
        let open = self.github.picker == Some(id);
        let connected = self
            .github
            .data
            .as_ref()
            .is_some_and(|d| !d.accounts.is_empty());
        let ready = connected && !self.checking_github() && !self.github.failed;
        let action = ready.then(|| {
            if open {
                control("github-picker-close", "Cancel", false, cx, |s, _, _| {
                    s.github.picker = None
                })
            } else {
                control(
                    "github-choose",
                    if selected.is_some() {
                        "Change"
                    } else {
                        "Choose repository"
                    },
                    false,
                    cx,
                    move |s, w, cx| s.open_picker(id, w, cx),
                )
            }
            .into_any_element()
        });
        let mut rows: Vec<AnyElement> = Vec::new();
        if self.checking_github() {
            rows.push(account_row("Checking GitHub…", "", div()).into_any_element());
        } else if self.github.failed && !open {
            rows.push(
                account_row(
                    "Couldn’t check GitHub",
                    "PostHog didn’t answer. The repository stays linked.",
                    control("github-retry", "Try again", false, cx, |s, w, cx| {
                        s.refresh_github(w, cx)
                    }),
                )
                .into_any_element(),
            );
        } else if !connected {
            rows.push(
                account_row(
                    "No GitHub account linked",
                    "Connect GitHub in Settings to choose a repository.",
                    control("github-settings", "Open Settings", false, cx, |s, w, cx| {
                        s.settings_page = SettingsPage::General;
                        s.go(Page::Settings, w, cx)
                    }),
                )
                .into_any_element(),
            );
        } else if let Some(repo) = selected.filter(|_| !open) {
            let source = repo.id;
            rows.push(
                account_row(
                    repo.label.clone(),
                    "Topic chat can read this code",
                    control("github-remove", "Remove", false, cx, move |s, _, _| {
                        s.github.picker = None;
                        s.issue(id, Command::RemoveContextSource { source });
                    }),
                )
                .into_any_element(),
            );
        } else if !open {
            rows.push(
                account_row(
                    "No repository",
                    "Chat can look up a repository when it needs one.",
                    div(),
                )
                .into_any_element(),
            );
        }
        if open {
            rows.extend(self.github_picker_rows(topic, cx));
        }
        ui::column()
            .child(set::section(
                "Repository",
                "Save a repository for future questions in this topic.",
                action,
                false,
            ))
            .child(group(rows))
    }

    fn github_picker_rows(&self, topic: &Topic, cx: &Context<Self>) -> Vec<AnyElement> {
        let id = topic.id;
        let current = Self::github_selected(topic);
        let previous = current.map(|s| s.id);
        let current_key = current.map(|s| s.key.to_lowercase());
        let repositories = self
            .github
            .data
            .as_ref()
            .map(|d| d.repositories.as_slice())
            .unwrap_or_default();
        let mut rows: Vec<AnyElement> = Vec::new();
        if self.github.failed {
            rows.push(
                account_row(
                    "Couldn’t load repositories",
                    "PostHog didn’t answer. Try again in a moment.",
                    control("github-picker-retry", "Try again", false, cx, |s, w, cx| {
                        s.refresh_github(w, cx)
                    }),
                )
                .into_any_element(),
            );
            return rows;
        }
        if repositories.is_empty() {
            rows.push(if self.github.busy {
                account_row("Loading repositories…", "", div()).into_any_element()
            } else {
                account_row(
                    "No repositories shared",
                    "Choose which repositories PostHog can read in Settings.",
                    control(
                        "github-picker-settings",
                        "Open Settings",
                        false,
                        cx,
                        |s, w, cx| {
                            s.github.picker = None;
                            s.settings_page = SettingsPage::General;
                            s.go(Page::Settings, w, cx)
                        },
                    ),
                )
                .into_any_element()
            });
            return rows;
        }
        for name in repositories.iter().take(self.github.shown) {
            let is_current = current_key.as_deref() == Some(name.to_lowercase().as_str());
            let repo = name.clone();
            let (owner, short) = name.split_once('/').unwrap_or(("", name.as_str()));
            rows.push(
                ui::row()
                    .id(SharedString::from(format!("github-{name}")))
                    .role(Role::Button)
                    .w_full()
                    .h(px(44.))
                    .px(px(set::ROW_X))
                    .gap(px(12.))
                    .text_size(px(13.))
                    .cursor_pointer()
                    .hover(|s| s.bg(ui::ink(0x05)))
                    .child(
                        div()
                            .size(px(32.))
                            .flex_none()
                            .flex()
                            .items_center()
                            .justify_center()
                            .when(is_current, |d| d.child(ui::nav::glyph(Glyph::Check, false))),
                    )
                    .child(
                        ui::row()
                            .flex_1()
                            .min_w_0()
                            .gap_0()
                            .overflow_hidden()
                            .child(
                                div()
                                    .flex_none()
                                    .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                                    .child(format!("{owner}/")),
                            )
                            .child(
                                div()
                                    .min_w_0()
                                    .truncate()
                                    .font_weight(FontWeight::MEDIUM)
                                    .text_color(rgb(ui::theme::color(ui::INK)))
                                    .child(short.to_owned()),
                            ),
                    )
                    .on_click(cx.listener(move |s, _, _, cx| {
                        if is_current {
                            s.github.picker = None;
                        } else {
                            s.attach_repository(id, previous, repo.clone());
                        }
                        cx.notify()
                    }))
                    .into_any_element(),
            );
        }
        let hidden = repositories.len().saturating_sub(self.github.shown);
        if hidden > 0 {
            rows.push(
                ui::row()
                    .id("github-more")
                    .role(Role::Button)
                    .w_full()
                    .h(px(44.))
                    .px(px(set::ROW_X))
                    .text_size(px(13.))
                    .font_weight(FontWeight::MEDIUM)
                    .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                    .cursor_pointer()
                    .hover(|s| {
                        s.bg(ui::ink(0x05))
                            .text_color(rgb(ui::theme::color(ui::INK)))
                    })
                    .gap(px(12.))
                    .child(div().size(px(32.)).flex_none())
                    .child(format!("Show {} more", hidden.min(PAGE)))
                    .on_click(cx.listener(|s, _, _, cx| {
                        s.github.shown += PAGE;
                        cx.notify()
                    }))
                    .into_any_element(),
            );
        }
        rows
    }
}
