//! A native session pane. Hosts supply session state, actions and optional controls.
use super::*;
use crate::{
    controls::Unavailable,
    transcript::{TranscriptHost, starter},
};
use gpui_kit::component::{button::ButtonVariants, input::TextareaState, *};
use meep_protocol::sessions::{AgentSession, ElementReference};
use std::{
    cell::RefCell,
    collections::{HashMap, HashSet},
    rc::Rc,
};

/// Action chosen on a queued prompt.
#[derive(Clone, Copy)]
pub enum QueueAction {
    /// Send the prompt now.
    Send,
    /// Return the prompt to the editor.
    Edit,
    /// Discard the queued prompt.
    Remove,
}

/// A pending prompt with actions supplied by its host.
pub fn queued_row(
    index: usize,
    shown: String,
    running: bool,
    action: impl Fn(QueueAction, &mut Window, &mut App) + 'static,
) -> impl IntoElement {
    let group: SharedString = format!("queued-{index}").into();
    let action = Rc::new(action);
    let send = action.clone();
    let mut surface = row()
        .id(group.clone())
        .group(group.clone())
        .h(px(28.))
        .pl(px(6.))
        .gap(px(4.))
        .rounded(px(ui::CONTROL_RADIUS))
        .bg(rgb(ui::theme::color(ui::INSET)))
        .child(icon(Glyph::CornerDownRight).size(px(12.)))
        .child(
            div()
                .flex_1()
                .min_w_0()
                .truncate()
                .text_size(px(ui::CAPTION))
                .child(shown),
        )
        .child(
            ui::button(
                SharedString::from(format!("steer-queued-{index}")),
                if running { "Steer" } else { "Send" },
            )
            .ghost()
            .h(px(22.))
            .text_size(px(ui::SMALL))
            .tooltip(if running {
                "Steer with this message"
            } else {
                "Send now"
            })
            .on_click(move |_, window, cx| send(QueueAction::Send, window, cx)),
        );
    for (key, glyph, label, kind) in [
        (
            "edit",
            Glyph::Pencil,
            "Edit queued message",
            QueueAction::Edit,
        ),
        (
            "remove",
            Glyph::X,
            "Remove queued message",
            QueueAction::Remove,
        ),
    ] {
        let action = action.clone();
        surface = surface.child(
            ui::contextual_icon_button(
                SharedString::from(format!("{key}-queued-{index}")),
                glyph,
                label,
                group.clone(),
                false,
            )
            .size(px(22.))
            .on_click(move |_, window, cx| action(kind, window, cx)),
        );
    }
    surface
}

/// Shared View session toolbar with a history selector, draggable titlebar and actions.
pub fn session_header<T: 'static>(
    title: String,
    chevron_turn: f32,
    toggle: fn(&mut T, &mut Window, &mut Context<T>),
    new_session: fn(&mut T, &mut Window, &mut Context<T>),
    close: fn(&mut T, &mut Window, &mut Context<T>),
    cx: &Context<T>,
) -> Div {
    row()
        .h(px(meep_ui::design::current().toolbar))
        // The session title's ink lands on the text edge of a transcript
        // inset 12pt inside its scroll (12 + 16pt panel inset); the title
        // button adds 4pt padding plus glyph bearing. Panes whose
        // transcript sits flush override this with `.pl(px(9.))`.
        .pl(px(21.))
        .pr(px(12.))
        .gap(px(8.0))
        .flex_shrink_0()
        .border_b_1()
        .border_color(rgb(ui::theme::color(LINE)))
        .child(
            ui::button("all-view-sessions", "")
                .max_w(relative(0.7))
                .min_w_0()
                .px(px(4.))
                .tooltip(title.clone())
                .child(
                    row()
                        .w_full()
                        .gap(px(8.))
                        .child(
                            text(title)
                                .flex_1()
                                .min_w_0()
                                .truncate()
                                .font_weight(FontWeight::SEMIBOLD),
                        )
                        .child(
                            icon(Glyph::ChevronDown)
                                .size(px(12.))
                                .rotate(gpui_kit::radians(std::f32::consts::PI * chevron_turn)),
                        ),
                )
                .accessibility_label("Show sessions for this view")
                .on_click(cx.listener(move |this, _, window, cx| {
                    toggle(this, window, cx);
                    cx.notify();
                })),
        )
        .child(
            crate::titlebar_drag("session-window-titlebar")
                .flex_1()
                .h_full(),
        )
        .child(
            row()
                .gap(px(2.))
                .p(px(0.))
                .child(
                    Button::new("new-agent-session")
                        .small()
                        .h(px(ui::CONTROL))
                        .text_size(px(ui::BODY))
                        .rounded(px(ui::CONTROL_RADIUS))
                        .ghost()
                        .size(px(ui::HIT_TARGET))
                        .rounded(px(ui::ICON_RADIUS))
                        .icon(Glyph::Plus)
                        .accessibility_label("New session for this view")
                        .tooltip("New session")
                        .on_click(
                            cx.listener(move |this, _, window, cx| new_session(this, window, cx)),
                        ),
                )
                .child(
                    Button::new("close-agent-panel")
                        .small()
                        .h(px(ui::CONTROL))
                        .text_size(px(ui::BODY))
                        .rounded(px(ui::CONTROL_RADIUS))
                        .ghost()
                        .size(px(ui::HIT_TARGET))
                        .rounded(px(ui::ICON_RADIUS))
                        .icon(Glyph::X)
                        .accessibility_label("Close agent sessions")
                        .on_click(cx.listener(move |this, _, window, cx| close(this, window, cx))),
                ),
        )
}

/// Borrow the current host state for one render.
pub struct PanelModel<'a> {
    /// View whose sessions are listed.
    pub view_id: &'a str,
    /// Saved panel width in logical pixels.
    pub preferred_width: Option<f32>,
    /// Whether the agent pane is visible.
    pub agent_sidebar: bool,
    /// Open animation progress.
    pub agent_progress: f32,
    /// Opacity of the veil over the outgoing view.
    pub views_out: f32,
    /// Whether the pane is showing session history.
    pub session_list: bool,
    /// Sessions available to the host.
    pub sessions: &'a [AgentSession],
    /// Sessions animating out of the list.
    pub leaving_sessions: &'a HashSet<String>,
    /// Measured row heights used during list transitions.
    pub session_row_heights: &'a Rc<RefCell<HashMap<String, f32>>>,
    /// Scroll position of the conversation.
    pub session_scroll: &'a ScrollHandle,
    /// Host error displayed above the composer.
    pub session_error: &'a Option<String>,
    /// Editor for the current draft.
    pub session_input: &'a Entity<TextareaState>,
    /// View selections grouped by draft key.
    pub reference_drafts: &'a HashMap<String, Vec<ElementReference>>,
    /// Queued prompts grouped by session key.
    pub session_queue: &'a HashMap<String, Vec<composer::DraftMessage>>,
    /// Sessions waiting for configuration changes.
    pub session_configuring: &'a HashSet<String>,
}
/// Attachment state and controls for the current composer.
pub struct AttachmentControls {
    /// Whether attachment work currently prevents sending.
    pub busy: bool,
    /// Whether the draft includes an attachment.
    pub has_files: bool,
    /// Rendered list of attachments, when present.
    pub chips: Option<AnyElement>,
    /// Control for adding an attachment, when available.
    pub button: Option<Button>,
}
/// Presentation state retained between renders of a View session pane.
#[derive(Default)]
pub struct PanelFrame {
    /// Session whose transcript last received scroll updates.
    pub session_scroll_key: Option<String>,
    /// Clear the editor when the conversation is next shown.
    pub session_input_reset: bool,
    session_list_shown: bool,
    session_list_arrival: Option<u64>,
    arrival_count: u64,
}
impl PanelFrame {
    fn follow_transcript(&mut self, show_transcript: bool, scroll: &ScrollHandle, key: String) {
        if !show_transcript {
            self.session_scroll_key = None;
        } else {
            // Compare against the previous layout before GPUI measures this frame.
            // Its deferred scroll then uses the new content/viewport height. This
            // covers full snapshots, streaming blocks, disclosure and resizing.
            if self.session_scroll_key.as_ref() != Some(&key) {
                // Clear the stale "Latest" affordance in this render too.
                scroll.set_offset(-scroll.max_offset());
                scroll.scroll_to_bottom();
            } else if at_bottom(scroll) {
                scroll.scroll_to_bottom();
            }
            self.session_scroll_key = Some(key);
        }
    }
    fn begin(&mut self, list: bool, progress: f32, window: &mut Window, cx: &mut App) -> f32 {
        // Switching between the transcript and the session list brings the
        // new page up out of the paper; the list also drops a little from the
        // title that opened it. Only once the pane is in: a pane sliding open
        // is motion enough.
        if list != self.session_list_shown {
            self.session_list_shown = list;
            self.session_list_arrival = if progress >= 1. {
                self.arrival_count += 1;
                Some(self.arrival_count)
            } else {
                None
            };
        }
        match self.session_list_arrival {
            Some(n) => {
                let arrival = ui::motion::arrival(
                    ElementId::NamedChild(
                        ElementId::from("session-list-arrival").into(),
                        n.to_string().into(),
                    ),
                    false,
                    window,
                    cx,
                );
                if arrival.status == gpui_kit::base::MotionStatus::Finished {
                    self.session_list_arrival = None;
                }
                arrival.progress
            }
            None => 1.,
        }
    }
}
fn at_bottom(scroll: &ScrollHandle) -> bool {
    scroll.offset().y <= -scroll.max_offset().y + px(1.)
}

/// A View session pane with annotation, permissions, history and preview controls.
/// Topic chats can use [`crate::chat::ChatHost`] directly.
pub trait PanelHost: TranscriptHost {
    /// Retained presentation state for this pane.
    fn panel_frame(&mut self) -> &mut PanelFrame;
    /// Borrow host data needed for the current frame.
    fn panel_model(&self) -> PanelModel<'_>;
    /// Key for the selected session or its unsaved draft.
    fn session_key(&self) -> String;
    /// Selected session, if one has been created.
    fn current_session(&self) -> Option<&AgentSession>;
    /// Width occupied by the host sidebar.
    fn sidebar_width(&self, window: &Window) -> f32;
    /// Suggested follow-ups supplied by a View preview.
    fn preview_session_starters(&self) -> Vec<(SharedString, SharedString)> {
        Vec::new()
    }
    /// Send the indexed queued prompt immediately.
    fn send_queued_at(&mut self, key: &str, index: usize, running: bool, cx: &mut Context<Self>);
    /// Select an existing conversation for a view.
    fn select_session(
        &mut self,
        view_id: String,
        id: String,
        window: &mut Window,
        cx: &mut Context<Self>,
    );
    /// Remove a conversation from history.
    fn remove_session(&mut self, id: String, cx: &mut Context<Self>);
    /// Open a new conversation.
    fn new_session(&mut self, window: &mut Window, cx: &mut Context<Self>);
    /// Show or hide the agent pane.
    fn toggle_agent(&mut self, window: &mut Window, cx: &mut Context<Self>);
    /// Stop the active turn in a session.
    fn cancel_session(&mut self, id: String, cx: &mut Context<Self>);
    /// Send the draft, optionally steering the active turn.
    fn send_session_as(&mut self, steer: bool, cx: &mut Context<Self>);
    /// Submit the draft using the current send mode.
    fn send_session(&mut self, cx: &mut Context<Self>);
    /// Render the selections attached to the draft.
    fn render_references(&self, cx: &mut Context<Self>) -> AnyElement;
    /// Render host-specific session options.
    fn render_options(&self, cx: &mut Context<Self>) -> AnyElement;
    /// Render the resize handle for the pane.
    fn render_resize(&self, cx: &mut Context<Self>) -> AnyElement;
    /// Open the permissions for the current view.
    fn open_view_access(&mut self, window: &mut Window, cx: &mut Context<Self>);
    /// Switch between the conversation and session history.
    fn toggle_session_list(&mut self);
    /// Restore an indexed queued message to the editor.
    fn edit_queued(&mut self, key: &str, index: usize, window: &mut Window, cx: &mut Context<Self>);
    /// Discard an indexed queued message.
    fn remove_queued(&mut self, key: &str, index: usize);
    /// Build the attachment controls for a session.
    fn attachment_controls(&self, key: &str, cx: &mut Context<Self>) -> AttachmentControls;
    /// Messages waiting for the turn to end. Each can go now (steer) or be
    /// taken back into the composer.
    fn queued_messages(
        &self,
        queue: &[composer::DraftMessage],
        running: bool,
        cx: &mut Context<Self>,
    ) -> Div {
        let session = self.session_key();
        let muted = rgb(ui::theme::color(ui::TERTIARY));
        let mut list = col().gap(px(2.)).px(px(4.)).pt(px(4.)).child(
            text(if running {
                "Queued · sends when the agent finishes"
            } else {
                "Queued"
            })
            .px(px(6.))
            .text_size(px(ui::SMALL))
            .text_color(muted),
        );
        for (index, message) in queue.iter().enumerate() {
            let shown = if message.prompt.trim().is_empty() {
                message
                    .references
                    .first()
                    .map(|r| r.comment.clone())
                    .or_else(|| message.attachments.first().map(|f| f.name.clone()))
                    .unwrap_or_default()
            } else {
                message.prompt.replace('\n', " ")
            };
            let entity = cx.entity().downgrade();
            let key = session.clone();
            list = list.child(queued_row(
                index,
                shown,
                running,
                move |action, window, cx| {
                    let _ = entity.update(cx, |this, cx| {
                        match action {
                            QueueAction::Send => this.send_queued_at(&key, index, running, cx),
                            QueueAction::Edit => this.edit_queued(&key, index, window, cx),
                            QueueAction::Remove => this.remove_queued(&key, index),
                        }
                        cx.notify();
                    });
                },
            ));
        }
        list
    }
    /// Panel width after reserving room for the sidebar.
    fn agent_panel_width(&self, window: &Window) -> f32 {
        self.agent_panel_width_for(window, self.sidebar_width(window))
    }
    /// The panel width beside a sidebar of `sidebar` points (0 when hidden).
    fn agent_panel_width_for(&self, window: &Window, sidebar: f32) -> f32 {
        crate::agent_panel_width(
            f32::from(window.viewport_size().width),
            sidebar,
            self.panel_model().preferred_width,
        )
    }
    /// Whether the reader is following the latest message.
    fn chat_at_bottom(&self) -> bool {
        // Only tolerate layout rounding, not an intentional scroll into history.
        at_bottom(self.panel_model().session_scroll)
    }
    /// Render the conversation or session list and its controls.
    fn agent_panel(&mut self, window: &mut Window, cx: &mut Context<Self>) -> Div {
        let model = self.panel_model();
        let (list, visible, progress, scroll) = (
            model.session_list,
            model.agent_sidebar,
            model.agent_progress,
            model.session_scroll.clone(),
        );
        let key = self.session_key();
        let frame = self.panel_frame();
        frame.follow_transcript(!list && visible, &scroll, key);
        let page_in = frame.begin(list, progress, window, cx);
        let reset_input = !list && std::mem::take(&mut self.panel_frame().session_input_reset);
        let model = self.panel_model();
        // The chevron turns over while the list is open: the same button closes
        // it. The same spring as the sidebar sections' chevrons.
        let chevron_turn =
            ui::motion::reveal("session-list-chevron", model.session_list, window, cx);
        let view_id = model.view_id;
        let title = if model.session_list {
            "Sessions"
        } else {
            self.current_session()
                .map(|s| s.title.as_str())
                .filter(|s| !s.is_empty())
                .unwrap_or("New session")
        }
        .to_owned();
        let mut panel = super::pane(col())
            .shadow(super::pane_shadow_at(model.agent_progress))
            .flex_1()
            .min_h_0()
            .relative()
            .when(model.views_out > 0., |pane| {
                pane.child(super::veil(model.views_out))
            })
            .child(
                session_header(
                    title,
                    chevron_turn,
                    |s, _, _| s.toggle_session_list(),
                    Self::new_session,
                    Self::toggle_agent,
                    cx,
                )
                // This pane's transcript is flush with the pane, at 16pt.
                .pl(px(9.)),
            );
        if model.session_list {
            let mut list = col().bg(rgb(ui::theme::color(PAPER))).p(px(8.)).gap(px(2.));
            let mut count = 0;
            for session in model.sessions.iter().rev().filter(|s| s.view_id == view_id) {
                count += 1;
                let id = session.id.clone();
                let view_id = view_id.to_owned();
                let selected = self.current_session().is_some_and(|s| s.id == session.id);
                let group: SharedString = format!("session-row-{id}").into();
                let message_count = session.messages.iter().filter(|m| m.role == "user").count();
                let last = session
                    .messages
                    .iter()
                    .map(|m| m.created_at)
                    .max()
                    .unwrap_or(0);
                let tone = match session.status.as_str() {
                    "running" => ui::theme::get(10),
                    "idle" => ui::theme::get(9),
                    "cancelled" | "interrupted" => ui::theme::get(2),
                    _ => ui::theme::get(8),
                };
                let leaving = model.leaving_sessions.contains(&session.id);
                let fold = ui::motion::reveal(
                    ElementId::NamedChild(
                        ElementId::from("session-row-fold").into(),
                        session.id.clone().into(),
                    ),
                    !leaving,
                    window,
                    cx,
                );
                let measured = model.session_row_heights.borrow().get(&session.id).copied();
                let heights = model.session_row_heights.clone();
                let measure_id = session.id.clone();
                list = list.child(
                    row()
                        .relative()
                        .when_some(measured.filter(|_| leaving), |el, height| {
                            // Pinned to the top, so it folds from the bottom.
                            el.h(px(height * fold.max(0.)))
                                .overflow_hidden()
                                .items_start()
                        })
                        .when(!leaving, |el| {
                            el.child(
                                canvas(
                                    move |bounds, _, _| {
                                        heights
                                            .borrow_mut()
                                            .insert(measure_id, f32::from(bounds.size.height));
                                    },
                                    |_, _, _, _| {},
                                )
                                .absolute()
                                .inset_0(),
                            )
                        })
                        .group(group.clone())
                        .rounded(px(10.))
                        .pr(px(6.))
                        .when(selected, |el| el.bg(ui::ink(0x0a)))
                        .when(!selected, |el| el.hover(|s| s.bg(ui::ink(0x05))))
                        .gap(px(4.0))
                        .child(
                            Button::new(SharedString::from(format!("session-{id}")))
                                .accessibility_label(session.title.clone())
                                .tooltip(session.title.clone())
                                .ghost()
                                .flex_1()
                                .min_w_0()
                                .h_auto()
                                .py(px(10.))
                                .px(px(10.))
                                .rounded(px(10.))
                                .justify_start()
                                .custom(
                                    gpui_kit::component::button::ButtonCustomVariant::new(cx)
                                        .color(gpui_kit::rgba(0x00000000).into())
                                        .hover(gpui_kit::rgba(0x00000000).into())
                                        .active(ui::ink(0x08).into()),
                                )
                                .child(
                                    row()
                                        .w_full()
                                        .min_w_0()
                                        .gap(px(10.))
                                        .items_start()
                                        .child(
                                            div()
                                                .mt(px(6.))
                                                .size(px(7.))
                                                .flex_none()
                                                .rounded_full()
                                                .bg(rgb(tone)),
                                        )
                                        .child(
                                            col()
                                                .flex_1()
                                                .min_w_0()
                                                .gap(px(3.))
                                                .items_start()
                                                .child(
                                                    text(session.title.clone())
                                                        .text_size(px(ui::BODY))
                                                        .font_weight(FontWeight::MEDIUM)
                                                        .truncate(),
                                                )
                                                .child(label(format!(
                                                    "{} · {} {}{}",
                                                    meep_protocol::sessions::human_status(
                                                        &session.status
                                                    ),
                                                    message_count,
                                                    if message_count == 1 {
                                                        "message"
                                                    } else {
                                                        "messages"
                                                    },
                                                    ago(last)
                                                        .map(|a| format!(" · {a}"))
                                                        .unwrap_or_default()
                                                ))),
                                        ),
                                )
                                .on_click(cx.listener(move |this, _, window, cx| {
                                    this.select_session(view_id.clone(), id.clone(), window, cx);
                                })),
                        )
                        .when(session.status != "running", |el| {
                            let id = session.id.clone();
                            el.child(
                                ui::contextual_icon_button(
                                    SharedString::from(format!("delete-session-{id}")),
                                    Glyph::Trash,
                                    format!("Remove session {}", session.title),
                                    group,
                                    selected,
                                )
                                .on_click(cx.listener(
                                    move |this, _, _, cx| this.remove_session(id.clone(), cx),
                                )),
                            )
                        })
                        .when(leaving, |el| {
                            el.child(
                                div()
                                    .absolute()
                                    .inset_0()
                                    .bg(rgb(ui::theme::color(PAPER)))
                                    .opacity((1. - fold).clamp(0., 1.))
                                    // A row on its way out takes no more clicks.
                                    .occlude(),
                            )
                        }),
                );
            }
            panel = panel.child(
                list.relative()
                    .top(px(-ui::motion::travel(page_in, 4.)))
                    .when(page_in < 1., |el| el.child(page_veil(page_in)))
                    .when(count == 0, |el| {
                        // Nothing to list: the first session is one click away,
                        // in the same row the chat's own starters use.
                        el.child(
                            col()
                                .gap(px(4.))
                                .px(px(12.))
                                .pt(px(12.))
                                .child(
                                    text("No sessions yet")
                                        .text_size(px(14.))
                                        .font_weight(FontWeight::MEDIUM),
                                )
                                .child(label(
                                    "Each session is a conversation with the agent about this view.",
                                ).line_height(relative(1.5)))
                                .child(div().h(px(8.)))
                                .child(
                                    starter(
                                        "empty-sessions-new".into(),
                                        Glyph::Plus,
                                        "Start a session".into(),
                                    )
                                    .on_click(cx.listener(|this, _, window, cx| {
                                        this.new_session(window, cx)
                                    })),
                                ),
                        )
                    })
                    .id("view-session-list")
                    .flex_1()
                    .min_h_0()
                    .overflow_y_scroll(),
            );
            return self.agent_pane_frame(panel, window, cx);
        }
        if reset_input {
            model
                .session_input
                .update(cx, |input, cx| input.set_value("", window, cx));
        }
        let current = self.current_session();
        let body = col().flex_1().min_h_0().bg(rgb(ui::theme::color(PAPER)));
        let messages = self.session_transcript(current, window, cx);
        let running_session = current.filter(|s| s.status == "running");
        let running = running_session.is_some();
        let key = self.session_key();
        let AttachmentControls {
            busy: sending,
            has_files: has_attachments,
            chips,
            button: attach,
        } = self.attachment_controls(&key, cx);
        let has_message = has_attachments
            || !model.session_input.read(cx).value().trim().is_empty()
            || model
                .reference_drafts
                .get(&key)
                .is_some_and(|refs| !refs.is_empty());
        let away_from_latest = !self.chat_at_bottom();
        let body = body
            .child(
                col()
                    .id("session-scroll-region")
                    .relative()
                    .flex_1()
                    .min_h_0()
                    .child(
                        messages
                            .id("session-conversation")
                            .flex_1()
                            .min_h_0()
                            .overflow_y_scroll()
                            .track_scroll(model.session_scroll)
                            .on_scroll(cx.listener(|_, _, _, cx| cx.notify())),
                    )
                    .when(away_from_latest, |el| {
                        el.child(
                            div()
                                .absolute()
                                .bottom(px(8.))
                                .left_0()
                                .right_0()
                                .flex()
                                .justify_center()
                                .child(
                                    ui::button("session-latest", "Latest")
                                        .h(px(28.))
                                        .text_size(px(11.5))
                                        .icon(Glyph::ArrowDown)
                                        .bg(rgb(ui::theme::color(PAPER)))
                                        .border_1()
                                        .border_color(rgb(ui::theme::color(LINE)))
                                        .rounded(px(6.))
                                        .on_click(cx.listener(|this, _, _, cx| {
                                            // Hide the floating control in this render. The
                                            // deferred scroll also follows newly laid-out text.
                                            this.panel_model().session_scroll.set_offset(
                                                -this.panel_model().session_scroll.max_offset(),
                                            );
                                            this.panel_model().session_scroll.scroll_to_bottom();
                                            cx.notify();
                                        })),
                                ),
                        )
                    }),
            )
            .when_some(model.session_error.clone(), |el, error| {
                el.child(
                    ui::error_message("session-error", error)
                        .px(px(16.0))
                        .pb(px(12.0)),
                )
            })
            .child(
                composer::surface(
                    model
                        .session_input
                        .read(cx)
                        .focus_handle(cx)
                        .contains_focused(window, cx),
                )
                .mx(px(12.))
                .mb(px(12.))
                .when(
                    model
                        .reference_drafts
                        .get(&self.session_key())
                        .is_some_and(|items| !items.is_empty()),
                    |el| el.child(self.render_references(cx)),
                )
                .when_some(chips, |el, chips| el.child(chips))
                .when_some(
                    model
                        .session_queue
                        .get(&self.session_key())
                        .filter(|queue| !queue.is_empty()),
                    |el, queue| el.child(self.queued_messages(queue, running, cx)),
                )
                .child(
                    div()
                        .id("session-input")
                        .w_full()
                        .p(px(4.))
                        .child(composer::input(
                            model.session_input,
                            "Message the agent about this view",
                        ))
                        .relative(),
                )
                .child(
                    // One line when it fits; the trailing actions drop to their
                    // own right-aligned line only when the options need the room.
                    row()
                        .flex_wrap()
                        .gap(px(2.0))
                        .child(self.render_options(cx))
                        .child(
                            row()
                                .ml_auto()
                                .gap(px(2.0))
                                .when_some(attach, |el, button| el.child(button))
                                .child(
                                    Button::new("session-view-access")
                                        .small()
                                        .h(px(ui::CONTROL))
                                        .text_size(px(ui::BODY))
                                        .rounded(px(ui::CONTROL_RADIUS))
                                        .ghost()
                                        .size(px(ui::HIT_TARGET))
                                        .icon(Glyph::Shield)
                                        .tooltip("View permissions")
                                        .accessibility_label("View permissions")
                                        .on_click(cx.listener(|this, _, window, cx| {
                                            this.open_view_access(window, cx);
                                        })),
                                )
                                .child(
                                    ui::icon_button(
                                        "select-view-element",
                                        Glyph::MousePointer2,
                                        "Select element",
                                    )
                                    .tooltip("Select element")
                                    .on_click(cx.listener(
                                        |this, _, window, cx| this.toggle_annotation(window, cx),
                                    )),
                                )
                                .when_some(running_session, |el, session| {
                                    let id = session.id.clone();
                                    el.child(
                                        Button::new("stop-view-session")
                                            .small()
                                            .h(px(ui::CONTROL))
                                            .text_size(px(ui::BODY))
                                            .rounded(px(ui::CONTROL_RADIUS))
                                            .ghost()
                                            .size(px(ui::CONTROL))
                                            .icon(Glyph::Square)
                                            .accessibility_label("Stop agent")
                                            .tooltip("Stop agent")
                                            .on_click(cx.listener(move |this, _, _, cx| {
                                                this.cancel_session(id.clone(), cx)
                                            })),
                                    )
                                })
                                .when(running && has_message, |el| {
                                    el.child(
                                        ui::button("steer-view-session", "Steer")
                                            .ghost()
                                            .h(px(ui::CONTROL))
                                            .tooltip(
                                                crate::shortcuts::SEND_LATER
                                                    .hint("Stop this turn and send now"),
                                            )
                                            .accessibility_label("Steer the agent now")
                                            .unavailable(sending)
                                            .on_click(cx.listener(|this, _, _, cx| {
                                                this.send_session_as(true, cx)
                                            })),
                                    )
                                    .child(
                                        composer::submit("queue-view-message", "Queue message")
                                            .tooltip("Send when the agent finishes · ↵")
                                            .unavailable(sending)
                                            .on_click(
                                                cx.listener(|this, _, _, cx| this.send_session(cx)),
                                            ),
                                    )
                                })
                                .when(!running, |el| {
                                    el.child(
                                        composer::submit("send-view-message", "Send message")
                                            .tooltip("Send message")
                                            .unavailable(
                                                sending
                                                    || model
                                                        .session_configuring
                                                        .contains(&self.session_key())
                                                    || !has_message,
                                            )
                                            .on_click(
                                                cx.listener(|this, _, _, cx| this.send_session(cx)),
                                            ),
                                    )
                                }),
                        ),
                ),
            );
        let body = body.when_some(self.session_suggestions(cx), |body, suggestions| {
            body.child(suggestions)
        });
        let body = body
            .relative()
            .when(page_in < 1., |el| el.child(page_veil(page_in)));
        self.agent_pane_frame(panel.child(body), window, cx)
    }
    /// Render the follow-ups for the current preview.
    fn session_suggestions(&self, cx: &mut Context<Self>) -> Option<Div> {
        let items = self.preview_session_starters();
        if items.is_empty() {
            return None;
        }
        Some(
            col()
                .px(px(20.))
                .pb(px(12.))
                .gap(px(2.))
                .children(items.into_iter().map(|(id, prompt)| {
                    starter(
                        format!("replay-suggestion-{id}").into(),
                        Glyph::Rows3,
                        prompt.clone(),
                    )
                    .on_click(cx.listener(move |this, _, window, cx| {
                        this.choose_session_starter(prompt.clone(), window, cx)
                    }))
                })),
        )
    }
    /// The agent pane rests on the glass beside the view: the same gutter on
    /// every side, and the resize band lives in the gutter it resizes.
    fn agent_pane_frame(&self, pane: Div, window: &Window, cx: &mut Context<Self>) -> Div {
        col()
            .w(px(self.agent_panel_width(window)))
            .flex_shrink_0()
            .h_full()
            .min_h_0()
            .relative()
            .p(px(super::GUTTER))
            .child(pane)
            .child(self.render_resize(cx))
    }
}

/// How long ago a Unix-millisecond time was, in a few words; nothing for
/// unknown times.
fn ago(ms: i64) -> Option<String> {
    if ms <= 0 {
        return None;
    }
    let minutes = (chrono::Utc::now().timestamp_millis() - ms).max(0) / 60_000;
    Some(match minutes {
        0 => "just now".into(),
        1..=59 => format!("{minutes}m ago"),
        60..=1439 => format!("{}h ago", minutes / 60),
        1440..=10079 => format!("{}d ago", minutes / 1440),
        _ => chrono::DateTime::from_timestamp_millis(ms)
            .map(|t| t.with_timezone(&chrono::Local).format("%-e %b").to_string())
            .unwrap_or_default(),
    })
}

/// Paper over a page that is arriving, lifting as it comes in. Square at the
/// top, where the page meets the header; rounded where it meets the pane.
fn page_veil(progress: f32) -> Div {
    div()
        .absolute()
        .inset_0()
        .rounded_b(px(super::PANE_RADIUS))
        .bg(rgb(ui::theme::color(PAPER)))
        .opacity((1. - progress).clamp(0., 1.))
}
