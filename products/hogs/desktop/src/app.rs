//! The window's one view: sign-in, the chat list, the open conversation, and its panels.

use std::time::Duration;

use anyhow::Result;
use gpui_kit::component::input::{Input, InputEvent, InputState, Textarea, TextareaState};
use gpui_kit::component::theme::Theme;
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;
use serde_json::json;

use crate::api::{Client, HOSTS, SignIn, SignedOut, Tokens};
use crate::models::{
    Hog, HogAction, HogMessage, HogReport, HogRule, HogSchedule, HogTrigger, McpInstallation, Me, day_label, list_label,
    same_day, time_label,
};
use crate::theme::{COLORS, EMOJI, Palette, hex};

const LIST_POLL: Duration = Duration::from_secs(2);
const CHAT_POLL: Duration = Duration::from_millis(1500);
// The keychain entry (Credential Manager on Windows) that holds the session.
const CREDENTIALS_URL: &str = "https://hogs.posthog.com";

#[derive(PartialEq)]
enum Phase {
    Loading,
    SignedOut,
    SignedIn,
}

struct NewHog {
    emoji: usize,
    color: usize,
    chosen: Vec<String>,
    busy: bool,
    error: Option<SharedString>,
}

pub struct HogsApp {
    client: Client,
    phase: Phase,
    host: usize,
    sign_in_busy: bool,
    sign_in_error: Option<SharedString>,
    me: Option<Me>,
    hogs: Vec<Hog>,
    selected: Option<String>,
    messages: Vec<HogMessage>,
    error: Option<SharedString>,
    info_open: bool,
    schedules: Vec<HogSchedule>,
    triggers: Vec<HogTrigger>,
    rules: Vec<HogRule>,
    open_report: Option<String>,
    installations: Option<Vec<McpInstallation>>,
    new_hog: Option<NewHog>,
    confirming_delete: bool,
    composer: Entity<TextareaState>,
    search: Entity<InputState>,
    name: Entity<InputState>,
    scroll: ScrollHandle,
    list_task: Option<Task<()>>,
    chat_task: Option<Task<()>>,
    _subscriptions: Vec<Subscription>,
}

impl HogsApp {
    pub fn new(window: &mut Window, cx: &mut Context<Self>) -> Self {
        let composer = cx.new(|cx| TextareaState::new(window, cx).placeholder("Type a message").auto_grow(1, 6));
        let search = cx.new(|cx| InputState::new(window, cx).placeholder("Search your hogs"));
        let name = cx.new(|cx| InputState::new(window, cx).placeholder("Name, for example Signups"));
        let subscriptions = vec![
            cx.subscribe_in(&composer, window, |this, _, event: &InputEvent, window, cx| {
                if let InputEvent::PressEnter { shift: false, .. } = event {
                    this.send_draft(window, cx);
                }
            }),
            cx.subscribe_in(&search, window, |_, _, event: &InputEvent, _, cx| {
                if matches!(event, InputEvent::Change) {
                    cx.notify();
                }
            }),
            cx.subscribe_in(&name, window, |_, _, event: &InputEvent, _, cx| {
                if matches!(event, InputEvent::Change) {
                    cx.notify();
                }
            }),
            cx.observe_window_appearance(window, |_, window, cx| {
                Theme::sync_system_appearance(Some(window), cx);
                cx.notify();
            }),
        ];
        // The inputs come from GPUI Kit, so its theme has to follow the system appearance too.
        Theme::sync_system_appearance(Some(window), cx);
        let mut this = Self {
            client: Client::default(),
            phase: Phase::Loading,
            host: 0,
            sign_in_busy: false,
            sign_in_error: None,
            me: None,
            hogs: Vec::new(),
            selected: None,
            messages: Vec::new(),
            error: None,
            info_open: false,
            schedules: Vec::new(),
            triggers: Vec::new(),
            rules: Vec::new(),
            open_report: None,
            installations: None,
            new_hog: None,
            confirming_delete: false,
            composer,
            search,
            name,
            scroll: ScrollHandle::new(),
            list_task: None,
            chat_task: None,
            _subscriptions: subscriptions,
        };
        this.restore_session(cx);
        this
    }

    fn team(&self) -> Option<i64> {
        self.me.as_ref()?.team.as_ref().map(|team| team.id)
    }

    fn selected_hog(&self) -> Option<&Hog> {
        let id = self.selected.as_ref()?;
        self.hogs.iter().find(|hog| &hog.id == id)
    }

    // Session

    fn restore_session(&mut self, cx: &mut Context<Self>) {
        // Development only: skip the browser sign-in with a personal API key from the environment.
        if let Ok(token) = std::env::var("HOGS_DEV_TOKEN") {
            let host = std::env::var("HOGS_DEV_HOST").unwrap_or_else(|_| HOSTS[0].url.to_string());
            self.client.set_tokens(Some(Tokens { host, access_token: token, refresh_token: None }));
            self.load_account(cx);
            return;
        }
        let stored = cx.read_credentials(CREDENTIALS_URL);
        cx.spawn(async move |this, cx| {
            let tokens = stored
                .await
                .ok()
                .flatten()
                .and_then(|(_, secret)| serde_json::from_slice::<Tokens>(&secret).ok());
            this.update(cx, |this, cx| match tokens {
                Some(tokens) => {
                    this.client.set_tokens(Some(tokens));
                    this.load_account(cx);
                }
                None => {
                    this.phase = Phase::SignedOut;
                    cx.notify();
                }
            })
            .ok();
        })
        .detach();
    }

    fn persist_session(&self, cx: &mut Context<Self>) {
        if std::env::var("HOGS_DEV_TOKEN").is_ok() {
            return;
        }
        match self.client.tokens().and_then(|tokens| serde_json::to_vec(&tokens).ok()) {
            Some(secret) => cx.write_credentials(CREDENTIALS_URL, "session", &secret).detach(),
            None => cx.delete_credentials(CREDENTIALS_URL).detach(),
        }
    }

    fn sign_in(&mut self, cx: &mut Context<Self>) {
        let attempt = match SignIn::begin(&HOSTS[self.host]) {
            Ok(attempt) => attempt,
            Err(error) => {
                self.sign_in_error = Some(error.to_string().into());
                cx.notify();
                return;
            }
        };
        cx.open_url(&attempt.authorize_url);
        self.sign_in_busy = true;
        self.sign_in_error = None;
        cx.notify();
        cx.spawn(async move |this, cx| {
            let result = cx.background_spawn(async move { attempt.finish() }).await;
            this.update(cx, |this, cx| {
                this.sign_in_busy = false;
                match result {
                    Ok(tokens) => {
                        this.client.set_tokens(Some(tokens));
                        this.persist_session(cx);
                        this.load_account(cx);
                        cx.activate(true);
                    }
                    Err(error) => this.sign_in_error = Some(error.to_string().into()),
                }
                cx.notify();
            })
            .ok();
        })
        .detach();
    }

    fn sign_out(&mut self, cx: &mut Context<Self>) {
        self.list_task = None;
        self.chat_task = None;
        self.client.set_tokens(None);
        self.persist_session(cx);
        self.phase = Phase::SignedOut;
        self.me = None;
        self.hogs.clear();
        self.messages.clear();
        self.selected = None;
        self.info_open = false;
        cx.notify();
    }

    /// Records a failed call. A finished session sends the person back to the sign-in screen.
    fn fail(&mut self, error: anyhow::Error, cx: &mut Context<Self>) {
        if error.downcast_ref::<SignedOut>().is_some() {
            self.sign_out(cx);
        } else {
            self.error = Some(error.to_string().into());
            cx.notify();
        }
    }

    fn load_account(&mut self, cx: &mut Context<Self>) {
        let client = self.client.clone();
        cx.spawn(async move |this, cx| {
            let me = cx.background_spawn(async move { client.me() }).await;
            this.update(cx, |this, cx| match me {
                Ok(me) => {
                    this.me = Some(me);
                    this.phase = Phase::SignedIn;
                    this.start_list_polling(cx);
                    cx.notify();
                }
                Err(error) => {
                    this.phase = Phase::SignedOut;
                    this.fail(error, cx);
                }
            })
            .ok();
        })
        .detach();
    }

    // Data

    fn start_list_polling(&mut self, cx: &mut Context<Self>) {
        let Some(team) = self.team() else { return };
        let client = self.client.clone();
        self.list_task = Some(cx.spawn(async move |this, cx| {
            let mut first = true;
            loop {
                let fetch = client.clone();
                let hogs = cx.background_spawn(async move { fetch.hogs(team) }).await;
                let alive = this.update(cx, |this, cx| {
                    match hogs {
                        Ok(hogs) => this.apply_hogs(hogs, first, cx),
                        Err(error) => this.fail(error, cx),
                    }
                    // A refresh may have rotated the tokens, so keep the stored copy current.
                    this.persist_session(cx);
                });
                if alive.is_err() {
                    return;
                }
                first = false;
                cx.background_executor().timer(LIST_POLL).await;
            }
        }));
    }

    fn apply_hogs(&mut self, hogs: Vec<Hog>, first: bool, cx: &mut Context<Self>) {
        if self.error.take().is_none() && hogs == self.hogs {
            return;
        }
        self.hogs = hogs;
        // The working indicator is a row in the chat, so keep it in view when it appears.
        if self.selected_hog().is_some_and(|hog| hog.working) {
            self.scroll.scroll_to_bottom();
        }
        if first {
            // Development only: open a named chat at launch, for scripted screenshots.
            if let Ok(name) = std::env::var("HOGS_DEV_SELECT") {
                if let Some(id) = self.hogs.iter().find(|hog| hog.name == name).map(|hog| hog.id.clone()) {
                    self.select(id, cx);
                    if std::env::var("HOGS_DEV_INFO").is_ok() {
                        self.toggle_info(cx);
                    }
                }
            }
            if std::env::var("HOGS_DEV_NEW").is_ok() {
                self.open_new_hog(cx);
            }
        }
        cx.notify();
    }

    /// Answers a card in the open chat, then reloads the chat so the card shows its new state.
    fn answer_card(&mut self, action: &'static str, body: serde_json::Value, cx: &mut Context<Self>) {
        let (Some(team), Some(hog)) = (self.team(), self.selected.clone()) else { return };
        let client = self.client.clone();
        cx.spawn(async move |this, cx| {
            let id = hog.clone();
            let result = cx
                .background_spawn(async move {
                    client.hog_post(team, &id, action, body)?;
                    client.messages(team, &id)
                })
                .await;
            this.update(cx, |this, cx| match result {
                Ok(messages) => {
                    if this.selected.as_ref() == Some(&hog) {
                        this.messages = messages;
                    }
                    this.refresh_hogs(cx);
                    cx.notify();
                }
                Err(error) => this.fail(error, cx),
            })
            .ok();
        })
        .detach();
    }

    fn toggle_report(&mut self, report: &HogReport, cx: &mut Context<Self>) {
        self.open_report = if self.open_report.as_ref() == Some(&report.id) { None } else { Some(report.id.clone()) };
        cx.notify();
    }

    fn refresh_hogs(&mut self, cx: &mut Context<Self>) {
        let Some(team) = self.team() else { return };
        let client = self.client.clone();
        cx.spawn(async move |this, cx| {
            let hogs = cx.background_spawn(async move { client.hogs(team) }).await;
            this.update(cx, |this, cx| match hogs {
                Ok(hogs) => this.apply_hogs(hogs, false, cx),
                Err(error) => this.fail(error, cx),
            })
            .ok();
        })
        .detach();
    }

    fn select(&mut self, hog_id: String, cx: &mut Context<Self>) {
        if self.selected.as_ref() == Some(&hog_id) {
            return;
        }
        let Some(team) = self.team() else { return };
        self.selected = Some(hog_id.clone());
        self.open_report = None;
        self.messages.clear();
        self.info_open = false;
        self.confirming_delete = false;
        let client = self.client.clone();
        self.chat_task = Some(cx.spawn(async move |this, cx| {
            loop {
                let (fetch, id) = (client.clone(), hog_id.clone());
                let messages = cx
                    .background_spawn(async move {
                        let messages = fetch.messages(team, &id)?;
                        // Opening the chat is what marks the hog's messages as read.
                        if messages.iter().any(|message| !message.from_owner() && message.read_at.is_none()) {
                            fetch.mark_read(team, &id)?;
                        }
                        Ok::<_, anyhow::Error>(messages)
                    })
                    .await;
                let alive = this.update(cx, |this, cx| match messages {
                    Ok(messages) => {
                        if messages != this.messages {
                            this.messages = messages;
                            this.scroll.scroll_to_bottom();
                            cx.notify();
                        }
                    }
                    Err(error) => this.fail(error, cx),
                });
                if alive.is_err() {
                    return;
                }
                cx.background_executor().timer(CHAT_POLL).await;
            }
        }));
        cx.notify();
    }

    fn send_draft(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let text = self.composer.read(cx).value().trim().to_string();
        let (Some(team), Some(hog)) = (self.team(), self.selected.clone()) else { return };
        self.composer.update(cx, |input, cx| input.set_value("", window, cx));
        if text.is_empty() {
            return;
        }
        let client = self.client.clone();
        cx.spawn(async move |this, cx| {
            let id = hog.clone();
            let sent = cx.background_spawn(async move { client.send_message(team, &id, &text) }).await;
            this.update(cx, |this, cx| match sent {
                Ok(message) => {
                    if this.selected.as_ref() == Some(&hog) {
                        this.messages.push(message);
                        this.scroll.scroll_to_bottom();
                    }
                    this.refresh_hogs(cx);
                    cx.notify();
                }
                Err(error) => this.fail(error, cx),
            })
            .ok();
        })
        .detach();
    }

    fn toggle_info(&mut self, cx: &mut Context<Self>) {
        self.info_open = !self.info_open;
        self.confirming_delete = false;
        if self.info_open {
            self.schedules.clear();
            self.triggers.clear();
            self.rules.clear();
            self.load_panel_data(cx);
        }
        cx.notify();
    }

    fn load_panel_data(&mut self, cx: &mut Context<Self>) {
        let Some(team) = self.team() else { return };
        let hog = self.selected.clone();
        let client = self.client.clone();
        cx.spawn(async move |this, cx| {
            let (details, installations) = cx
                .background_spawn(async move {
                    let details = hog.map(|id| {
                        (
                            client.schedules(team, &id).unwrap_or_default(),
                            client.triggers(team, &id).unwrap_or_default(),
                            client.rules(team, &id).unwrap_or_default(),
                        )
                    });
                    (details, client.mcp_installations(team).unwrap_or_default())
                })
                .await;
            this.update(cx, |this, cx| {
                if let Some((schedules, triggers, rules)) = details {
                    this.schedules = schedules;
                    this.triggers = triggers;
                    this.rules = rules;
                }
                this.installations = Some(installations);
                cx.notify();
            })
            .ok();
        })
        .detach();
    }

    /// Runs a write against the selected hog, then reloads the list.
    fn mutate(
        &mut self,
        cx: &mut Context<Self>,
        call: impl FnOnce(&Client, i64, &str) -> Result<()> + Send + 'static,
        then: impl FnOnce(&mut Self, &mut Context<Self>) + 'static,
    ) {
        let (Some(team), Some(hog)) = (self.team(), self.selected.clone()) else { return };
        let client = self.client.clone();
        cx.spawn(async move |this, cx| {
            let result = cx.background_spawn(async move { call(&client, team, &hog) }).await;
            this.update(cx, |this, cx| match result {
                Ok(()) => {
                    then(this, cx);
                    this.refresh_hogs(cx);
                }
                Err(error) => this.fail(error, cx),
            })
            .ok();
        })
        .detach();
    }

    fn open_new_hog(&mut self, cx: &mut Context<Self>) {
        self.new_hog = Some(NewHog { emoji: 0, color: 0, chosen: Vec::new(), busy: false, error: None });
        self.load_panel_data(cx);
        cx.notify();
    }

    fn create_hog(&mut self, cx: &mut Context<Self>) {
        let name = self.name.read(cx).value().trim().to_string();
        let (Some(team), Some(form)) = (self.team(), self.new_hog.as_mut()) else { return };
        if name.is_empty() || form.busy {
            return;
        }
        form.busy = true;
        let (emoji, color, chosen) = (EMOJI[form.emoji], COLORS[form.color], form.chosen.clone());
        let client = self.client.clone();
        cx.spawn(async move |this, cx| {
            let created = cx.background_spawn(async move { client.create_hog(team, &name, emoji, color, &chosen) }).await;
            this.update(cx, |this, cx| {
                match created {
                    Ok(hog) => {
                        this.new_hog = None;
                        this.hogs.insert(0, hog.clone());
                        this.select(hog.id, cx);
                        this.refresh_hogs(cx);
                    }
                    Err(error) => {
                        if let Some(form) = this.new_hog.as_mut() {
                            form.busy = false;
                            form.error = Some(error.to_string().into());
                        }
                    }
                }
                cx.notify();
            })
            .ok();
        })
        .detach();
    }

    // Views

    fn avatar(emoji: &str, color: &str, diameter: f32) -> Div {
        div()
            .flex_none()
            .size(px(diameter))
            .rounded_full()
            .bg(hex(color))
            .flex()
            .items_center()
            .justify_center()
            .text_size(px(diameter * 0.5))
            .child(emoji.to_string())
    }

    fn ticks(message: &HogMessage, p: &Palette) -> Div {
        let (glyph, color) = match (message.seen_at.is_some(), message.delivered_at.is_some()) {
            (true, _) => ("✓✓", p.tick_seen),
            (false, true) => ("✓✓", p.text_3),
            (false, false) => ("✓", p.text_3),
        };
        div().flex_none().text_size(px(11.)).text_color(color).child(glyph)
    }

    fn pill_button(id: impl Into<ElementId>, label: impl Into<SharedString>, p: &Palette) -> Stateful<Div> {
        div()
            .id(id)
            .h(px(36.))
            .px(px(18.))
            .rounded_full()
            .border_1()
            .border_color(p.divider)
            .flex()
            .items_center()
            .justify_center()
            .cursor_pointer()
            .hover(|style| style.bg(p.surface))
            .child(label.into())
    }

    fn primary_button(id: impl Into<ElementId>, label: impl Into<SharedString>, enabled: bool, p: &Palette) -> Stateful<Div> {
        div()
            .id(id)
            .h(px(38.))
            .px(px(22.))
            .rounded_full()
            .bg(p.accent)
            .text_color(rgb(0xFFFFFF))
            .font_weight(FontWeight::MEDIUM)
            .flex()
            .items_center()
            .justify_center()
            .when(enabled, |el| el.cursor_pointer().hover(|style| style.opacity(0.9)))
            .when(!enabled, |el| el.opacity(0.5))
            .child(label.into())
    }

    fn section(title: &'static str, p: &Palette) -> Div {
        div().flex().flex_col().gap(px(6.)).child(
            div().text_size(px(13.)).font_weight(FontWeight::MEDIUM).text_color(p.accent).child(title),
        )
    }

    fn render_sign_in(&self, p: &Palette, cx: &mut Context<Self>) -> Div {
        let busy = self.sign_in_busy;
        div().size_full().bg(p.surface).flex().items_center().justify_center().child(
            div()
                .w(px(360.))
                .p(px(32.))
                .rounded(px(12.))
                .bg(p.panel)
                .flex()
                .flex_col()
                .items_center()
                .gap(px(16.))
                .child(div().text_size(px(72.)).child("🦔"))
                .child(div().text_size(px(26.)).font_weight(FontWeight::SEMIBOLD).child("Hogs"))
                .child(
                    div()
                        .text_color(p.text_3)
                        .text_center()
                        .child("Agents that each look after one thing for you, and message you when it matters."),
                )
                .child(div().w_full().flex().flex_col().gap(px(6.)).children(HOSTS.iter().enumerate().map(
                    |(index, host)| {
                        let chosen = index == self.host;
                        div()
                            .id(("host", index))
                            .h(px(34.))
                            .px(px(12.))
                            .rounded(px(8.))
                            .border_1()
                            .border_color(if chosen { p.accent } else { p.divider })
                            .flex()
                            .items_center()
                            .cursor_pointer()
                            .child(host.label)
                            .on_click(cx.listener(move |this, _, _, cx| {
                                if !this.sign_in_busy {
                                    this.host = index;
                                    cx.notify();
                                }
                            }))
                    },
                )))
                .child(
                    Self::primary_button(
                        "sign-in",
                        if busy { "Waiting for your browser…" } else { "Sign in with PostHog" },
                        !busy,
                        p,
                    )
                    .w_full()
                    .on_click(cx.listener(|this, _, _, cx| {
                        if !this.sign_in_busy {
                            this.sign_in(cx);
                        }
                    })),
                )
                .when(busy, |el| {
                    el.child(
                        div()
                            .text_size(px(13.))
                            .text_color(p.text_3)
                            .child("Approve the request in the browser tab that opened."),
                    )
                })
                .when_some(self.sign_in_error.clone(), |el, error| {
                    el.child(div().text_size(px(13.)).text_color(p.danger).child(error))
                }),
        )
    }

    fn render_chat_list(&self, p: &Palette, cx: &mut Context<Self>) -> Div {
        let query = self.search.read(cx).value().trim().to_lowercase();
        let rows = self
            .hogs
            .iter()
            .filter(|hog| query.is_empty() || format!("{} {}", hog.name, hog.responsibility).to_lowercase().contains(&query))
            .map(|hog| {
                let id = hog.id.clone();
                let unread = hog.unread_count > 0;
                let waiting = hog.needs_you_count > 0;
                let preview = if hog.working {
                    div().text_color(p.accent).child("working…")
                } else if let Some(last) = &hog.last_message {
                    div()
                        .flex()
                        .gap(px(4.))
                        .items_center()
                        .text_color(p.text_3)
                        .when(last.from_owner(), |el| el.child(Self::ticks(last, p)))
                        .child(div().truncate().child(last.content.replace('\n', " ")))
                } else {
                    div().text_color(p.text_3).child("No messages yet")
                };
                div()
                    .id(SharedString::from(format!("hog-{}", hog.id)))
                    .h(px(72.))
                    .px(px(14.))
                    .flex()
                    .items_center()
                    .gap(px(12.))
                    .cursor_pointer()
                    .when(self.selected.as_ref() == Some(&hog.id), |el| el.bg(p.selected))
                    .hover(|style| style.bg(p.hover))
                    .on_click(cx.listener(move |this, _, _, cx| this.select(id.clone(), cx)))
                    .child(Self::avatar(&hog.emoji, &hog.color, 48.))
                    .child(
                        div()
                            .flex_1()
                            .min_w_0()
                            .h_full()
                            .flex()
                            .flex_col()
                            .justify_center()
                            .gap(px(3.))
                            .border_b_1()
                            .border_color(p.divider)
                            .child(
                                div()
                                    .flex()
                                    .items_center()
                                    .gap(px(8.))
                                    .child(
                                        div()
                                            .flex_1()
                                            .min_w_0()
                                            .truncate()
                                            .text_size(px(16.))
                                            .font_weight(FontWeight::MEDIUM)
                                            .child(hog.name.clone()),
                                    )
                                    .when_some(hog.last_message.as_ref(), |el, last| {
                                        el.child(
                                            div()
                                                .flex_none()
                                                .text_size(px(12.))
                                                .text_color(if unread || waiting { p.accent } else { p.text_3 })
                                                .child(list_label(&last.created_at)),
                                        )
                                    }),
                            )
                            .child(
                                div()
                                    .flex()
                                    .items_center()
                                    .gap(px(8.))
                                    .child(div().flex_1().min_w_0().overflow_hidden().child(preview))
                                    .when(hog.status == "paused", |el| {
                                        el.child(
                                            div()
                                                .flex_none()
                                                .px(px(8.))
                                                .rounded_full()
                                                .bg(p.surface)
                                                .text_size(px(11.))
                                                .text_color(p.text_3)
                                                .child("Paused"),
                                        )
                                    })
                                    .when(waiting, |el| {
                                        el.child(
                                            div()
                                                .flex_none()
                                                .h(px(20.))
                                                .px(px(8.))
                                                .rounded_full()
                                                .border_1()
                                                .border_color(p.accent)
                                                .text_color(p.accent)
                                                .text_size(px(11.))
                                                .font_weight(FontWeight::SEMIBOLD)
                                                .flex()
                                                .items_center()
                                                .child(if hog.needs_you_count == 1 {
                                                    "Needs you".to_string()
                                                } else {
                                                    format!("Needs you · {}", hog.needs_you_count)
                                                }),
                                        )
                                    })
                                    .when(unread, |el| el.child(Self::badge(hog.unread_count.to_string(), p))),
                            ),
                    )
            })
            .collect::<Vec<_>>();

        div()
            .w(px(360.))
            .flex_none()
            .h_full()
            .bg(p.panel)
            .border_r_1()
            .border_color(p.divider)
            .flex()
            .flex_col()
            .child(
                div()
                    // Leaves room for the window controls above the title.
                    .pt(px(44.))
                    .pb(px(10.))
                    .px(px(18.))
                    .flex()
                    .items_center()
                    .child(div().flex_1().text_size(px(22.)).font_weight(FontWeight::BOLD).child("Hogs"))
                    .child(
                        div()
                            .id("new-hog")
                            .size(px(32.))
                            .rounded_full()
                            .flex()
                            .items_center()
                            .justify_center()
                            .text_size(px(20.))
                            .text_color(p.text_3)
                            .cursor_pointer()
                            .hover(|style| style.bg(p.surface))
                            .child("+")
                            .on_click(cx.listener(|this, _, _, cx| this.open_new_hog(cx))),
                    ),
            )
            .child(div().px(px(12.)).pb(px(8.)).child(Input::new(&self.search).cleanable(true)))
            .when_some(self.error.clone(), |el, error| {
                el.child(div().px(px(18.)).py(px(6.)).text_size(px(13.)).text_color(p.danger).child(error))
            })
            .child(
                div()
                    .id("chat-list")
                    .flex_1()
                    .overflow_y_scroll()
                    .children(rows)
                    .when(self.hogs.is_empty() && self.error.is_none(), |el| {
                        el.child(
                            div()
                                .pt(px(48.))
                                .flex()
                                .flex_col()
                                .items_center()
                                .gap(px(16.))
                                .child(div().text_color(p.text_3).child("You have no hogs yet."))
                                .child(
                                    Self::primary_button("first-hog", "Set up your first hog", true, p)
                                        .on_click(cx.listener(|this, _, _, cx| this.open_new_hog(cx))),
                                ),
                        )
                    }),
            )
            .child(
                div()
                    .px(px(18.))
                    .py(px(10.))
                    .border_t_1()
                    .border_color(p.divider)
                    .flex()
                    .items_center()
                    .text_size(px(12.))
                    .text_color(p.text_3)
                    .child(
                        div().flex_1().min_w_0().truncate().child(
                            self.me.as_ref().map(|me| me.email.clone()).unwrap_or_default(),
                        ),
                    )
                    .child(
                        div()
                            .id("sign-out")
                            .cursor_pointer()
                            .hover(|style| style.text_color(p.text))
                            .child("Sign out")
                            .on_click(cx.listener(|this, _, _, cx| this.sign_out(cx))),
                    ),
            )
    }

    fn render_conversation(&self, hog: &Hog, p: &Palette, cx: &mut Context<Self>) -> Div {
        let subtitle = if hog.working {
            "working…".to_string()
        } else {
            match hog.status.as_str() {
                "setup" => "Being set up. Tell it what to look after.".to_string(),
                "paused" => "Paused".to_string(),
                _ => hog.responsibility.lines().next().unwrap_or_default().to_string(),
            }
        };
        let pill = |text: String| {
            div().w_full().flex().justify_center().py(px(8.)).child(
                div()
                    .max_w(px(460.))
                    .px(px(12.))
                    .py(px(5.))
                    .rounded(px(8.))
                    .bg(p.bubble_in)
                    .text_size(px(12.5))
                    .text_color(p.text_3)
                    .text_center()
                    .child(text),
            )
        };
        let mut rows: Vec<Div> = Vec::new();
        for (index, message) in self.messages.iter().enumerate() {
            let previous = index.checked_sub(1).map(|i| &self.messages[i]);
            let new_day = previous.is_none_or(|previous| !same_day(&previous.created_at, &message.created_at));
            if new_day {
                rows.push(pill(day_label(&message.created_at)));
            }
            if message.is_system() {
                rows.push(pill(message.content.clone()));
                continue;
            }
            let outgoing = message.from_owner();
            let first = new_day || previous.is_none_or(|previous| previous.author != message.author);
            // A report or an approval request is an ordinary message with its answers as pills underneath.
            let (body, pills) = match (&message.report, &message.action) {
                (Some(report), _) => (self.report_body(report, p, cx), Some(self.report_pills(report, p, cx))),
                (_, Some(action)) => (Self::approval_body(action, p), Some(self.approval_pills(action, p, cx))),
                _ => (div().child(message.content.clone()).into_any_element(), None),
            };
            let bubble = div()
                .max_w(relative(0.65))
                .px(px(10.))
                .py(px(7.))
                .rounded(px(7.5))
                .when(first && outgoing, |el| el.rounded_tr(px(0.)))
                .when(first && !outgoing, |el| el.rounded_tl(px(0.)))
                .bg(if outgoing { p.bubble_out } else { p.bubble_in })
                .shadow_sm()
                .flex()
                .flex_col()
                .child(div().text_size(px(14.2)).line_height(px(19.)).child(body))
                .child(
                    div()
                        .flex()
                        .justify_end()
                        .items_center()
                        .gap(px(3.))
                        .text_size(px(11.))
                        .text_color(p.text_3)
                        .child(time_label(&message.created_at))
                        .when(outgoing, |el| el.child(Self::ticks(message, p))),
                );
            rows.push(
                div()
                    .w_full()
                    .flex()
                    .flex_col()
                    .when(outgoing, |el| el.items_end())
                    .when(!outgoing, |el| el.items_start())
                    .pt(px(if first { 10. } else { 2. }))
                    .child(bubble)
                    .when_some(pills, |el, pills| el.child(pills.pt(px(6.)).pb(px(4.)))),
            );
        }
        if hog.working {
            rows.push(
                div().w_full().flex().pt(px(10.)).child(
                    div()
                        .px(px(14.))
                        .py(px(8.))
                        .rounded(px(7.5))
                        .rounded_tl(px(0.))
                        .bg(p.bubble_in)
                        .shadow_sm()
                        .text_color(p.text_3)
                        .child("• • •"),
                ),
            );
        }

        div()
            .flex_1()
            .min_w_0()
            .h_full()
            .flex()
            .flex_col()
            .child(
                div()
                    .id("conversation-header")
                    .h(px(60.))
                    .flex_none()
                    .px(px(16.))
                    .bg(p.surface)
                    .border_b_1()
                    .border_color(p.divider)
                    .flex()
                    .items_center()
                    .gap(px(14.))
                    .cursor_pointer()
                    .on_click(cx.listener(|this, _, _, cx| this.toggle_info(cx)))
                    .child(Self::avatar(&hog.emoji, &hog.color, 40.))
                    .child(
                        div()
                            .flex_1()
                            .min_w_0()
                            .child(div().text_size(px(16.)).font_weight(FontWeight::MEDIUM).child(hog.name.clone()))
                            .child(
                                div()
                                    .truncate()
                                    .text_size(px(13.))
                                    .text_color(if hog.working { p.accent } else { p.text_3 })
                                    .child(subtitle),
                            ),
                    )
                    .child(div().text_size(px(17.)).text_color(p.text_3).child("ⓘ")),
            )
            .child(
                div()
                    .id("messages")
                    .flex_1()
                    .bg(p.canvas)
                    .overflow_y_scroll()
                    .track_scroll(&self.scroll)
                    .px(px(48.))
                    .py(px(10.))
                    .children(rows),
            )
            .child(
                div()
                    .flex_none()
                    .px(px(16.))
                    .py(px(10.))
                    .bg(p.surface)
                    .flex()
                    .items_end()
                    .gap(px(10.))
                    .child(div().flex_1().min_w_0().child(Textarea::new(&self.composer)))
                    .child(
                        div()
                            .id("send")
                            .size(px(38.))
                            .flex_none()
                            .rounded_full()
                            .bg(p.accent)
                            .text_color(rgb(0xFFFFFF))
                            .text_size(px(17.))
                            .flex()
                            .items_center()
                            .justify_center()
                            .cursor_pointer()
                            .hover(|style| style.opacity(0.9))
                            .child("➤")
                            .on_click(cx.listener(|this, _, window, cx| this.send_draft(window, cx))),
                    ),
            )
    }

    fn render_mcp_picker(
        &self,
        chosen: &[String],
        p: &Palette,
        cx: &mut Context<Self>,
        toggle: impl Fn(&mut Self, String, &mut Context<Self>) + Clone + 'static,
    ) -> Div {
        let hint = |text: &'static str| div().text_size(px(13.)).text_color(p.text_3).child(text);
        let Some(installations) = &self.installations else {
            return hint("Loading your MCP servers…");
        };
        if installations.is_empty() {
            return hint(
                "No MCP servers are installed in this project. Add some in the MCP store in PostHog, then assign \
                 them here. Every hog can use PostHog's own tools.",
            );
        }
        div().flex().flex_col().gap(px(8.)).children(installations.iter().map(|installation| {
            let checked = chosen.contains(&installation.id);
            let (id, toggle) = (installation.id.clone(), toggle.clone());
            div()
                .id(SharedString::from(format!("mcp-{}", installation.id)))
                .flex()
                .items_center()
                .gap(px(10.))
                .cursor_pointer()
                .on_click(cx.listener(move |this, _, _, cx| toggle(this, id.clone(), cx)))
                .child(
                    div()
                        .size(px(16.))
                        .flex_none()
                        .rounded(px(4.))
                        .border_1()
                        .border_color(if checked { p.accent } else { p.text_3 })
                        .when(checked, |el| el.bg(p.accent))
                        .flex()
                        .items_center()
                        .justify_center()
                        .text_size(px(11.))
                        .text_color(rgb(0xFFFFFF))
                        .when(checked, |el| el.child("✓")),
                )
                .child(
                    div().min_w_0().child(installation.title()).when_some(
                        installation.description.clone().filter(|text| !text.is_empty()),
                        |el, text| el.child(div().truncate().text_size(px(12.)).text_color(p.text_3).child(text)),
                    ),
                )
        }))
    }

    fn render_info(&self, hog: &Hog, p: &Palette, cx: &mut Context<Self>) -> Div {
        let status = if hog.working {
            "Working now"
        } else {
            match hog.status.as_str() {
                "setup" => "Being set up",
                "paused" => "Paused",
                _ => "Active",
            }
        };
        let paused = hog.status == "paused";
        let body_text = |text: String| div().text_color(p.text_2).line_height(px(20.)).child(text);
        let schedules = if self.schedules.is_empty() {
            vec![div().text_size(px(13.)).text_color(p.text_3).child("This hog has not scheduled any wakes.")]
        } else {
            self.schedules
                .iter()
                .map(|schedule| {
                    let kind = match &schedule.cron_expression {
                        Some(cron) => format!("Repeats ({cron} UTC)"),
                        None => "Once".to_string(),
                    };
                    let title = match &schedule.next_fire_at {
                        Some(next) => format!("{kind}, next {} at {}", day_label(next), time_label(next)),
                        None => kind,
                    };
                    div()
                        .child(div().font_weight(FontWeight::MEDIUM).child(title))
                        .child(div().text_size(px(13.)).text_color(p.text_3).child(schedule.prompt.clone()))
                })
                .collect()
        };
        let host = self.client.tokens().map(|tokens| tokens.host).unwrap_or_default();
        let triggers = if self.triggers.is_empty() {
            vec![div().text_size(px(13.)).text_color(p.text_3).child(
                "No triggers. Ask this hog to create one to wake it when another system posts an event.",
            )]
        } else {
            self.triggers
                .iter()
                .map(|trigger| {
                    let fired = match trigger.fire_count {
                        0 => "Never fired".to_string(),
                        1 => "Fired once".to_string(),
                        count => format!("Fired {count} times"),
                    };
                    div()
                        .child(div().font_weight(FontWeight::MEDIUM).child(trigger.name.clone()))
                        .child(div().text_size(px(13.)).text_color(p.text_3).child(fired))
                        .child(
                            div()
                                .text_size(px(12.))
                                .text_color(p.text_3)
                                .child(format!("POST {host}{}", trigger.fire_path)),
                        )
                })
                .collect()
        };
        let rules = if self.rules.is_empty() {
            vec![div().text_size(px(13.)).text_color(p.text_3).child(
                "No rules. This hog asks before every action outside PostHog.",
            )]
        } else {
            self.rules
                .iter()
                .map(|rule| {
                    let effect = match rule.effect.as_str() {
                        "allow" => "Allowed without asking",
                        "deny" => "Always denied",
                        _ => "Asks every time",
                    };
                    let kind = rule.kind.clone();
                    div()
                        .flex()
                        .items_center()
                        .gap(px(8.))
                        .child(
                            div()
                                .flex_1()
                                .min_w_0()
                                .child(div().font_weight(FontWeight::MEDIUM).child(rule.kind.clone()))
                                .child(div().text_size(px(13.)).text_color(p.text_3).child(effect)),
                        )
                        .when(rule.effect != "ask", |el| {
                            el.child(
                                div()
                                    .id(SharedString::from(format!("rule-{}", rule.id)))
                                    .text_size(px(12.))
                                    .text_color(p.accent)
                                    .cursor_pointer()
                                    .child("Ask again")
                                    .on_click(cx.listener(move |this, _, _, cx| {
                                        let kind = kind.clone();
                                        this.mutate(
                                            cx,
                                            move |client, team, hog| {
                                                client.hog_post(team, hog, "rules/set", json!({ "kind": kind, "effect": "ask" }))
                                            },
                                            |this, cx| this.load_panel_data(cx),
                                        );
                                    })),
                            )
                        })
                })
                .collect()
        };
        let picker = self.render_mcp_picker(&hog.mcp_installation_ids, p, cx, |this, id, cx| {
            let Some(hog) = this.selected_hog() else { return };
            let mut ids = hog.mcp_installation_ids.clone();
            match ids.iter().position(|existing| existing == &id) {
                Some(index) => {
                    ids.remove(index);
                }
                None => ids.push(id),
            }
            this.mutate(
                cx,
                move |client, team, hog| client.update_hog(team, hog, json!({ "mcp_installation_ids": ids })),
                |_, _| {},
            );
        });

        div()
            .w(px(330.))
            .flex_none()
            .h_full()
            .bg(p.panel)
            .border_l_1()
            .border_color(p.divider)
            .flex()
            .flex_col()
            .child(
                div()
                    .h(px(60.))
                    .flex_none()
                    .px(px(16.))
                    .bg(p.surface)
                    .border_b_1()
                    .border_color(p.divider)
                    .flex()
                    .items_center()
                    .gap(px(12.))
                    .child(
                        div()
                            .id("close-info")
                            .text_color(p.text_3)
                            .cursor_pointer()
                            .child("✕")
                            .on_click(cx.listener(|this, _, _, cx| this.toggle_info(cx))),
                    )
                    .child(div().text_size(px(16.)).font_weight(FontWeight::MEDIUM).child("Hog details")),
            )
            .child(
                div().id("info-body").flex_1().overflow_y_scroll().child(
                div()
                    .p(px(20.))
                    .flex()
                    .flex_col()
                    .gap(px(20.))
                    .child(
                        div()
                            .flex()
                            .flex_col()
                            .items_center()
                            .gap(px(8.))
                            .child(Self::avatar(&hog.emoji, &hog.color, 96.))
                            .child(div().text_size(px(22.)).font_weight(FontWeight::MEDIUM).child(hog.name.clone()))
                            .child(div().text_size(px(13.)).text_color(p.text_3).child(status)),
                    )
                    .child(Self::section("Responsibility", p).child(body_text(if hog.responsibility.is_empty() {
                        "Not set yet. Tell this hog what to look after in the chat.".to_string()
                    } else {
                        hog.responsibility.clone()
                    })))
                    .child(Self::section("Schedules", p).children(schedules))
                    .child(Self::section("Triggers", p).children(triggers))
                    .child(Self::section("Approval rules", p).children(rules))
                    .child(Self::section("MCP servers", p).child(picker))
                    .child(Self::section("Memory", p).child(body_text(if hog.memory.is_empty() {
                        "Nothing saved yet.".to_string()
                    } else {
                        hog.memory.clone()
                    })))
                    .child(
                        div()
                            .flex()
                            .flex_col()
                            .gap(px(8.))
                            .when(hog.status != "setup", |el| {
                                el.child(
                                    Self::pill_button("pause", if paused { "Resume hog" } else { "Pause hog" }, p)
                                        .on_click(cx.listener(move |this, _, _, cx| {
                                            let status = if paused { "active" } else { "paused" };
                                            this.mutate(
                                                cx,
                                                move |client, team, hog| {
                                                    client.update_hog(team, hog, json!({ "status": status }))
                                                },
                                                |_, _| {},
                                            );
                                        })),
                                )
                            })
                            .child(if self.confirming_delete {
                                Self::pill_button("delete", "Delete it, with its chat and schedules", p)
                                    .text_color(p.danger)
                                    .border_color(p.danger)
                                    .on_click(cx.listener(|this, _, _, cx| {
                                        this.mutate(
                                            cx,
                                            |client, team, hog| client.delete_hog(team, hog),
                                            |this, cx| {
                                                this.chat_task = None;
                                                this.selected = None;
                                                this.info_open = false;
                                                this.messages.clear();
                                                cx.notify();
                                            },
                                        );
                                    }))
                            } else {
                                Self::pill_button("delete", "Delete hog", p).text_color(p.danger).on_click(
                                    cx.listener(|this, _, _, cx| {
                                        this.confirming_delete = true;
                                        cx.notify();
                                    }),
                                )
                            }),
                    ),
                ),
            )
    }

    fn render_new_hog(&self, form: &NewHog, p: &Palette, cx: &mut Context<Self>) -> Div {
        let can_create = !form.busy && !self.name.read(cx).value().trim().is_empty();
        let picker = self.render_mcp_picker(&form.chosen, p, cx, |this, id, cx| {
            if let Some(form) = this.new_hog.as_mut() {
                match form.chosen.iter().position(|existing| existing == &id) {
                    Some(index) => {
                        form.chosen.remove(index);
                    }
                    None => form.chosen.push(id),
                }
                cx.notify();
            }
        });
        div()
            .absolute()
            .inset_0()
            .occlude()
            .bg(p.scrim)
            .flex()
            .items_center()
            .justify_center()
            .child(
                div()
                    .w(px(460.))
                    .p(px(24.))
                    .rounded(px(12.))
                    .bg(p.panel)
                    .shadow_lg()
                    .flex()
                    .flex_col()
                    .gap(px(14.))
                    .child(div().text_size(px(20.)).font_weight(FontWeight::SEMIBOLD).child("New hog"))
                    .child(div().text_size(px(13.)).text_color(p.text_3).child(
                        "Give it a name and the tools it can use. You describe what it looks after in your first \
                         chat with it.",
                    ))
                    .child(
                        div()
                            .flex()
                            .items_center()
                            .gap(px(14.))
                            .child(Self::avatar(EMOJI[form.emoji], COLORS[form.color], 56.))
                            .child(div().flex_1().child(Input::new(&self.name))),
                    )
                    .child(div().flex().flex_wrap().gap(px(6.)).children(EMOJI.iter().enumerate().map(
                        |(index, emoji)| {
                            div()
                                .id(("emoji", index))
                                .size(px(32.))
                                .rounded_full()
                                .flex()
                                .items_center()
                                .justify_center()
                                .text_size(px(18.))
                                .cursor_pointer()
                                .when(index == form.emoji, |el| el.bg(p.selected))
                                .child(*emoji)
                                .on_click(cx.listener(move |this, _, _, cx| {
                                    if let Some(form) = this.new_hog.as_mut() {
                                        form.emoji = index;
                                        cx.notify();
                                    }
                                }))
                        },
                    )))
                    .child(div().flex().gap(px(8.)).children(COLORS.iter().enumerate().map(|(index, color)| {
                        div()
                            .id(("color", index))
                            .size(px(26.))
                            .rounded_full()
                            .bg(hex(color))
                            .border_2()
                            .border_color(if index == form.color { p.text } else { p.panel })
                            .cursor_pointer()
                            .on_click(cx.listener(move |this, _, _, cx| {
                                if let Some(form) = this.new_hog.as_mut() {
                                    form.color = index;
                                    cx.notify();
                                }
                            }))
                    })))
                    .child(Self::section("MCP servers", p).child(
                        div().id("new-hog-mcp").max_h(px(160.)).overflow_y_scroll().child(picker),
                    ))
                    .when_some(form.error.clone(), |el, error| {
                        el.child(div().text_size(px(13.)).text_color(p.danger).child(error))
                    })
                    .child(
                        div()
                            .flex()
                            .justify_end()
                            .gap(px(8.))
                            .child(Self::pill_button("cancel-new", "Cancel", p).on_click(cx.listener(
                                |this, _, _, cx| {
                                    this.new_hog = None;
                                    cx.notify();
                                },
                            )))
                            .child(
                                Self::primary_button("create-hog", "Create and start chat", can_create, p)
                                    .on_click(cx.listener(|this, _, _, cx| this.create_hog(cx))),
                            ),
                    ),
            )
    }

    fn badge(text: String, p: &Palette) -> Div {
        div()
            .flex_none()
            .min_w(px(20.))
            .h(px(20.))
            .px(px(6.))
            .rounded_full()
            .bg(p.badge)
            .text_color(p.badge_text)
            .text_size(px(12.))
            .font_weight(FontWeight::SEMIBOLD)
            .flex()
            .items_center()
            .justify_center()
            .child(text)
    }

    fn priority_chip(priority: &str, p: &Palette) -> Div {
        let color = match priority {
            "p0" | "p1" => p.danger,
            "p2" => rgb(0xDC9300),
            _ => p.text_3,
        };
        div()
            .flex_none()
            .w(px(30.))
            .h(px(20.))
            .rounded(px(5.))
            .border_1()
            .border_color(color)
            .text_color(color)
            .text_size(px(11.))
            .font_weight(FontWeight::SEMIBOLD)
            .flex()
            .items_center()
            .justify_center()
            .child(priority.to_uppercase())
    }

    fn small_button(id: SharedString, label: &'static str, primary: bool, p: &Palette) -> Stateful<Div> {
        div()
            .id(id)
            .h(px(30.))
            .px(px(14.))
            .rounded_full()
            .text_size(px(13.))
            .flex()
            .items_center()
            .cursor_pointer()
            .when(primary, |el| {
                el.bg(p.accent).text_color(rgb(0xFFFFFF)).font_weight(FontWeight::MEDIUM).hover(|style| style.opacity(0.9))
            })
            .when(!primary, |el| el.bg(p.bubble_in).border_1().border_color(p.divider).hover(|style| style.bg(p.surface)))
            .child(label)
    }

    /// The line under a message once its pills have been answered.
    fn answered(text: String, p: &Palette) -> Div {
        div().flex().items_center().gap(px(8.)).text_size(px(12.)).text_color(p.text_3).child(text)
    }

    fn approval_body(action: &HogAction, p: &Palette) -> AnyElement {
        div()
            .flex()
            .flex_col()
            .gap(px(6.))
            .child(action.label.clone())
            .when(!action.draft.is_empty(), |el| {
                el.child(div().pl(px(8.)).border_l_2().border_color(p.text_3).text_color(p.text_2).child(action.draft.clone()))
            })
            .into_any_element()
    }

    fn approval_pills(&self, action: &HogAction, p: &Palette, cx: &mut Context<Self>) -> Div {
        if action.status != "pending" {
            return Self::answered(
                match action.status.as_str() {
                    "approved" => "Approved".to_string(),
                    "denied" => "Denied".to_string(),
                    _ if action.result.is_empty() => "Done".to_string(),
                    _ => format!("Done. {}", action.result),
                },
                p,
            );
        }
        let decide = |label: &'static str, key: &'static str, decision: &'static str, always: bool, primary: bool| {
            let id = action.id.clone();
            Self::small_button(format!("{key}-{}", action.id).into(), label, primary, p).on_click(cx.listener(
                move |this, _, _, cx| {
                    let body = json!({ "action_id": id, "decision": decision, "always": always });
                    this.answer_card("actions/decide", body, cx);
                },
            ))
        };
        div()
            .flex()
            .flex_wrap()
            .gap(px(6.))
            .child(decide("Approve", "approve", "approve", false, true))
            .child(decide("Always allow", "allow", "approve", true, false))
            .child(decide("Deny", "deny", "deny", false, false))
            .child(decide("Always deny", "never", "deny", true, false))
    }

    fn report_body(&self, report: &HogReport, p: &Palette, cx: &mut Context<Self>) -> AnyElement {
        let open = self.open_report.as_ref() == Some(&report.id);
        let toggled = report.clone();
        let part = |title: &'static str, text: String| {
            div()
                .flex()
                .flex_col()
                .child(div().text_size(px(12.)).font_weight(FontWeight::MEDIUM).text_color(p.text_3).child(title))
                .child(text)
        };
        let lead = if report.impact.is_empty() {
            report.summary.lines().next().unwrap_or_default().to_string()
        } else {
            report.impact.clone()
        };
        div()
            .id(SharedString::from(format!("report-{}", report.id)))
            .flex()
            .flex_col()
            .gap(px(6.))
            .cursor_pointer()
            .on_click(cx.listener(move |this, _, _, cx| this.toggle_report(&toggled, cx)))
            .child(
                div()
                    .flex()
                    .items_start()
                    .gap(px(8.))
                    .child(Self::priority_chip(&report.priority, p))
                    .child(div().flex_1().min_w_0().font_weight(FontWeight::MEDIUM).child(report.title.clone())),
            )
            .when(!open, |el| {
                el.child(lead.clone()).child(div().text_size(px(12.)).text_color(p.accent).child("Show details"))
            })
            .when(open, |el| {
                el.when(!report.impact.is_empty(), |el| el.child(part("Impact", report.impact.clone())))
                    .child(part("Summary", report.summary.clone()))
                    .when(!report.proposal.is_empty(), |el| el.child(part("Proposal", report.proposal.clone())))
                    .when(!report.evidence.is_empty(), |el| {
                        el.child(
                            div()
                                .flex()
                                .flex_col()
                                .child(
                                    div()
                                        .text_size(px(12.))
                                        .font_weight(FontWeight::MEDIUM)
                                        .text_color(p.text_3)
                                        .child("Evidence"),
                                )
                                .children(report.evidence.iter().map(|item| {
                                    div()
                                        .child(format!("{}: {}", item.kind, item.description))
                                        .child(div().text_size(px(12.)).text_color(p.text_3).child(item.source.clone()))
                                })),
                        )
                    })
                    .child(div().text_size(px(12.)).text_color(p.accent).child("Hide details"))
            })
            .into_any_element()
    }

    fn report_pills(&self, report: &HogReport, p: &Palette, cx: &mut Context<Self>) -> Div {
        let post = |label: &'static str, key: &'static str, action: &'static str, body: serde_json::Value, primary: bool| {
            Self::small_button(format!("{key}-{}", report.id).into(), label, primary, p).on_click(cx.listener(
                move |this, _, _, cx| this.answer_card(action, body.clone(), cx),
            ))
        };
        let resolve = || {
            post("Resolve", "resolve", "reports/verdict", json!({ "report_id": report.id, "status": "resolved" }), false)
        };
        if !report.waiting() {
            let state = match (report.status.as_str(), report.follow_up.as_deref()) {
                ("resolved", _) => "Resolved",
                ("dismissed", _) => "Dismissed",
                (_, Some("implement")) => "Implementing",
                _ => "Investigating",
            };
            return Self::answered(state.to_string(), p).when(report.status == "open", |el| el.child(resolve()));
        }
        div()
            .flex()
            .flex_wrap()
            .gap(px(6.))
            .child(post(
                "Implement",
                "implement",
                "reports/follow_up",
                json!({ "report_id": report.id, "mode": "implement" }),
                true,
            ))
            .child(post(
                "Investigate",
                "investigate",
                "reports/follow_up",
                json!({ "report_id": report.id, "mode": "investigate" }),
                false,
            ))
            .child(resolve())
            .child(post(
                "Dismiss",
                "dismiss",
                "reports/verdict",
                json!({ "report_id": report.id, "status": "dismissed" }),
                false,
            ))
    }

    fn render_empty(&self, p: &Palette) -> Div {
        div()
            .flex_1()
            .h_full()
            .bg(p.surface)
            .flex()
            .flex_col()
            .items_center()
            .justify_center()
            .gap(px(12.))
            .child(div().text_size(px(72.)).child("🦔"))
            .child(div().text_size(px(30.)).font_weight(FontWeight::LIGHT).child("Hogs"))
            .child(div().max_w(px(420.)).text_center().text_color(p.text_3).child(
                "Each hog looks after one area for you. It works in the background and messages you only when \
                 something needs your attention.",
            ))
            .when_some(self.me.as_ref().and_then(|me| me.team.as_ref()), |el, team| {
                el.child(
                    div()
                        .pt(px(20.))
                        .text_size(px(13.))
                        .text_color(p.text_3)
                        .child(format!("Signed in to {}", team.name)),
                )
            })
    }
}

impl Render for HogsApp {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let p = Palette::for_appearance(window.appearance());
        let root = div().size_full().relative().bg(p.surface).text_color(p.text).text_size(px(14.));
        match self.phase {
            Phase::Loading => root,
            Phase::SignedOut => root.child(self.render_sign_in(&p, cx)),
            Phase::SignedIn => {
                let hog = self.selected_hog().cloned();
                root.child(
                    div()
                        .size_full()
                        .flex()
                        .child(self.render_chat_list(&p, cx))
                        .when_some(hog.as_ref(), |el, hog| {
                            el.child(self.render_conversation(hog, &p, cx))
                                .when(self.info_open, |el| el.child(self.render_info(hog, &p, cx)))
                        })
                        .when(hog.is_none(), |el| el.child(self.render_empty(&p))),
                )
                .when_some(self.new_hog.as_ref(), |el, form| el.child(self.render_new_hog(form, &p, cx)))
            }
        }
    }
}
