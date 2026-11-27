use super::*;

#[derive(Clone, Copy, Default, PartialEq, Eq)]
pub(super) enum Scene {
    #[default]
    Opening,
    Reply,
    View,
    Error,
}

impl Host {
    pub(super) fn preview_states(&self, cx: &mut Context<Self>) -> AnyElement {
        let prompt = "Summarize this week’s activity.";
        let body = match self.preview {
            Scene::Opening | Scene::Error => self.opening_screen(cx),
            Scene::View => views::building(Some((prompt, &meep_wire::views::Stage::Starting)))
                .into_any_element(),
            Scene::Reply => ui::column()
                .size_full()
                .items_center()
                .justify_center()
                .child(
                    ui::column()
                        .w(px(390.))
                        .gap(px(18.))
                        .child(
                            ui::row().justify_end().child(
                                div()
                                    .rounded(px(12.))
                                    .bg(ui::ink(12))
                                    .px(px(12.))
                                    .py(px(7.))
                                    .child(prompt),
                            ),
                        )
                        .child(meep_shell::transcript::pending_reply()),
                )
                .into_any_element(),
        };
        let mut buttons = ui::row().justify_center().gap(px(6.)).py(px(12.));
        for (scene, label) in [
            (Scene::Opening, "Opening workspace"),
            (Scene::Reply, "Chat reply"),
            (Scene::View, "Building a view"),
            (Scene::Error, "Connection error"),
        ] {
            let button = if scene == self.preview {
                ui::primary_button(label, label)
            } else {
                ui::button(label, label)
            };
            buttons = buttons.child(button.on_click(cx.listener(move |s, _, _, cx| {
                s.preview = scene;
                s.error = (scene == Scene::Error).then(|| "Could not connect to PostHog.".into());
                cx.notify();
            })));
        }
        let dark = ui::theme::is_dark();
        buttons = buttons.child(
            ui::button(
                "preview-theme",
                if dark { "Light mode" } else { "Dark mode" },
            )
            .on_click(cx.listener(move |_, _, _, cx| {
                meep_shell::appearance::set_palette(
                    if dark {
                        meep_ui::design::LIGHT
                    } else {
                        meep_ui::design::GRAPHITE
                    },
                    cx,
                );
                cx.notify();
            })),
        );
        ui::page()
            .child(div().flex_1().min_h_0().child(body))
            .child(buttons)
            .into_any_element()
    }
}
