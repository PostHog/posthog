//! A topic's status at a glance: hovering its sidebar row shows what its agent is
//! doing and what is waiting, as View's sidebar cards do.
use super::pages::UNREAD;
use super::*;

impl Desktop {
    /// Open the card after a short hover; leaving the row or the card closes it after
    /// a short grace, so the pointer can cross from one to the other.
    pub(super) fn hover_topic_card(&mut self, id: TopicId, hovered: bool, cx: &mut Context<Self>) {
        self.hover_card(Card::Topic(id), hovered, cx)
    }

    pub(super) fn hover_card(&mut self, id: Card, hovered: bool, cx: &mut Context<Self>) {
        if cx.has_active_drag() {
            self.dismiss_topic_card(cx);
            return;
        }
        if hovered {
            self.topic_card.epoch += 1;
            self.topic_card.hover = Some(id);
            if self.topic_card.open.is_some() {
                // Moving between rows swaps the card at once.
                self.topic_card.open = Some(id);
                cx.notify();
                return;
            }
        } else {
            if self.topic_card.inside || self.topic_card.hover != Some(id) {
                return;
            }
            self.topic_card.hover = None;
            self.topic_card.epoch += 1;
        }
        let epoch = self.topic_card.epoch;
        let delay = if hovered { 450 } else { 100 };
        cx.spawn(async move |this, cx| {
            cx.background_executor()
                .timer(std::time::Duration::from_millis(delay))
                .await;
            let _ = this.update(cx, |this, cx| {
                if this.topic_card.epoch != epoch || cx.has_active_drag() {
                    return;
                }
                this.topic_card.open = hovered.then_some(id);
                cx.notify();
            });
        })
        .detach();
    }

    pub(super) fn dismiss_topic_card(&mut self, cx: &mut Context<Self>) {
        self.topic_card.epoch += 1;
        self.topic_card.hover = None;
        self.topic_card.inside = false;
        if self.topic_card.open.take().is_some() {
            cx.notify();
        }
    }

    /// The card beside a topic's row: its mission, then one line per part that has
    /// something to say, each opening that part.
    pub(super) fn topic_card(&self, s: &TopicState, cx: &mut Context<Self>) -> Option<AnyElement> {
        let id = s.topic.id;
        if self.topic_card.open != Some(Card::Topic(id)) {
            return None;
        }
        // The card only speaks when there is something live: work in progress, or
        // something waiting on the person. Otherwise the row says enough.
        let working = desktop::topic_working(s).then(|| {
            s.tasks
                .iter()
                .filter(|t| t.column == Column::InProgress)
                .find_map(|t| t.worker.clone())
                .filter(|w| !w.is_empty() && w != "Running" && w != "in_progress")
                .unwrap_or_else(|| "Thinking".into())
        });
        let waiting: Vec<pages::Attention> = self
            .needs
            .iter()
            .filter_map(|n| pages::attention(n, s))
            .collect();
        if working.is_none() && waiting.is_empty() {
            return None;
        }
        let more = waiting.len().saturating_sub(4);
        let mut card = ui::floating_surface()
            .flex()
            .flex_col()
            .id("topic-hover-card")
            .occlude()
            .on_mouse_down(MouseButton::Left, |_, _, cx| cx.stop_propagation())
            .w(px(320.))
            .p(px(6.))
            .gap(px(2.))
            .rounded(px(10.))
            .on_hover(cx.listener(move |s, hovered: &bool, _, cx| {
                s.topic_card.inside = *hovered;
                s.hover_topic_card(id, *hovered, cx)
            }));
        let label = |text: String| {
            div()
                .px(px(10.))
                .pt(px(6.))
                .pb(px(4.))
                .text_size(px(11.))
                .font_weight(FontWeight::MEDIUM)
                .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                .child(text)
        };
        let row = |key: String, page: Page| {
            ui::row()
                .id(SharedString::from(key))
                .h(px(30.))
                .gap(px(8.))
                .px(px(10.))
                .rounded(px(6.))
                .text_size(px(12.5))
                .cursor_pointer()
                .hover(|s| s.bg(ui::ink(0x0a)))
                .on_click(cx.listener(move |s, _, w, cx| {
                    cx.stop_propagation();
                    s.dismiss_topic_card(cx);
                    s.go(page.clone(), w, cx)
                }))
        };
        // What the agent is doing, alive.
        if let Some(doing) = working {
            card = card.child(label("Working on".into())).child(
                row(
                    "topic-card-working".into(),
                    Page::Topic(id, Tab::Chat, None),
                )
                .child(
                    div()
                        .flex_none()
                        .w(px(14.))
                        .flex()
                        .justify_center()
                        .child(self.sidebar_activity.clone()),
                )
                .child(div().flex_1().min_w_0().truncate().child(doing)),
            );
        }
        // What waits on the person: the item, and the one word for what it needs.
        if !waiting.is_empty() {
            card = card.child(label(format!("Needs you · {}", waiting.len())));
            for (i, a) in waiting.into_iter().take(4).enumerate() {
                card = card.child(
                    row(format!("topic-card-need-{i}"), a.page)
                        .child(
                            div()
                                .flex_none()
                                .w(px(14.))
                                .flex()
                                .justify_center()
                                .child(div().size(px(6.)).rounded_full().bg(rgb(UNREAD))),
                        )
                        .child(div().flex_1().min_w_0().truncate().child(a.title))
                        .child(
                            div()
                                .flex_none()
                                .text_size(px(11.5))
                                .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                                .child(a.kind),
                        ),
                );
            }
            if more > 0 {
                card = card.child(
                    row("topic-card-more".into(), Page::Topic(id, Tab::Needs, None)).child(
                        div()
                            .pl(px(22.))
                            .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                            .child(format!("{more} more")),
                    ),
                );
            }
        }
        Some(
            deferred(
                div()
                    .absolute()
                    .left(relative(1.))
                    .top_0()
                    .pl(px(6.))
                    .child(anchored().snap_to_window().child(card)),
            )
            .into_any_element(),
        )
    }
}

/// Which topic's card is showing, and the hover that leads to it.
#[derive(Default)]
pub(super) struct TopicCard {
    pub hover: Option<Card>,
    pub open: Option<Card>,
    pub inside: bool,
    pub epoch: u64,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub(super) enum Card {
    Topic(TopicId),
    Needs,
}

impl Desktop {
    pub(super) fn needs_button(&self, cx: &mut Context<Self>) -> Stateful<Div> {
        use meep_shell::titlebar;
        let n = self.needs_count();
        let here = self.page == Page::Needs && self.sheet != Some(Sheet::New);
        let label = match n {
            0 => "Needs you".to_owned(),
            n => format!("Needs you, {n} waiting"),
        };
        div()
            .id("needs-you-slot")
            .absolute()
            .top(px(meep_shell::TRAFFIC_LIGHT_CENTER - titlebar::BUTTON / 2.))
            .left(px(titlebar::TOGGLE_LEFT + titlebar::BUTTON + 4.))
            .cursor_pointer()
            .on_hover(cx.listener(move |s, hovered: &bool, _, cx| {
                s.hover_card(Card::Needs, *hovered && n > 0, cx)
            }))
            .on_click(cx.listener(|s, _, w, cx| {
                s.dismiss_topic_card(cx);
                s.go(Page::Needs, w, cx)
            }))
            .child(
                titlebar::button("needs-you", Glyph::Inbox, label)
                    .when(here, |b| b.bg(ui::ink(0x10)))
                    .when(n == 0, |b| b.tooltip("Needs you")),
            )
            .when(n > 0, |slot| {
                slot.child(
                    div()
                        .absolute()
                        .top(px(-3.))
                        .left(px(titlebar::BUTTON - 11.))
                        .h(px(15.))
                        .min_w(px(15.))
                        .px(px(4.))
                        .rounded_full()
                        .flex()
                        .items_center()
                        .justify_center()
                        .bg(rgb(ui::theme::get(10)))
                        .text_color(rgb(ui::theme::get(13)))
                        .text_size(px(10.))
                        .font_weight(FontWeight::SEMIBOLD)
                        .child(if n > 99 {
                            "99+".to_owned()
                        } else {
                            n.to_string()
                        }),
                )
            })
            .children(self.needs_card(cx))
    }

    fn needs_card(&self, cx: &mut Context<Self>) -> Option<AnyElement> {
        if self.topic_card.open != Some(Card::Needs) {
            return None;
        }
        const SHOWN: usize = 8;
        let mut card = ui::floating_surface()
            .flex()
            .flex_col()
            .id("needs-hover-card")
            .occlude()
            .on_mouse_down(MouseButton::Left, |_, _, cx| cx.stop_propagation())
            .w(px(340.))
            .p(px(6.))
            .gap(px(2.))
            .rounded(px(10.))
            .on_hover(cx.listener(|s, hovered: &bool, _, cx| {
                s.topic_card.inside = *hovered;
                s.hover_card(Card::Needs, *hovered, cx)
            }));
        let label = |icon: Option<&TopicIcon>, text: String| {
            ui::row()
                .gap(px(6.))
                .px(px(10.))
                .pt(px(8.))
                .pb(px(4.))
                .text_size(px(11.))
                .font_weight(FontWeight::MEDIUM)
                .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                .children(icon.map(|i| super::topic_icon::small_sidebar_tile(i, 14.)))
                .child(div().min_w_0().truncate().child(text))
        };
        let row = |key: String,
                   glyph: Glyph,
                   tone: u32,
                   title: String,
                   kind: &'static str,
                   page: Page| {
            ui::row()
                .id(SharedString::from(key))
                .h(px(30.))
                .gap(px(8.))
                .px(px(10.))
                .rounded(px(6.))
                .text_size(px(12.5))
                .cursor_pointer()
                .hover(|s| s.bg(ui::ink(0x0a)))
                .child(
                    meep_ui::gpui_kit::component::Icon::new(glyph)
                        .size(px(13.))
                        .text_color(rgb(tone)),
                )
                .child(div().flex_1().min_w_0().truncate().child(title))
                .child(
                    div()
                        .flex_none()
                        .text_size(px(11.5))
                        .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                        .child(kind),
                )
                .on_click(cx.listener(move |s, _, w, cx| {
                    cx.stop_propagation();
                    s.dismiss_topic_card(cx);
                    s.go(page.clone(), w, cx)
                }))
        };
        let mut shown = 0;
        let mut total = 0;
        let problems: Vec<&String> = self
            .needs
            .iter()
            .filter_map(|n| match n {
                NeedsYouItem::Problem { title, .. } => Some(title),
                _ => None,
            })
            .collect();
        if !problems.is_empty() {
            card = card.child(label(None, "Connections".into()));
            let (glyph, tone, kind) = pages::attention_glyph("Problem");
            for (i, title) in problems.into_iter().enumerate() {
                total += 1;
                if shown < SHOWN {
                    shown += 1;
                    card = card.child(row(
                        format!("needs-card-problem-{i}"),
                        glyph,
                        tone,
                        title.clone(),
                        kind,
                        Page::Needs,
                    ));
                }
            }
        }
        let rest: Vec<NeedsYouItem> = self
            .needs
            .iter()
            .filter(|n| !matches!(n, NeedsYouItem::Problem { .. }))
            .cloned()
            .collect();
        for state in &self.states {
            let groups = pages::attention_groups(&rest, state);
            if groups.is_empty() {
                continue;
            }
            total += groups.len();
            if shown >= SHOWN {
                continue;
            }
            let icon = state.topic.display_icon();
            card = card.child(label(Some(&icon), state.topic.name.clone()));
            for (i, g) in groups.into_iter().enumerate() {
                if shown >= SHOWN {
                    break;
                }
                shown += 1;
                let a = g.latest;
                let (glyph, tone, kind) = pages::attention_glyph(a.kind);
                card = card.child(row(
                    format!("needs-card-{}-{i}", state.topic.id),
                    glyph,
                    tone,
                    a.title,
                    kind,
                    a.page,
                ));
            }
        }
        if total > shown {
            card = card.child(
                ui::row()
                    .id("needs-card-more")
                    .h(px(30.))
                    .px(px(10.))
                    .pl(px(31.))
                    .rounded(px(6.))
                    .text_size(px(12.5))
                    .cursor_pointer()
                    .hover(|s| s.bg(ui::ink(0x0a)))
                    .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                    .child(format!("{} more", total - shown))
                    .on_click(cx.listener(|s, _, w, cx| {
                        cx.stop_propagation();
                        s.dismiss_topic_card(cx);
                        s.go(Page::Needs, w, cx)
                    })),
            );
        }
        Some(
            deferred(
                div()
                    .absolute()
                    .top(relative(1.))
                    .left_0()
                    .pt(px(6.))
                    .child(anchored().snap_to_window().child(card)),
            )
            .into_any_element(),
        )
    }
}
