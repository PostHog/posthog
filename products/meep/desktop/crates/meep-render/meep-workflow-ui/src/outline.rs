use super::*;

const BAR: f32 = 112.;
const TIME: f32 = 64.;
const INDENT: f32 = 30.;

impl Outline {
    fn status_mark(status: Status) -> AnyElement {
        let (bg, glyph) = match status {
            Status::Ok => (
                ui::theme::named("positive").unwrap_or(0x3f7d57),
                Some(Glyph::Check),
            ),
            Status::Failed => (
                ui::theme::named("danger").unwrap_or(0xb3403a),
                Some(Glyph::X),
            ),
            Status::Recovered => (
                ui::theme::named("orange").unwrap_or(0xa9682a),
                Some(Glyph::RefreshCw),
            ),
            Status::Skipped => {
                return div()
                    .size(px(14.))
                    .m(px(1.))
                    .rounded_full()
                    .border_1()
                    .border_color(ui::ink(0x38))
                    .into_any_element();
            }
            Status::Running => {
                // A ring with a breathing centre: in progress, not stuck.
                let accent = ui::theme::get(10);
                return div()
                    .size(px(16.))
                    .flex_none()
                    .rounded_full()
                    .border_2()
                    .border_color(rgb(accent))
                    .flex()
                    .items_center()
                    .justify_center()
                    .child(
                        div()
                            .size(px(6.))
                            .rounded_full()
                            .bg(rgb(accent))
                            .with_animation(
                                "running-pulse",
                                Animation::new(std::time::Duration::from_millis(1100))
                                    .repeat()
                                    .with_easing(ease_in_out),
                                |dot, t| dot.opacity(0.25 + 0.75 * (1. - (2. * t - 1.).abs())),
                            ),
                    )
                    .into_any_element();
            }
            Status::Unknown => {
                return div()
                    .size(px(16.))
                    .flex()
                    .items_center()
                    .justify_center()
                    .child(div().size(px(6.)).rounded_full().bg(ui::ink(0x30)))
                    .into_any_element();
            }
        };
        div()
            .size(px(16.))
            .flex_none()
            .rounded_full()
            .bg(rgb(bg))
            .flex()
            .items_center()
            .justify_center()
            .when_some(glyph, |el, g| {
                el.child(Icon::new(g).size(px(10.)).text_color(rgb(0xffffff)))
            })
            .into_any_element()
    }

    fn tile(&self, tile: &Tile, dim: bool) -> AnyElement {
        match tile {
            Tile::Brand(name, kind) => div()
                .size(px(24.))
                .flex()
                .items_center()
                .justify_center()
                .flex_none()
                .when(dim, |el| el.opacity(0.5))
                .child(self.source_icon.map_or_else(
                    || {
                        Icon::new(if *kind == "cli" {
                            Glyph::Terminal
                        } else {
                            Glyph::Plug
                        })
                        .size(px(16.))
                        .into_any_element()
                    },
                    |icon| icon(name, kind, 24.),
                ))
                .into_any_element(),
            Tile::Glyph(glyph) => div()
                .size(px(24.))
                .flex_none()
                .rounded(px(7.))
                .bg(rgb(ui::theme::color(PAPER)))
                .border_1()
                .border_color(ui::ink(0x12))
                .flex()
                .items_center()
                .justify_center()
                .when(dim, |el| el.opacity(0.5))
                .child(
                    Icon::new(*glyph)
                        .size(px(13.))
                        .text_color(rgb(ui::theme::get(1))),
                )
                .into_any_element(),
        }
    }

    /// Where in the run a step spent its time, on one shared track.
    /// Time since the latest live snapshot, so running clocks keep moving.
    fn since_snapshot(&self) -> f64 {
        if self.model.live {
            self.received.elapsed().as_secs_f64() * 1000.
        } else {
            0.
        }
    }
    fn bar(&self, item: &Row, emphasis: bool, span: Option<(f64, f64)>) -> Div {
        let extra = self.since_snapshot();
        let total = (self.model.total + extra).max(1.);
        let (start, mut length) = match (item.looped, span) {
            (true, Some(span)) => span,
            _ => (item.start, item.elapsed.unwrap_or(0.)),
        };
        if item.status == Status::Running {
            length += extra;
        }
        let left = (start / total).clamp(0., 1.) as f32 * BAR;
        let width = ((length / total).clamp(0., 1.) as f32 * BAR)
            .max(2.)
            .min(BAR - left);
        // A span on the run's timeline, with no empty track behind it.
        let running = item.status == Status::Running;
        let fill = div()
            .absolute()
            .top_0()
            .left(px(left))
            .w(px(width))
            .h(px(4.))
            .rounded_full()
            .bg(if item.status == Status::Failed {
                rgb(ui::theme::named("danger").unwrap_or(0xb3403a))
            } else if running {
                rgb(ui::theme::get(10))
            } else if emphasis {
                rgb(ui::theme::color(INK))
            } else if item.looped {
                ui::ink(0x22)
            } else {
                ui::ink(0x38)
            });
        let fill = if running {
            fill.with_animation(
                SharedString::from(format!("running-bar-{}", item.key)),
                Animation::new(std::time::Duration::from_millis(1100))
                    .repeat()
                    .with_easing(ease_in_out),
                |bar, t| bar.opacity(0.35 + 0.65 * (1. - (2. * t - 1.).abs())),
            )
            .into_any_element()
        } else {
            fill.into_any_element()
        };
        div()
            .w(px(BAR))
            .h(px(4.))
            .flex_none()
            .relative()
            // Spans too short to see are left to the time beside them.
            .when(
                item.elapsed.is_some()
                    && item.status != Status::Skipped
                    && (running || (length / total) as f32 * BAR >= 8.),
                |el| el.child(fill),
            )
    }

    fn time_label(&self, item: &Row, emphasis: bool) -> Div {
        let traced = self.model.traced;
        let running = item.status == Status::Running;
        let value = match (item.status, item.elapsed) {
            (Status::Skipped, _) => "—".to_owned(),
            (Status::Running, Some(ms)) => time(ms + self.since_snapshot()),
            (_, Some(ms)) if item.looped && item.started > 0 => {
                format!("avg {}", time(ms / item.started as f64))
            }
            (_, Some(ms)) => time(ms),
            _ if traced => "—".into(),
            _ => String::new(),
        };
        text(value)
            .w(px(TIME))
            .flex_none()
            .flex()
            .justify_end()
            .text_size(px(12.))
            .when(emphasis || running, |el| {
                el.font_weight(FontWeight::SEMIBOLD)
            })
            .text_color(if running {
                rgb(ui::theme::get(10))
            } else if emphasis {
                rgb(ui::theme::color(INK))
            } else {
                rgb(ui::theme::get(1))
            })
    }

    fn row(
        &self,
        item: &Row,
        emphasis: bool,
        span: Option<(f64, f64)>,
        bars: bool,
        cx: &mut Context<Self>,
    ) -> AnyElement {
        let expanded = self.expanded.as_deref() == Some(item.key.as_str());
        let dim = item.status == Status::Skipped;
        let key = item.key.clone();
        let tag = |value: String| {
            text(value)
                .text_size(px(12.))
                .text_color(rgb(ui::theme::get(2)))
        };
        let mut meta = row().gap(px(6.)).min_w_0().flex_wrap();
        for (i, m) in item.meta.iter().enumerate() {
            if i > 0 {
                meta = meta.child(tag("·".into()));
            }
            meta = meta.child(tag(m.clone()));
        }
        if item.status == Status::Skipped {
            if !item.meta.is_empty() {
                meta = meta.child(tag("·".into()));
            }
            meta = meta.child(tag(if item.guard.is_some() {
                "condition not met".into()
            } else {
                "not run".into()
            }));
        }
        if item.recovery.is_some() {
            meta = meta.child(
                div()
                    .size(px(16.))
                    .rounded(px(5.))
                    .bg(gpui_kit::rgba(
                        (ui::theme::named("positive").unwrap_or(0x3f7d57) << 8) | 0x1e,
                    ))
                    .flex()
                    .items_center()
                    .justify_center()
                    .child(
                        Icon::new(Glyph::RefreshCw)
                            .size(px(9.))
                            .text_color(rgb(ui::theme::named("positive").unwrap_or(0x3f7d57))),
                    ),
            );
        }
        let has_meta =
            !item.meta.is_empty() || item.status == Status::Skipped || item.recovery.is_some();
        let line = div()
            .id(SharedString::from(format!(
                "workflow-navigate-{}",
                item.key
            )))
            .role(Role::Button)
            .aria_label(SharedString::from(item.title.clone()))
            .flex()
            .items_center()
            .w_full()
            .min_h(px(if has_meta { 52. } else { 44. }))
            .px(px(12.))
            .py(px(7.))
            .gap(px(12.))
            .rounded(px(10.))
            .cursor_pointer()
            .when(expanded, |el| el.bg(ui::ink(0x09)))
            .when(!expanded, |el| el.hover(|s| s.bg(ui::ink(0x05))))
            .child(Self::status_mark(item.status))
            .child(self.tile(&item.tile, dim))
            .child(
                col()
                    .flex_1()
                    .min_w_0()
                    .gap(px(1.))
                    .child(
                        text(item.title.clone())
                            .truncate()
                            .text_size(px(13.))
                            .line_height(px(18.))
                            .font_weight(if item.children.is_empty() {
                                FontWeight::NORMAL
                            } else {
                                FontWeight::MEDIUM
                            })
                            .text_color(if dim {
                                rgb(ui::theme::get(1))
                            } else {
                                rgb(ui::theme::color(INK))
                            }),
                    )
                    .when(has_meta, |el| el.child(meta)),
            )
            .when(bars, |el| el.child(self.bar(item, emphasis, span)))
            .child(self.time_label(item, emphasis))
            .on_click(cx.listener(move |this, _, _, cx| {
                this.expanded = if this.expanded.as_deref() == Some(key.as_str()) {
                    None
                } else {
                    Some(key.clone())
                };
                cx.notify();
            }));
        col()
            .w_full()
            .child(line)
            .when(expanded, |el| el.child(self.details(item, cx)))
            .into_any_element()
    }

    /// What a step did, under its item.
    fn details(&self, item: &Row, cx: &mut Context<Self>) -> Div {
        let heading = |value: &'static str| {
            text(value)
                .text_size(px(11.5))
                .font_weight(FontWeight::MEDIUM)
                .text_color(rgb(ui::theme::get(2)))
        };
        let body = |value: String| {
            text(value)
                .text_size(px(12.5))
                .line_height(px(18.))
                .text_color(rgb(ui::theme::color(INK)))
        };
        let fact = |title: &'static str, content: Div| {
            col()
                .min_w(px(150.))
                .flex_1()
                .gap(px(4.))
                .child(heading(title))
                .child(content)
        };
        let mut facts = row().w_full().items_start().gap(px(24.)).flex_wrap();
        if item.status == Status::Failed
            && let Some(error) = item.error.as_ref().or(self.error.as_ref())
        {
            facts = facts.child(
                fact(
                    "Error",
                    body(error.clone())
                        .text_color(rgb(ui::theme::named("danger").unwrap_or(0xb3403a))),
                )
                .min_w(px(220.)),
            );
        }
        if !item.calls.is_empty() {
            let mut calls = col().gap(px(3.));
            for call in &item.calls {
                calls = calls.child(
                    row()
                        .gap(px(10.))
                        .child(
                            row()
                                .flex_1()
                                .min_w_0()
                                .gap(px(5.))
                                .child(body(call.title.clone()).truncate())
                                .when(call.started > 1, |el| {
                                    el.child(
                                        text(format!("×{}", call.started))
                                            .text_size(px(11.5))
                                            .text_color(rgb(ui::theme::get(2))),
                                    )
                                }),
                        )
                        .when(self.model.traced, |el| {
                            el.child(
                                text(if call.started == 0 {
                                    "not run".into()
                                } else {
                                    time(call.elapsed)
                                })
                                .flex_none()
                                .text_size(px(12.))
                                .text_color(rgb(ui::theme::get(1))),
                            )
                        }),
                );
            }
            let added = item.calls.iter().filter(|c| c.started > 1).count() > 0;
            facts = facts.child(
                fact(
                    "Steps",
                    calls.when(added, |el| {
                        el.child(
                            text("Times add up across calls; they overlap.")
                                .text_size(px(11.))
                                .text_color(rgb(ui::theme::get(2))),
                        )
                    }),
                )
                .min_w(px(240.)),
            );
        } else if let Some(uses) = &item.uses {
            facts = facts.child(fact("Uses", body(uses.clone())));
        }
        if item.children.is_empty() && item.calls.is_empty() && self.model.traced {
            facts = facts.child(fact(
                "Ran",
                body(match (item.status, item.elapsed) {
                    (Status::Skipped, _) => "Not in the last run".into(),
                    (_, Some(ms)) if item.started > 1 => {
                        format!("{} times · {} across calls", item.started, time(ms))
                    }
                    (_, Some(ms)) => time(ms),
                    _ => "No timing recorded".into(),
                }),
            ));
        }
        if let Some(guard) = &item.guard {
            facts = facts.child(fact("Runs only when", body(guard.clone())));
        }
        if let Some(recovery) = &item.recovery {
            facts = facts.child(fact("If it fails", body(recovery.clone())));
        }
        if !item.data.is_empty() {
            facts = facts.child(fact(
                "Data steps",
                body(item.data.join(" · ")).text_color(rgb(ui::theme::get(1))),
            ));
        }
        let edit = item.edit.clone().filter(|_| self.on_edit.is_some());
        let callback = self.on_edit.clone();
        let indent = 12. + 16. + 12.;
        col()
            .ml(px(indent))
            .mr(px(4.))
            .mt(px(2.))
            .mb(px(8.))
            .p(px(14.))
            .gap(px(14.))
            .rounded(px(10.))
            .bg(ui::ink(0x05))
            .child(facts)
            .when_some(edit.zip(callback), |el, (step, callback)| {
                let target = if kind_of(&self.definition, &step) == Some("command") {
                    EditTarget::Script
                } else {
                    EditTarget::Step(step)
                };
                el.child(
                    row().child(
                        settings::pill("workflow-edit-step", "Edit Step", cx)
                            .icon(Icon::new(Glyph::Braces).size(px(12.)))
                            .on_click(move |_, window, cx| callback(target.clone(), window, cx)),
                    ),
                )
            })
    }

    /// The step that took most of the time, when one clearly did.
    fn slowest(rows: &[&Row], whole: f64) -> Option<String> {
        let mut timed: Vec<&&Row> = rows
            .iter()
            .filter(|r| r.elapsed.is_some() && !r.looped)
            .collect();
        timed.sort_by(|a, b| {
            b.elapsed
                .partial_cmp(&a.elapsed)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        let first = timed.first()?;
        let top = first.elapsed?;
        let second = timed.get(1).and_then(|r| r.elapsed).unwrap_or(0.);
        (whole >= 1000. && top >= whole * 0.5 && top >= second * 1.5).then(|| first.key.clone())
    }
}

impl Render for Outline {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let model = self.model.clone();
        let bars = window.viewport_size().width >= px(980.) && model.traced;
        let show_data = self.show_data;
        let visible = |r: &&Row| show_data || !r.data_row;
        let top: Vec<&Row> = model.rows.iter().filter(visible).collect();
        let slow_top = Self::slowest(&top, model.total);
        let failed = first_failed_key(&model.rows);
        self.failed_item.set(None);
        let mut items: Vec<AnyElement> = vec![];
        for row in &top {
            if failed.as_deref() == Some(row.key.as_str()) {
                self.failed_item.set(Some(items.len()));
            }
            items.push(self.row(
                row,
                slow_top.as_deref() == Some(row.key.as_str()),
                None,
                bars,
                cx,
            ));
            let children: Vec<&Row> = row.children.iter().filter(visible).collect();
            if children
                .iter()
                .any(|c| failed.as_deref() == Some(c.key.as_str()))
            {
                self.failed_item.set(Some(items.len()));
            }
            if !children.is_empty() {
                let span = Some((row.start, row.elapsed.unwrap_or(0.)));
                let slow = Self::slowest(&children, row.elapsed.unwrap_or(0.));
                let mut group = col()
                    .ml(px(INDENT - 8.))
                    .pl(px(8.))
                    .border_l_1()
                    .border_color(ui::ink(0x12))
                    .gap(px(2.));
                for child in children {
                    group = group.child(self.row(
                        child,
                        slow.as_deref() == Some(child.key.as_str()),
                        span,
                        bars,
                        cx,
                    ));
                }
                items.push(group.into_any_element());
            }
        }
        if model.rows.is_empty() {
            items.push(
                settings::empty("No steps", "This workflow doesn't do anything yet.")
                    .into_any_element(),
            );
        }
        let hidden = model.data_steps;
        let footer = (model.failure.is_some() || (hidden > 0 && !model.small())).then(|| {
            row()
                .w_full()
                .mt(px(10.))
                .pt(px(12.))
                .px(px(12.))
                .gap(px(16.))
                .when(model.failure.is_some(), |el| {
                    el.border_t_1().border_color(ui::ink(0x0e))
                })
                .child(row().flex_1().min_w_0().gap(px(8.)).when_some(
                    model.failure.clone(),
                    |el, failure| {
                        el.child(
                            Icon::new(Glyph::LifeBuoy)
                                .size(px(13.))
                                .text_color(rgb(ui::theme::get(2))),
                        )
                        .child(
                            text(if model.failure_ran {
                                format!("The run failed, so it will {failure}.")
                            } else {
                                format!("If the run fails, it will {failure}.")
                            })
                            .text_size(px(12.))
                            .line_height(px(17.))
                            .text_color(rgb(ui::theme::get(1))),
                        )
                    },
                ))
                .when(hidden > 0 && !model.small(), |el| {
                    el.child(
                        controls::quiet_button("workflow-show-data", cx)
                            .small()
                            .h(px(26.))
                            .px(px(10.))
                            .rounded(px(13.))
                            .text_size(px(12.))
                            .label(if show_data {
                                "Hide data steps".to_owned()
                            } else {
                                format!(
                                    "Show {hidden} data {}",
                                    if hidden == 1 { "step" } else { "steps" }
                                )
                            })
                            .on_click(cx.listener(|this, _, _, cx| {
                                this.show_data = !this.show_data;
                                cx.notify();
                            })),
                    )
                })
        });
        let steps = div()
            .id("workflow-outline")
            .size_full()
            .min_h_0()
            .overflow_y_scroll()
            .track_scroll(&self.scroll)
            .flex()
            .flex_col()
            .gap(px(2.))
            .pb(px(24.))
            .children(items)
            .children(footer);
        col()
            .size_full()
            .min_h_0()
            .when_some(event_label(&self.definition["trigger"]), |el, label| {
                el.child(text(label).px(px(12.)).py(px(6.)).text_size(px(13.)))
            })
            .child(steps)
    }
}
