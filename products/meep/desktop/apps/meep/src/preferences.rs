use super::mcp_settings::{policy_name, policy_picker};
use super::*;
use meep_notifications::{
    Authorization, Namespace, Notification, NotificationCenter, Publisher, SystemNotifications,
};
use meep_shell::settings::{danger, empty, group, header, item, section, value_text};
use meep_ui::gpui_kit::component::{Disableable, Sizable, switch::Switch};
use meep_wire::mcp_store::Policy;

#[derive(Clone, Copy, Serialize, Deserialize)]
pub(super) struct Alerts {
    pub enabled: bool,
    kinds: [bool; 3],
}
impl Default for Alerts {
    fn default() -> Self {
        Self {
            enabled: false,
            kinds: [true; 3],
        }
    }
}
fn alert(item: &NeedsYouItem) -> (usize, String, &str) {
    match item {
        NeedsYouItem::Decide {
            topic,
            thread,
            title,
            ..
        } => (0, format!("decision-{topic}-{thread}"), title),
        NeedsYouItem::Approve {
            topic,
            task,
            title,
            action: Some(action),
            ..
        } if action == "Reply" => (0, format!("question-{topic}-{task}"), title),
        NeedsYouItem::Approve {
            topic, task, title, ..
        } => (1, format!("approval-{topic}-{task}"), title),
        NeedsYouItem::Problem {
            connection, title, ..
        } => (2, format!("connection-{connection}"), title),
    }
}

impl Desktop {
    pub(super) fn deliver_alerts(
        &self,
        previous: &[NeedsYouItem],
        w: &Window,
        cx: &mut Context<Self>,
    ) {
        if !self.alerts.enabled || self.identity.is_none() {
            return;
        }
        let seen: HashSet<_> = previous.iter().map(|i| alert(i).1).collect();
        for item in &self.needs {
            let (kind, id, title) = alert(item);
            if !self.alerts.kinds[kind] || seen.contains(&id) {
                continue;
            }
            let notification = Notification {
                title: [
                    "A topic needs a decision",
                    "A task needs approval",
                    "Connection needs attention",
                ][kind]
                    .into(),
                body: title.into(),
                ..Default::default()
            };
            self.job(
                async move {
                    Publisher::new(&SystemNotifications, Namespace::new("meep")?)
                        .send(&id, &notification)
                        .await
                },
                w,
                cx,
                |s, result, _, _| {
                    if let Err(error) = result {
                        s.fail(
                            error.context("Meep couldn’t deliver the notification to this Mac."),
                        );
                    }
                },
            );
        }
    }
    fn set_alerts(&mut self, alerts: Alerts) {
        match self.client().set_preference("notifications", &alerts) {
            Ok(()) => self.alerts = alerts,
            Err(e) => self.fail(e),
        }
    }
    pub(super) fn notifications_page(&self, cx: &Context<Self>) -> Div {
        let enabled = self.alerts.enabled;
        ui::column()
            .gap_0()
            .child(header(
                "Notifications",
                "Choose what Meep sends to Notification Center on this Mac.",
                None,
            ))
            .child(section("Delivery", "", None, true))
            .child(group([item(
                "System notifications",
                "Notify me when something new needs my attention.",
                Switch::new("toggle-alerts")
                    .accessibility_label("System notifications")
                    .small()
                    .checked(enabled)
                    .on_change(cx.listener(|s, _, w, cx| {
                        if s.alerts.enabled {
                            s.set_alerts(Alerts {
                                enabled: false,
                                ..s.alerts
                            });
                        } else {
                            s.job(
                                async { SystemNotifications.request_authorization().await },
                                w,
                                cx,
                                |s, r, _, _| match r {
                                    Ok(Authorization::Authorized | Authorization::Provisional) => s
                                        .set_alerts(Alerts {
                                            enabled: true,
                                            ..s.alerts
                                        }),
                                    Ok(_) => {
                                        s.error = Some(
                                            "Allow Meep notifications in macOS System Settings."
                                                .into(),
                                        )
                                    }
                                    Err(e) => s.fail(e),
                                },
                            );
                        }
                        cx.notify();
                    })),
            )
            .into_any_element()]))
            .child(section(
                "Notify me about",
                if enabled {
                    ""
                } else {
                    "Turn on notifications to choose what reaches you."
                },
                None,
                false,
            ))
            .child(group(
                [
                    ("Decisions", "An inbox thread needs an answer."),
                    ("Approvals", "A task is waiting for review."),
                    ("Connection problems", "A watched service needs attention."),
                ]
                .into_iter()
                .enumerate()
                .map(|(i, (title, detail))| {
                    let on = self.alerts.kinds[i];
                    item(
                        title,
                        detail,
                        Switch::new(format!("alert-kind-{i}"))
                            .accessibility_label(title)
                            .small()
                            // Off with the master switch: nothing is sent, so
                            // nothing reads as on.
                            .checked(on && enabled)
                            .disabled(!enabled)
                            .on_change(cx.listener(move |s, value, _, cx| {
                                let mut prefs = s.alerts;
                                prefs.kinds[i] = *value;
                                s.set_alerts(prefs);
                                cx.notify()
                            })),
                    )
                    .when(!enabled, |row| row.opacity(0.6))
                    .into_any_element()
                }),
            ))
    }
    pub(super) fn shortcuts_page(&self) -> Div {
        let rows = |pairs: &[(&'static str, &'static str)]| {
            group(
                pairs
                    .iter()
                    .map(|(name, key)| item(*name, "", value_text(*key)).into_any_element()),
            )
        };
        ui::column()
            .gap_0()
            .child(header("Shortcuts", "Keyboard controls for Meep.", None))
            .child(section("Workspace", "", None, true))
            .child(rows(&[
                ("Search topics", "⌘ K"),
                ("New topic", "⌘ N"),
                ("Open settings", "⌘ ,"),
                ("Go back", "⌘ ["),
            ]))
            .child(section("Navigation", "", None, false))
            .child(rows(&[
                ("Previous or next item", "K / J  or  ↑ / ↓"),
                ("Select a search result", "Return"),
                ("Close a sheet or detail", "Esc"),
            ]))
            .child(section("Window", "", None, false))
            .child(rows(&[
                ("Close window", "⌘ W"),
                ("Hide Meep", "⌘ H"),
                ("Hide other apps", "⌥ ⌘ H"),
                ("Quit Meep", "⌘ Q"),
            ]))
    }
    pub(super) fn permissions_page(&self, cx: &Context<Self>) -> Div {
        let mut page = ui::column().gap_0().child(header(
            "Permissions",
            "Meep asks before taking an action unless a rule for that topic says otherwise.",
            None,
        ));
        if self.identity.is_none() {
            return page.child(empty("Signed out", "Sign in to manage topic rules."));
        }
        let mut first = true;
        for state in &self.states {
            let topic = state.topic.id;
            let mut kinds: BTreeMap<String, Policy> = state
                .tasks
                .iter()
                .filter_map(|t| t.action.as_ref())
                .map(|a| (a.kind.0.clone(), Policy::NeedsApproval))
                .collect();
            for rule in &state.topic.rules {
                let (k, p) = match &rule.effect {
                    RuleEffect::Allow(k) => (k, Policy::Approved),
                    RuleEffect::Ask(k) => (k, Policy::NeedsApproval),
                    RuleEffect::Deny(k) => (k, Policy::DoNotUse),
                    RuleEffect::Skip(_) => continue,
                };
                kinds.insert(k.0.clone(), p);
            }
            if kinds.is_empty() {
                continue;
            }
            page = page
                .child(section(state.topic.name.clone(), "", None, first))
                .child(group(kinds.into_iter().map(|(name, current)| {
                    let title = ActionKind(name.clone()).title();
                    item(
                        title,
                        "",
                        policy_picker(
                            &format!("{topic}-{name}"),
                            current,
                            None,
                            false,
                            cx,
                            move |s, policy, _, _| {
                                let kind = ActionKind(name.clone());
                                let rule = Rule {
                                    id: RuleId(Uuid::new_v4()),
                                    text: format!(
                                        "{} · {}",
                                        kind.description(),
                                        policy_name(policy)
                                    ),
                                    from_task: None,
                                    created_at: chrono::Utc::now(),
                                    effect: match policy {
                                        Policy::Approved => RuleEffect::Allow(kind),
                                        Policy::NeedsApproval => RuleEffect::Ask(kind),
                                        Policy::DoNotUse => RuleEffect::Deny(kind),
                                    },
                                };
                                s.issue(topic, Command::AddRule { rule });
                            },
                        ),
                    )
                    .into_any_element()
                })));
            first = false;
        }
        if first {
            page=page.child(empty("Ask first","Action permissions appear here when a topic proposes an action or has an existing rule."));
        }
        page
    }
    pub(super) fn advanced_page(&self, cx: &Context<Self>) -> Div {
        let mut page = ui::column()
            .gap_0()
            .child(header(
                "Advanced",
                "Connection and local storage for this device.",
                None,
            ))
            .child(section("Connection", "", None, true))
            .child(group([ui::row()
                .w_full()
                .min_h(px(60.))
                .px(px(meep_shell::settings::ROW_X))
                .py(px(10.))
                .child(
                    ui::column()
                        .flex_1()
                        .min_w_0()
                        .gap(px(2.))
                        .child(meep_shell::settings::copy(
                            "PostHog",
                            match self.client().status() {
                                Status::Online => "Connected",
                                Status::Syncing => "Syncing",
                                Status::Offline { .. } => "Offline",
                                Status::Unauthorized => "Sign in again",
                            },
                        ))
                        .child(ui::mono(self.backend.server.clone()).truncate()),
                )
                .into_any_element()]))
            .child(section("Local storage", "", None, false));
        if self.clear_confirm {
            let cancel = control("cancel-clear", "Cancel", false, cx, |s, _, _| {
                s.clear_confirm = false
            });
            let confirm = danger(
                control("clear-confirm", "Clear copies", true, cx, |s, w, cx| {
                    s.clear_confirm = false;
                    let client = s.client().clone();
                    s.job(
                        async move { client.clear_replica_cache().await },
                        w,
                        cx,
                        |s, result, _, _| {
                            if let Err(e) = result {
                                s.fail(e)
                            }
                            s.reload();
                        },
                    );
                }),
                cx,
            );
            page=page.child(group([item(
                "Clear offline copies?",
                "Synced topics and files will download again. Pending edits must finish syncing first.",
                ui::row().gap(px(6.)).child(cancel).child(confirm),
            ).into_any_element()]));
        } else {
            page = page.child(group([item(
                "Offline copies",
                "Local copies of synced topics, files and source lists.",
                control("clear-cache", "Clear copies…", false, cx, |s, _, _| {
                    s.clear_confirm = true
                }),
            )
            .into_any_element()]));
        }
        page
    }
}
