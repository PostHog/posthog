use super::*;
use meep_shell::settings::{self as set, group, header, section};
use meep_ui::gpui_kit::component::Icon;

fn kind_label(watch: &Watch) -> &str {
    match watch.kind.as_str() {
        "topic" => "Topic",
        "flag" => "Feature flag",
        "insight" => "Insight",
        "event" => "Event",
        "channel" => "Channel",
        "repository" | "repo" => "Repository",
        "service" => "Service",
        other => other,
    }
}

fn kind_glyph(watch: &Watch) -> Glyph {
    match watch.kind.as_str() {
        "topic" => Glyph::AtSign,
        "flag" => Glyph::Flag,
        "insight" | "event" => Glyph::ChartColumn,
        "channel" => Glyph::Hash,
        _ => Glyph::Plug,
    }
}

fn source_tile(watch: &Watch) -> Div {
    if watch.kind == "service" {
        set::logo_tile().child(meep_render::brands::logo(&watch.label, 16.))
    } else {
        set::tile().child(ui::nav::glyph(kind_glyph(watch), false))
    }
}

impl Desktop {
    pub(super) fn linked_section(&self, topic: &Topic, cx: &Context<Self>) -> Div {
        let id = topic.id;
        let sources: Vec<(usize, &Watch)> = topic
            .context_sources
            .iter()
            .enumerate()
            .filter(|(_, w)| !(w.connection == "github" && w.kind == "repository"))
            .collect();
        let add = control("edit-watch", "Add source", false, cx, move |s, w, cx| {
            s.ask_in_chat("Find and add this PostHog object: ", w, cx)
        })
        .into_any_element();
        let rows: Vec<AnyElement> = if sources.is_empty() {
            vec![
                set::empty(
                    "No linked sources",
                    "Link a dashboard, insight, flag or channel so the agent can read it.",
                )
                .into_any_element(),
            ]
        } else {
            sources
                .into_iter()
                .map(|(i, watch)| {
                    let source = watch.id;
                    let key = watch.key.clone();
                    let hover = SharedString::from(format!("watch-{i}"));
                    ui::row()
                        .id(SharedString::from(format!("context-source-{i}")))
                        .group(hover.clone())
                        .role(Role::Button)
                        .aria_label(SharedString::from(watch.label.clone()))
                        .w_full()
                        .min_h(px(60.))
                        .px(px(set::ROW_X))
                        .py(px(10.))
                        .gap(px(12.))
                        .cursor_pointer()
                        .hover(|s| s.bg(ui::ink(0x05)))
                        .active(|s| s.bg(ui::ink(0x0a)))
                        .on_click(cx.listener(move |s, _, w, cx| {
                            s.go(
                                Page::Topic(id, Tab::Linked, Some(Detail::Linked(key.clone()))),
                                w,
                                cx,
                            )
                        }))
                        .child(source_tile(watch))
                        .child(set::copy(watch.label.clone(), kind_label(watch).to_owned()))
                        .child(
                            div()
                                .flex_none()
                                .opacity(0.)
                                .group_hover(hover, |s| s.opacity(1.))
                                .child(
                                    ui::icon_button(
                                        SharedString::from(format!("unwatch-{i}")),
                                        Glyph::X,
                                        "Remove source",
                                    )
                                    .on_click(cx.listener(
                                        move |s, _, _, cx| {
                                            cx.stop_propagation();
                                            s.issue(id, Command::RemoveContextSource { source });
                                            cx.notify()
                                        },
                                    )),
                                ),
                        )
                        .child(
                            Icon::new(Glyph::ChevronRight)
                                .size(px(14.))
                                .text_color(rgb(ui::theme::get(2))),
                        )
                        .into_any_element()
                })
                .collect()
        };
        ui::column()
            .child(header(
                "Linked",
                "What this topic reads for context. Topic chat reads these and never changes them.",
                None,
            ))
            .child(section("Sources", "", Some(add), true))
            .child(group(rows))
            .when(self.identity.is_some(), |col| {
                col.child(self.github_section(topic, cx))
            })
    }
}
