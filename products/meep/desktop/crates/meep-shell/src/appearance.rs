//! Main-window appearance, shared with the native host.
use gpui_kit::component::{Theme, ThemeMode};
use gpui_kit::*;
use meep_ui::components as ui;
/// The native palette corresponding to the operating system's appearance.
pub fn system_palette(appearance: WindowAppearance) -> [u32; 14] {
    use meep_ui::design::{GRAPHITE, LIGHT};
    match appearance {
        WindowAppearance::Dark | WindowAppearance::VibrantDark => GRAPHITE,
        _ => LIGHT,
    }
}

/// Update semantic colors and toolkit controls together, preserving host typography and spacing.
pub fn set_palette(palette: [u32; 14], cx: &mut App) {
    let mut tokens = meep_ui::design::current();
    tokens.palette = palette;
    meep_ui::design::set(tokens);
    apply_theme(cx);
}

/// Apply the active Meep palette to native toolkit widgets.
pub fn apply_theme(cx: &mut App) {
    let palette = meep_ui::design::current().palette;
    let dark = ((palette[3] >> 16) & 255) + ((palette[3] >> 8) & 255) + (palette[3] & 255) < 384;
    Theme::change(
        if dark {
            ThemeMode::Dark
        } else {
            ThemeMode::Light
        },
        None,
        cx,
    );
    Theme::update(cx, |theme| {
        theme.motion = ui::motion::tokens(ui::motion::InputOrigin::Pointer);
        theme.focus_ring = true;
        let c = |i: usize| gpui_kit::rgb(palette[i]).into();
        theme.font_size = px(meep_ui::design::current().body);
        theme.colors.primary = c(10);
        theme.colors.primary_hover = c(10);
        theme.colors.primary_active = c(10);
        theme.colors.primary_foreground = c(13);
        theme.colors.button_primary = c(10);
        theme.colors.button_primary_hover = c(10);
        theme.colors.button_primary_active = c(10);
        theme.colors.button_primary_foreground = c(13);
        theme.colors.background = c(3);
        theme.colors.foreground = c(0);
        theme.colors.muted = c(4);
        theme.colors.muted_foreground = c(1);
        theme.colors.accent = c(7);
        theme.colors.accent_foreground = c(0);
        theme.colors.button = c(3);
        theme.colors.button_hover = c(4);
        theme.colors.button_active = c(7);
        theme.colors.button_foreground = c(0);
        theme.colors.border = c(5);
        theme.colors.input = c(5);
        // A focus ring that says "here" without shouting: the ink at low
        // strength, visible on every palette.
        // The framework draws the ring at half alpha whatever we pass, so
        // the softness comes from the colour itself: ink mixed into paper.
        theme.colors.ring = {
            let (a, b) = (palette[0], palette[3]);
            let mix = |shift: u32| {
                let (x, y) = (((a >> shift) & 255) as f32, ((b >> shift) & 255) as f32);
                ((y + (x - y) * 0.32).round() as u32) << shift
            };
            gpui_kit::rgb(mix(16) | mix(8) | mix(0)).into()
        };
        theme.colors.caret = c(0);
        // Text selection everywhere matches the block editor's: the accent
        // at low strength. The selected-row fill (7) is nearly the page
        // colour, so a highlight in it could not be seen.
        theme.colors.selection = c(10).opacity(if dark { 0.42 } else { 0.26 });
        theme.colors.secondary = c(4);
        theme.colors.secondary_foreground = c(0);
        theme.colors.secondary_hover = c(7);
        theme.colors.secondary_active = c(7);
        theme.colors.danger = c(8);
        theme.colors.danger_hover = c(8);
        theme.colors.danger_active = c(8);
        theme.colors.button_danger = c(8);
        theme.colors.button_danger_hover = c(8);
        theme.colors.button_danger_active = c(8);
        theme.colors.danger_foreground = gpui_kit::rgb(0xffffff).into();
        theme.colors.button_danger_foreground = gpui_kit::rgb(0xffffff).into();
        theme.colors.popover = c(3);
        theme.colors.popover_foreground = c(0);
        // An off switch is ink at low strength, so it reads on a page and
        // on a settings group's fill alike, in light and dark themes.
        theme.colors.switch = c(0).opacity(0.3);
        // Dialogs and sheets share the settings groups' generous corners.
        theme.radius_lg = px(14.);
    });
}

/// Standard settings scroll surface. Callers pass the available pane width, including its insets.
pub fn settings_body(id: &'static str, width: Pixels, content: Div) -> AnyElement {
    use crate::settings;
    div()
        .id(id)
        .flex_1()
        .min_h_0()
        .w_full()
        .overflow_y_scroll()
        .child(
            ui::row()
                .items_start()
                .justify_center()
                .w_full()
                .px(px(if width < px(500.) {
                    16.
                } else {
                    settings::PAGE_X
                }))
                .py(px(settings::PAGE_TOP))
                .child(content.w_full().max_w(px(settings::MEASURE))),
        )
        .into_any_element()
}

/// Resolve an optional palette name against the window's system appearance.
pub fn resolve(scheme: Option<&str>, appearance: WindowAppearance) -> [u32; 14] {
    meep_ui::palettes::PRESETS
        .iter()
        .find(|p| Some(p.name) == scheme)
        .map_or_else(|| system_palette(appearance), |p| p.palette)
}

/// View's palette gallery. The host chooses how an appearance change is persisted.
pub fn picker<V: 'static>(
    scheme: Option<&str>,
    saving: bool,
    width: Pixels,
    select: fn(&mut V, Option<&'static str>, &mut Window, &mut Context<V>),
    w: &Window,
    cx: &mut Context<V>,
) -> AnyElement {
    use crate::settings;
    use gpui_kit::{
        assets::IconName as Glyph,
        component::{
            Disableable, Icon,
            button::{Button, ButtonCustomVariant, ButtonVariants},
        },
        prelude::FluentBuilder,
    };
    let palette = resolve(scheme, w.appearance());
    let system = if scheme.is_none() {
        // Name the palette the system resolved to, so the checked card and
        // the caption agree.
        let current = meep_ui::palettes::PRESETS
            .iter()
            .find(|preset| preset.palette == palette)
            .map(|preset| preset.name);
        ui::caption(match current {
            Some(name) => format!("{name} · following system"),
            None => "Following system".to_owned(),
        })
        .into_any_element()
    } else {
        settings::pill("follow-system", "Use system", cx)
            .disabled(saving)
            .on_click(cx.listener(move |v, _, w, cx| select(v, None, w, cx)))
            .into_any_element()
    };
    let header = settings::header(
        "Appearance",
        "Choose the colors used throughout your workspace.",
        None,
    );
    let mut grid = div()
        .grid()
        .w_full()
        .grid_cols(if width < px(500.) { 2 } else { 3 })
        .gap(px(10.));
    for preset in &meep_ui::palettes::PRESETS {
        let active = preset.palette == palette;
        let name = preset.name;
        let card = Button::new(name)
            .w_full()
            .h(px(124.))
            .p(px(6.))
            .rounded(px(10.))
            .custom(
                ButtonCustomVariant::new(cx)
                    .color(rgb(ui::theme::get(3)).into())
                    .hover(rgb(ui::theme::get(4)).into())
                    .active(rgb(ui::theme::get(4)).into()),
            )
            .border_1()
            .border_color(rgb(ui::theme::get(if active { 10 } else { 5 })))
            .accessibility_label(format!("Use {name} theme"))
            .toggled(active)
            .disabled(saving)
            .child(
                ui::column()
                    .size_full()
                    .gap(px(8.))
                    .child(meep_ui::appearance::thumbnail(preset.palette))
                    .child(
                        ui::row()
                            .w_full()
                            .gap(px(8.))
                            .px(px(4.))
                            .child(
                                ui::column()
                                    .min_w_0()
                                    .flex_1()
                                    .items_start()
                                    .gap(px(1.))
                                    .child(
                                        div()
                                            .text_size(px(ui::BODY))
                                            .font_weight(FontWeight::MEDIUM)
                                            .child(name),
                                    )
                                    .child(
                                        ui::caption(preset.detail).text_size(px(11.)).truncate(),
                                    ),
                            )
                            .when(active, |el| {
                                el.child(
                                    div()
                                        .size(px(16.))
                                        .flex_none()
                                        .rounded_full()
                                        .flex()
                                        .items_center()
                                        .justify_center()
                                        .bg(rgb(ui::theme::get(10)))
                                        .child(
                                            Icon::new(Glyph::Check)
                                                .size(px(10.))
                                                .text_color(rgb(ui::theme::get(13))),
                                        ),
                                )
                            }),
                    ),
            )
            .on_click(cx.listener(move |v, _, w, cx| select(v, Some(name), w, cx)));
        grid = grid.child(
            div()
                .min_w_0()
                .rounded(px(10.))
                .bg(rgb(ui::theme::get(3)))
                .when(active, |el| {
                    el.shadow(vec![BoxShadow {
                        color: rgb(ui::theme::get(10)).into(),
                        offset: Default::default(),
                        blur_radius: px(0.),
                        spread_radius: px(1.),
                        inset: false,
                    }])
                })
                .child(card),
        );
    }
    let body = ui::column()
        .gap_0()
        .child(header)
        .child(settings::section("Theme", "", Some(system), true))
        .child(grid)
        .child(settings::section("Preview", "", None, false))
        .child(meep_ui::appearance::preview(palette, width >= px(600.)));
    settings_body("appearance-scroll", width, body)
}
