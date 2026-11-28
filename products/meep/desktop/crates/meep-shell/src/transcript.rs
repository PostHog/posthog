//! Rendering for a conversation, including selectable messages and grouped tool calls.
use super::*;
use gpui_kit::component::{
    text::{TextView, TextViewStyle},
    *,
};
use meep_protocol::sessions::*;
use std::collections::HashSet;

pub fn pending_reply() -> Div {
    row()
        .h(px(20.))
        .gap(px(6.))
        .child(
            spinner::Spinner::new()
                .with_size(px(13.))
                .color(rgb(ui::theme::color(MUTED)).into()),
        )
        .child(label("Thinking"))
}

/// Stable identity and position for a conversation row in either a list or a full pane.
pub struct TranscriptRow<'a> {
    /// Turn to render.
    pub message: &'a AgentMessage,
    /// Stable element key for this row.
    pub key: &'a str,
    /// Position in the session, used to anchor approval cards.
    pub index: usize,
    /// Whether this is the in-progress agent reply.
    pub active: bool,
}

/// Supplies disclosure state, provider presentation and approval interactions.
pub trait TranscriptHost: Sized + 'static {
    /// Fallback author label for messages saved without an agent name.
    fn harness_name(_command: &str) -> &str {
        "Agent"
    }
    /// Format tool output for an expanded block.
    fn tool_output(output: &str) -> String {
        output.to_owned()
    }
    /// Render the icon for a tool's service.
    fn tool_logo(_name: &str, size: f32) -> Div {
        div().child(icon(Glyph::Wrench).size(px(size)))
    }
    /// Block keys whose details are visible.
    fn expanded(&self) -> &HashSet<String>;
    /// Update disclosure state when a reader toggles a block.
    fn expanded_mut(&mut self) -> &mut HashSet<String>;
    /// Indicator displayed alongside an active reply.
    fn activity_indicator(&self) -> &Entity<ActivityIndicator>;
    /// Suggested prompts for an empty conversation.
    fn session_starters(&self) -> Vec<(Glyph, SharedString)> {
        Vec::new()
    }
    /// Handle selection of a host-supplied suggested prompt.
    fn choose_session_starter(
        &mut self,
        _prompt: SharedString,
        _window: &mut Window,
        _cx: &mut Context<Self>,
    ) {
    }
    /// Begin or end element selection in a View session.
    fn toggle_annotation(&mut self, _window: &mut Window, _cx: &mut Context<Self>) {}
    /// Whether an empty View session offers element selection.
    fn annotation_starter(&self) -> bool {
        true
    }
    /// Render the approval and bind its actions to the host.
    fn approval_card(
        &self,
        session: &AgentSession,
        approval: &AgentApproval,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> Div;

    /// Render a session, offering View starters for a new or legacy View session.
    fn session_transcript(
        &self,
        session: Option<&AgentSession>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> Div {
        let kind = session.map_or(EmptyConversation::View, |s| {
            EmptyConversation::for_session(s.topic.as_deref(), &s.view_id)
        });
        render_transcript(self, session, kind, window, cx)
    }

    /// Render a plain chat, including before its first session is created.
    fn chat_transcript(
        &self,
        session: Option<&AgentSession>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> Div {
        render_transcript(self, session, EmptyConversation::Chat, window, cx)
    }
    /// Render one conversation message, including its tools, permissions and copy actions.
    fn transcript_row(
        &self,
        session: &AgentSession,
        slot: TranscriptRow<'_>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> Div {
        let TranscriptRow {
            message,
            key: message_key,
            index,
            active,
        } = slot;
        if message.role == "user" {
            let group: SharedString = format!("user-turn-{message_key}").into();
            let copy = message.text.clone();
            let bubble =
                user_bubble()
                    .children(message.references.iter().enumerate().map(|(n, r)| {
                        col()
                            .gap(px(3.))
                            .mb(px(6.))
                            .child(
                                selectable(format!("{message_key}-ref-{n}-label"), r.label.clone())
                                    .text_size(px(11.5))
                                    .font_weight(FontWeight::MEDIUM),
                            )
                            .child(
                                selectable(format!("{message_key}-ref-{n}"), r.comment.clone())
                                    .text_size(px(ui::BODY)),
                            )
                            .when(r.stale, |el| el.child(label("Earlier version")))
                    }))
                    .when(!message.attachments.is_empty(), |el| {
                        el.child(
                            composer::attachment_row()
                                .children(message.attachments.iter().map(|file| {
                                    composer::attachment_chip(&file.name, &file.mime_type)
                                }))
                                .mb(px(4.)),
                        )
                    })
                    .when(!message.text.is_empty(), |el| {
                        let fold_key = format!("fold-{message_key}");
                        let folded = folded_text(&message.text);
                        let open = self.expanded().contains(&fold_key);
                        let shown = match (&folded, open) {
                            (Some(short), false) => short.clone(),
                            _ => message.text.clone(),
                        };
                        el.child(
                            selectable(format!("{message_key}-text"), shown)
                                .text_size(px(READ))
                                .line_height(relative(1.55)),
                        )
                        .when(folded.is_some(), |el| {
                            el.child(
                                div()
                                    .id(SharedString::from(format!("fold-toggle-{message_key}")))
                                    .mt(px(4.))
                                    .cursor_pointer()
                                    .text_size(px(ui::SMALL))
                                    .font_weight(FontWeight::MEDIUM)
                                    .text_color(rgb(ui::theme::color(MUTED)))
                                    .hover(|s| s.text_color(rgb(ui::theme::color(ui::INK))))
                                    .child(if open { "Show less" } else { "Show all" })
                                    .on_click(cx.listener(move |this, _, _, cx| {
                                        if !this.expanded_mut().remove(&fold_key) {
                                            this.expanded_mut().insert(fold_key.clone());
                                        }
                                        cx.notify();
                                    })),
                            )
                        })
                    });
            // Copy sits left of the time and matches its height, so the
            // footer stays one quiet line and hovering never shifts it.
            let footer = row()
                .h(px(20.))
                .gap(px(2.))
                .pr(px(2.))
                .when(!copy.is_empty(), |el| {
                    el.child(
                        ui::copy_button(
                            SharedString::from(format!("copy-message-{message_key}")),
                            "Copy message",
                            copy,
                        )
                        .compact(20., 12., 4.)
                        .contextual(group.clone()),
                    )
                })
                .when_some(message_time(message.created_at), |el, time| {
                    el.child(
                        selectable(format!("{message_key}-time"), time)
                            .text_size(px(ui::SMALL))
                            .text_color(rgb(ui::theme::color(MUTED))),
                    )
                });
            return col()
                .child(
                    div()
                        .id(group.clone())
                        .group(group)
                        .w_full()
                        .min_w_0()
                        .child(
                            col()
                                .w_full()
                                .items_end()
                                .gap(px(2.))
                                .child(bubble)
                                .child(footer),
                        ),
                )
                .when(active, |col| {
                    col.child(
                        pending_reply().id(SharedString::from(format!("pending-{message_key}"))),
                    )
                });
        }
        let group: SharedString = format!("assistant-turn-{message_key}").into();
        let response = response_text(message);
        let agent_name = if message.agent_name.is_empty() {
            Self::harness_name(&session.agent_command).to_owned()
        } else {
            message.agent_name.clone()
        };
        // An unnamed reply keeps its timestamp flush with the reply text. With
        // nothing to show, the reply skips the row so turns keep one rhythm.
        let time = reply_time(&session.messages, index);
        let show_heading = heading_visible(&agent_name, time.as_deref(), active);
        let mut heading = row()
            .w_full()
            .h(px(28.))
            .gap(px(8.))
            .when(!agent_name.is_empty(), |el| {
                el.child(
                    text(agent_name)
                        .text_size(px(11.5))
                        .font_weight(FontWeight::MEDIUM)
                        .text_color(rgb(ui::theme::color(MUTED))),
                )
            })
            .when_some(time, |el, time| {
                el.child(
                    selectable(format!("{message_key}-time"), time)
                        .flex_none()
                        .text_size(px(ui::SMALL))
                        .text_color(rgb(ui::theme::color(MUTED))),
                )
            });
        if active {
            let waiting = session.approvals.iter().any(|a| a.status == "pending");
            heading = heading.child(
                row()
                    .flex_1()
                    .gap(px(5.))
                    .min_w_0()
                    .child(if waiting {
                        icon(Glyph::Shield).size(px(11.)).into_any_element()
                    } else {
                        self.activity_indicator().clone().into_any_element()
                    })
                    .child(
                        label(turn_status(session, message))
                            .flex_1()
                            .min_w_0()
                            .text_size(px(11.))
                            .truncate(),
                    ),
            );
        }
        let copy = response.clone();
        let copy_button = (!response.is_empty()).then(|| {
            ui::copy_button(
                SharedString::from(format!("copy-response-{message_key}")),
                "Copy response",
                copy,
            )
            .contextual(group.clone())
        });
        // Without a heading, copy floats over the reply's top corner on hover.
        let (copy_in_heading, floating_copy) = if show_heading {
            (copy_button, None)
        } else {
            (None, copy_button)
        };
        heading = heading
            .when(!active, |el| el.child(div().flex_1()))
            .children(copy_in_heading);
        let mut content = col()
            .min_w_0()
            .w_full()
            .gap(px(4.))
            .when(show_heading, |el| el.child(heading));
        if message.blocks.is_empty() && !message.text.is_empty() {
            content = content.child(
                chat_markdown(
                    SharedString::from(message_key.to_owned()),
                    message.text.clone(),
                )
                .text_size(px(READ))
                .line_height(relative(1.55)),
            );
        }
        // Keep consecutive completed work compact, in its original place in the turn.
        // Running/failed tools, assistant text and approvals never disappear into this group.
        let completed = |i: usize, block: &SessionBlock| {
            block.kind != "text"
                && (block.status == "completed"
                    || (block.kind == "thinking"
                        && (i + 1 < message.blocks.len() || session.status != "running")))
        };
        // Each approval stays where it was requested, so later work flows below it.
        let approvals: Vec<&AgentApproval> = session
            .approvals
            .iter()
            .filter(|a| {
                a.message_index == index
                    && !(a.change["kind"] == "screenshot" && a.status == "pending")
            })
            .collect();
        let anchor = |a: &AgentApproval| a.block_index.unwrap_or(usize::MAX);
        let anchored = |i: usize| approvals.iter().any(|a| anchor(a) == i);
        let mut grouped_until = 0;
        let mut group_open = true;
        for (block_index, block) in message.blocks.iter().enumerate() {
            for approval in approvals.iter().filter(|a| anchor(a) == block_index) {
                content = content.child(self.approval_card(session, approval, window, cx));
            }
            if block_index >= grouped_until {
                let count = message.blocks[block_index..]
                    .iter()
                    .enumerate()
                    .take_while(|(offset, b)| {
                        completed(block_index + offset, b)
                            && (*offset == 0 || !anchored(block_index + offset))
                    })
                    .count();
                grouped_until = block_index + count;
                group_open = true;
                if count >= 2 {
                    let group_key = format!("activity-{message_key}-{block_index}");
                    group_open = self.expanded().contains(&group_key);
                    content = content.child(
                        crate::controls::quiet_button(SharedString::from(group_key.clone()), cx)
                            .small()
                            .h(px(28.))
                            .w_full()
                            .px(px(0.))
                            .justify_start()
                            .accessibility_label(format!(
                                "{} {count} completed steps",
                                if group_open { "Collapse" } else { "Expand" }
                            ))
                            .child(
                                row()
                                    .w_full()
                                    .min_w_0()
                                    .gap(px(6.))
                                    .child(
                                        icon(if group_open {
                                            Glyph::ChevronDown
                                        } else {
                                            Glyph::ChevronRight
                                        })
                                        .size(px(12.)),
                                    )
                                    .child(
                                        label(format!("{count} completed steps"))
                                            .flex_1()
                                            .text_size(px(11.5)),
                                    ),
                            )
                            .on_click(cx.listener(move |this, _, _, cx| {
                                if !this.expanded_mut().remove(&group_key) {
                                    this.expanded_mut().insert(group_key.clone());
                                }
                                cx.notify();
                            })),
                    );
                }
            }
            if block_index < grouped_until && !group_open {
                continue;
            }
            let key = format!("{message_key}-{block_index}");
            if block.kind == "text" {
                content = content.child(
                    chat_markdown(SharedString::from(key), block.text.clone())
                        .text_size(px(READ))
                        .line_height(relative(1.55)),
                );
            } else {
                let open = self.expanded().contains(&key);
                let toggle_key = key.clone();
                let title = if block.kind == "thinking" {
                    "Thinking".to_owned()
                } else {
                    tool_title(&block.text).to_owned()
                };
                let status = match block.status.as_str() {
                    "in_progress" => "Running",
                    "completed" => "",
                    "failed" => "Failed",
                    "cancelled" => "Stopped",
                    "pending" => "Pending",
                    _ => "",
                };
                let disclosure_label = format!("{} {}", if open { "Hide" } else { "Show" }, title);
                let mut disclosure = col()
                    .w_full()
                    .min_w_0()
                    .pl(px(8.))
                    .border_l_1()
                    .border_color(rgb(ui::theme::color(ui::RULE)))
                    .child(
                        crate::controls::quiet_button(
                            SharedString::from(format!("disclose-{key}")),
                            cx,
                        )
                        .small()
                        .h(px(ui::CONTROL))
                        .text_size(px(ui::BODY))
                        .rounded(px(ui::CONTROL_RADIUS))
                        .w_full()
                        .accessibility_label(disclosure_label)
                        .h_auto()
                        .min_h(px(26.))
                        .px(px(0.0))
                        .justify_start()
                        .accessibility_label(format!(
                            "{} {}",
                            if open { "Collapse" } else { "Expand" },
                            title
                        ))
                        .child(
                            row()
                                .w_full()
                                .min_w_0()
                                .gap(px(6.))
                                .child(
                                    icon(if open {
                                        Glyph::ChevronDown
                                    } else {
                                        Glyph::ChevronRight
                                    })
                                    .size(px(12.)),
                                )
                                .when_some(
                                    block.app.as_ref().filter(|_| block.kind == "tool"),
                                    |row, app| {
                                        row.child(
                                            Self::tool_logo(app, 14.)
                                                .id(SharedString::from(format!("tool-app-{key}")))
                                                .aria_label(app.clone()),
                                        )
                                    },
                                )
                                .child(
                                    text(title)
                                        .text_size(px(11.5))
                                        .text_color(rgb(ui::theme::color(MUTED)))
                                        .truncate()
                                        .flex_1()
                                        .min_w_0(),
                                )
                                .child(label(status).text_size(px(ui::SMALL))),
                        )
                        .on_click(cx.listener(move |this, _, _, cx| {
                            if !this.expanded_mut().remove(&toggle_key) {
                                this.expanded_mut().insert(toggle_key.clone());
                            }
                            cx.notify();
                        })),
                    );
                let reveal_id = ElementId::NamedChild(
                    ElementId::from("tool-disclosure").into(),
                    key.clone().into(),
                );
                let progress = ui::motion::reveal(reveal_id.clone(), open, window, cx);
                if progress > 0. {
                    let detail = if block.kind == "thinking" {
                        block.text.clone()
                    } else {
                        format!(
                            "Tool: {}\n\n{}{}{}",
                            block.text,
                            block.input,
                            if !block.input.is_empty() && !block.output.is_empty() {
                                "\n\n"
                            } else {
                                ""
                            },
                            Self::tool_output(&block.output)
                        )
                    };
                    let copy = detail.clone();
                    let body = div()
                        .id(SharedString::from(format!("tool-detail-scroll-{key}")))
                        .max_h(px(220.))
                        .min_w_0()
                        .flex_1()
                        .overflow_y_scroll()
                        .child(if block.kind == "thinking" {
                            chat_markdown(SharedString::from(format!("thinking-{key}")), detail)
                                .text_size(px(ui::CAPTION))
                                .line_height(relative(1.5))
                                .into_any_element()
                        } else {
                            selectable(format!("tool-detail-{key}"), detail)
                                .font_family(ui::mono_font())
                                .text_size(px(ui::MONO))
                                .line_height(relative(1.5))
                                .into_any_element()
                        });
                    let copy_button = div().flex_shrink_0().child(
                        ui::copy_button(
                            SharedString::from(format!("copy-{key}")),
                            "Copy details",
                            copy,
                        )
                        .compact(22., 14., ui::ICON_RADIUS),
                    );
                    let details = col()
                        .w_full()
                        .min_w_0()
                        .pl(px(18.))
                        .pb(px(6.))
                        .when(block.kind != "thinking", |el| {
                            el.child(label("Input / output").text_size(px(10.)).mb(px(6.)))
                        })
                        .child(
                            row()
                                .w_full()
                                .min_w_0()
                                .items_start()
                                .gap(px(8.))
                                .child(body)
                                .child(copy_button),
                        );
                    disclosure = disclosure.child(ui::motion::fold(
                        reveal_id,
                        progress,
                        details.into_any_element(),
                    ));
                }
                content = content.child(disclosure);
            }
        }
        // Requests made after the last block (or before anchors existed) close the turn.
        for approval in approvals
            .iter()
            .filter(|a| anchor(a) >= message.blocks.len())
        {
            content = content.child(self.approval_card(session, approval, window, cx));
        }
        if !message.text.is_empty() || !message.blocks.is_empty() || !approvals.is_empty() || active
        {
            return col().child(
                div()
                    .id(group.clone())
                    .group(group)
                    .relative()
                    .w_full()
                    .min_w_0()
                    .child(content)
                    .when_some(floating_copy, |el, button| {
                        el.child(div().absolute().top_0().right_0().child(button))
                    }),
            );
        }
        col()
    }
}

fn render_transcript<H: TranscriptHost>(
    host: &H,
    session: Option<&AgentSession>,
    kind: EmptyConversation,
    window: &mut Window,
    cx: &mut Context<H>,
) -> Div {
    let Some(session) = session else {
        return empty_transcript(host, kind, cx);
    };
    let mut transcript = if session.messages.is_empty() {
        empty_transcript(host, kind, cx).children(
            session
                .approvals
                .iter()
                .map(|approval| host.approval_card(session, approval, window, cx)),
        )
    } else {
        transcript_surface()
    };
    for (index, message) in session.messages.iter().enumerate() {
        let key = format!("{}-{index}", session.id);
        transcript = transcript.child(host.transcript_row(
            session,
            TranscriptRow {
                message,
                key: &key,
                index,
                active: index + 1 == session.messages.len() && session.status == "running",
            },
            window,
            cx,
        ));
    }
    if let Some(error) = &session.error {
        transcript = transcript.child(
            selectable(format!("{}-error", session.id), error.clone())
                .text_size(px(ui::BODY))
                .text_color(rgb(ui::theme::color(MUTED)))
                .line_height(relative(1.5)),
        );
    }
    transcript
}

fn transcript_surface() -> Div {
    col()
        .bg(rgb(ui::theme::color(PAPER)))
        .gap(px(16.))
        .px(px(ui::PANEL_INSET))
        .py(px(16.))
        .min_w_0()
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum EmptyConversation {
    Chat,
    View,
}

impl EmptyConversation {
    fn for_session(topic: Option<&str>, view_id: &str) -> Self {
        if topic.is_none() && !view_id.is_empty() {
            Self::View
        } else {
            Self::Chat
        }
    }
}

fn empty_transcript<H: TranscriptHost>(
    host: &H,
    kind: EmptyConversation,
    cx: &mut Context<H>,
) -> Div {
    let starters = host.session_starters();
    let view = kind == EmptyConversation::View;
    let annotate = view && host.annotation_starter();
    transcript_surface().justify_center().child(
        col()
            .gap(px(4.))
            .pb(px(64.))
            .child(
                text(if view {
                    "Work on this view"
                } else {
                    "Start a conversation"
                })
                .text_size(px(14.))
                .font_weight(FontWeight::MEDIUM),
            )
            .when(view, |el| {
                el.child(
                    label("Ask for a change in your own words, or start from one of these.")
                        .line_height(relative(1.5)),
                )
            })
            .when(!starters.is_empty() || annotate, |el| {
                el.child(div().h(px(8.)))
            })
            .children(
                starters
                    .into_iter()
                    .enumerate()
                    .map(|(index, (glyph, prompt))| {
                        starter(
                            SharedString::from(format!("chat-starter-{index}")),
                            glyph,
                            prompt.clone(),
                        )
                        .on_click(cx.listener(
                            move |this, _, window, cx| {
                                this.choose_session_starter(prompt.clone(), window, cx);
                            },
                        ))
                    }),
            )
            .when(annotate, |el| {
                el.child(
                    starter(
                        "empty-chat-select".into(),
                        Glyph::MousePointer2,
                        "Point to an element to change".into(),
                    )
                    .on_click(
                        cx.listener(|this, _, window, cx| this.toggle_annotation(window, cx)),
                    ),
                )
            }),
    )
}

fn folded_text(text: &str) -> Option<String> {
    const KEEP: usize = 360;
    if text.chars().count() <= KEEP + 120 && text.lines().count() <= 8 {
        return None;
    }
    let head: String = text.chars().take(KEEP).collect();
    let cut = head
        .rfind("\n\n")
        .filter(|&i| i > KEEP / 3)
        .or_else(|| head.rfind(". ").map(|i| i + 1))
        .or_else(|| head.rfind(' '))
        .unwrap_or(head.len());
    Some(format!(
        "{}…",
        head[..cut]
            .trim_end()
            .trim_end_matches(['.', ',', ';', ':'])
    ))
}

/// Shared surface for a user turn in a native chat transcript.
pub fn user_bubble() -> Div {
    col()
        .max_w(relative(0.92))
        .rounded(px(8.))
        .bg(rgb(ui::theme::color(ui::INSET)))
        .px(px(10.))
        .py(px(8.))
        .min_w_0()
}

/// Plain text that joins the window's text selection, so a drag can start in
/// it, run across neighbouring messages, and copy with Cmd-C. It renders
/// through the same text view as replies, escaped so it reads literally:
/// one kind of selectable text keeps a drag across messages in reading order.
pub fn selectable(id: impl Into<SharedString>, body: impl Into<SharedString>) -> TextView {
    TextView::markdown(ElementId::Name(id.into()), literal_markdown(&body.into()))
        .selectable(true)
        .style(TextViewStyle {
            paragraph_gap: rems(0.5),
            ..Default::default()
        })
}

/// Markdown that renders `text` as written: punctuation escaped, line breaks
/// kept, and leading spaces held so indentation is not read as a code block.
fn literal_markdown(text: &str) -> String {
    let mut out = String::with_capacity(text.len() + text.len() / 4);
    let text = text.replace("\r\n", "\n");
    let paragraphs = text
        .split("\n\n")
        .map(|p| p.trim_matches('\n'))
        .filter(|p| !p.trim().is_empty());
    for (index, paragraph) in paragraphs.enumerate() {
        if index > 0 {
            out.push_str("\n\n");
        }
        for (line_index, line) in paragraph.lines().map(str::trim_end).enumerate() {
            if line_index > 0 {
                out.push_str("\\\n");
            }
            let indent = line.len() - line.trim_start_matches([' ', '\t']).len();
            for c in line[..indent].chars() {
                out.push_str(if c == '\t' {
                    "\u{a0}\u{a0}\u{a0}\u{a0}"
                } else {
                    "\u{a0}"
                });
            }
            for c in line[indent..].chars() {
                if c.is_ascii_punctuation() {
                    out.push('\\');
                }
                out.push(c);
            }
        }
    }
    out
}

/// Whether a reply's heading row has anything to show: the agent's name, a
/// time, or live activity. An empty row would only add space between turns.
fn heading_visible(agent_name: &str, time: Option<&str>, active: bool) -> bool {
    !agent_name.is_empty() || time.is_some() || active
}

/// The time a message was sent: the clock alone today, with the date before.
/// A reply's time, omitted when the previous message already shows a time
/// within five minutes of it, so one moment isn't printed twice in a row.
fn reply_time(messages: &[AgentMessage], index: usize) -> Option<String> {
    const NEARBY_MS: i64 = 5 * 60 * 1000;
    let created_at = messages.get(index)?.created_at;
    let previous = index
        .checked_sub(1)
        .and_then(|i| messages.get(i))
        .map(|m| m.created_at)
        .filter(|&t| t > 0);
    if previous.is_some_and(|t| (created_at - t).abs() <= NEARBY_MS) {
        return None;
    }
    message_time(created_at)
}

fn message_time(created_at: i64) -> Option<String> {
    use chrono::{Local, TimeZone};
    if created_at <= 0 {
        return None;
    }
    let time = Local.timestamp_millis_opt(created_at).single()?;
    let now = Local::now();
    Some(if time.date_naive() == now.date_naive() {
        time.format("%H:%M").to_string()
    } else if time.format("%Y").to_string() == now.format("%Y").to_string() {
        time.format("%b %-d, %H:%M").to_string()
    } else {
        time.format("%b %-d %Y, %H:%M").to_string()
    })
}

fn tool_title(title: &str) -> &str {
    let tool = title
        .strip_prefix("mcp.view.")
        .or_else(|| title.strip_prefix("mcp__view__"))
        .unwrap_or(title);
    match tool {
        "connections_search" => "Find connections",
        "connections_import_api" => "Read API description",
        "connections_request" => "Suggest connection",
        "permissions_inspect" => "Inspect permissions",
        "permissions_request" => "Request permission change",
        "cli_discover" => "Read command help",
        "cli_list" => "Inspect allowed CLI actions",
        "cli_run" => "Run CLI action",
        "views_inspect" => "Inspect view",
        "views_screenshot" => "Capture view",
        "views_install_script" => "Update view",
        "views_read_source" => "Read view source",
        "views_search_source" => "Search view source",
        "views_edit_source" => "Edit view live",
        "design_system" => "Read design guidance",
        "views_control" => "Control view",
        "sources_list" => "Inspect connected sources",
        "sources_describe" => "Read tool schemas",
        "sources_call" => "Call MCP tool",
        _ => title,
    }
}

fn response_text(message: &AgentMessage) -> String {
    if message.blocks.is_empty() {
        return message.text.clone();
    }
    message
        .blocks
        .iter()
        .filter(|b| b.kind == "text")
        .map(|b| b.text.as_str())
        .collect::<Vec<_>>()
        .join("\n\n")
}
/// Describe the activity in the current agent turn.
pub fn turn_status<'a>(session: &AgentSession, message: &'a AgentMessage) -> &'a str {
    if session.approvals.iter().any(|a| a.status == "pending") {
        return "Awaiting approval";
    }
    if let Some(block) = message
        .blocks
        .iter()
        .rev()
        .find(|b| b.kind == "tool" && ["in_progress", "pending"].contains(&b.status.as_str()))
    {
        return tool_title(&block.text);
    }
    if message.blocks.last().is_some_and(|b| b.kind == "text")
        || (message.blocks.is_empty() && !message.text.is_empty())
    {
        "Responding"
    } else {
        "Thinking"
    }
}
/// Agent or message text rendered as markdown, with the transcript's rhythm.
/// Conversation text: set for reading, as a chat or a document reads.
pub const READ: f32 = 15.;

pub fn chat_markdown(id: SharedString, body: String) -> TextView {
    TextView::markdown(id, body)
        .selectable(true)
        .style(
            TextViewStyle {
                paragraph_gap: rems(0.75),
                heading_base_font_size: px(READ),
                ..Default::default()
            }
            // Flat headings: a step up in weight more than in size.
            .heading_font_size(|level, base| {
                base * match level {
                    1 => 1.2,
                    2 => 1.1,
                    _ => 1.0,
                }
            })
            .code_block(
                StyleRefinement::default()
                    .bg(rgb(ui::theme::color(ui::INSET)))
                    .rounded(px(6.))
                    .p(px(8.)),
            ),
        )
        .code_block_actions(|block, _, _| {
            let id = block.span.map_or(0, |span| span.start);
            row().w_full().justify_end().child(ui::copy_button(
                SharedString::from(format!("copy-code-{id}")),
                "Copy code",
                block.code(),
            ))
        })
}

/// Notifies only this entity. Generated views retain their GPUI view cache
/// across ticks; no timer survives a hidden or idle chat.
#[derive(Default)]
pub struct ActivityIndicator {
    /// Index of the current animation frame.
    pub frame: usize,
    /// Set for the sidebar's copy, which sits on the row's trailing ink line.
    sidebar: bool,
    timer: Option<Task<()>>,
    reduced: bool,
}
const ACTIVITY_FRAMES: [&str; 10] = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
impl ActivityIndicator {
    /// Build the compact indicator used on a sidebar row.
    pub fn sidebar() -> Self {
        Self {
            sidebar: true,
            ..Self::default()
        }
    }
    /// Start or stop animation according to activity and motion preferences.
    pub fn set_active(&mut self, active: bool, reduced: bool, cx: &mut Context<Self>) {
        if self.reduced != reduced {
            self.reduced = reduced;
            cx.notify();
        }
        if !active || reduced {
            self.timer = None;
        } else if self.timer.is_none() {
            self.timer = Some(cx.spawn(async move |this, cx| {
                loop {
                    cx.background_executor()
                        .timer(std::time::Duration::from_millis(80))
                        .await;
                    if this
                        .update(cx, |this, cx| {
                            this.frame = (this.frame + 1) % ACTIVITY_FRAMES.len();
                            cx.notify();
                        })
                        .is_err()
                    {
                        break;
                    }
                }
            }));
        }
    }
}
impl Render for ActivityIndicator {
    fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
        div()
            .id(if self.sidebar {
                "sidebar-activity-spinner"
            } else {
                "chat-activity-spinner"
            })
            .w(px(12.))
            .flex_shrink_0()
            .flex()
            .justify_end()
            .accessibility_id("Agent working")
            .child(
                text(ACTIVITY_FRAMES[if self.reduced { 0 } else { self.frame }])
                    .font_family(ui::mono_font())
                    .text_size(px(if self.sidebar { 15. } else { 13. }))
                    // Menlo's braille ink stops short of its advance; the
                    // sidebar's lands on the count's trailing line.
                    .when(self.sidebar, |t| t.mr(px(-1.5)))
                    .text_color(rgb(ui::theme::color(MUTED))),
            )
    }
}

/// Render a selectable prompt or action for an empty session.
pub fn starter(id: SharedString, glyph: Glyph, title: SharedString) -> Stateful<Div> {
    div()
        .relative()
        .id(id)
        .role(Role::Button)
        .aria_label(title.clone())
        .flex()
        .items_center()
        .gap(px(8.))
        .h(px(30.))
        .px(px(8.))
        .mx(px(-8.))
        .rounded(px(6.))
        .cursor_pointer()
        .hover(|s| s.bg(ui::ink(0x0a)))
        .child(ui::nav::glyph(glyph, false))
        .child(ui::nav::title(title))
}

#[cfg(test)]
mod tests {
    use super::{EmptyConversation, heading_visible, literal_markdown, reply_time};
    use meep_protocol::sessions::AgentMessage;

    #[test]
    fn a_reply_close_to_the_previous_message_omits_its_time() {
        let at = |created_at| AgentMessage {
            created_at,
            ..Default::default()
        };
        let base = 1_700_000_000_000;
        let near = [at(base), at(base + 4 * 60 * 1000)];
        assert_eq!(reply_time(&near, 1), None);
        let far = [at(base), at(base + 6 * 60 * 1000)];
        assert!(reply_time(&far, 1).is_some());
        assert!(reply_time(&far[1..], 0).is_some());
    }

    #[test]
    fn an_unnamed_reply_without_a_time_or_activity_has_no_heading() {
        assert!(!heading_visible("", None, false));
        assert!(heading_visible("Codex", None, false));
        assert!(heading_visible("", Some("09:30"), false));
        assert!(heading_visible("", None, true));
    }

    #[test]
    fn topic_ownership_takes_precedence_over_an_associated_view() {
        assert_eq!(
            EmptyConversation::for_session(Some("weekly"), "chart"),
            EmptyConversation::Chat
        );
        assert_eq!(
            EmptyConversation::for_session(Some("weekly"), ""),
            EmptyConversation::Chat
        );
    }

    #[test]
    fn only_a_legacy_view_conversation_offers_element_selection_by_default() {
        assert_eq!(
            EmptyConversation::for_session(None, "chart"),
            EmptyConversation::View
        );
        assert_eq!(
            EmptyConversation::for_session(None, ""),
            EmptyConversation::Chat
        );
    }
    #[test]
    fn literal_markdown_keeps_text_as_written() {
        assert_eq!(
            literal_markdown("# not a *heading*"),
            "\\# not a \\*heading\\*"
        );
        assert_eq!(
            literal_markdown("one\ntwo\n\n\nthree"),
            "one\\\ntwo\n\nthree"
        );
        assert_eq!(
            literal_markdown("{\n    \"a\": 1\n}"),
            "\\{\\\n\u{a0}\u{a0}\u{a0}\u{a0}\\\"a\\\"\\: 1\\\n\\}"
        );
    }
}
