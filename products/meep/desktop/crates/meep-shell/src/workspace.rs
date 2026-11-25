//! View's window material, navigation and in-place Settings switch. The embedding
//! app supplies destinations, page content, and any persistence or service clients.
use super::*;
use gpui_kit::component::input::{self, InputEvent, InputState};

actions!(
    meep_workspace,
    [
        OpenSettings,
        Back,
        ToggleSidebar,
        CloseWindow,
        QuitApp,
        HideApp,
        HideOthers,
        ShowAll,
        Minimize,
        Zoom,
        FullScreen
    ]
);

/// Install application, editing and window menus for a native host.
pub fn install_menus(name: &'static str, cx: &mut App) {
    cx.bind_keys([
        KeyBinding::new("cmd-,", OpenSettings, Some("MeepWorkspace")),
        KeyBinding::new("escape", Back, Some("MeepWorkspace")),
        KeyBinding::new("ctrl-cmd-s", ToggleSidebar, Some("MeepWorkspace")),
        KeyBinding::new("cmd-w", CloseWindow, None),
        KeyBinding::new("cmd-q", QuitApp, None),
        KeyBinding::new("cmd-h", HideApp, None),
        KeyBinding::new("alt-cmd-h", HideOthers, None),
        KeyBinding::new("cmd-m", Minimize, None),
        KeyBinding::new("ctrl-cmd-f", FullScreen, None),
    ]);
    cx.set_menus([
        Menu::new(name).items([
            MenuItem::action("Settings…", OpenSettings),
            MenuItem::separator(),
            MenuItem::os_submenu("Services", SystemMenuType::Services),
            MenuItem::separator(),
            MenuItem::action(format!("Hide {name}"), HideApp),
            MenuItem::action("Hide Others", HideOthers),
            MenuItem::action("Show All", ShowAll),
            MenuItem::separator(),
            MenuItem::action(format!("Quit {name}"), QuitApp),
        ]),
        Menu::new("File").items([MenuItem::action("Close Window", CloseWindow)]),
        Menu::new("Edit").items([
            MenuItem::action("Undo", input::Undo),
            MenuItem::action("Redo", input::Redo),
            MenuItem::separator(),
            MenuItem::action("Cut", input::Cut),
            MenuItem::action("Copy", input::Copy),
            MenuItem::action("Paste", input::Paste),
            MenuItem::action("Select All", input::SelectAll),
        ]),
        Menu::new("View").items([MenuItem::action("Toggle Sidebar", ToggleSidebar)]),
        Menu::new("Window").items([
            MenuItem::action("Minimize", Minimize),
            MenuItem::action("Zoom", Zoom),
            MenuItem::action("Enter Full Screen", FullScreen),
        ]),
    ]);
    cx.on_action(|_: &QuitApp, cx| cx.quit());
    cx.on_action(|_: &HideApp, cx| cx.hide());
    cx.on_action(|_: &HideOthers, cx| cx.hide_other_apps());
    cx.on_action(|_: &ShowAll, cx| cx.unhide_other_apps());
}

/// Use this after host toolkit initialization. GPUI installs its Root *after*
/// building the child, so changing its paint inside the child constructor is too early.
pub fn open_window<V: Render>(
    options: WindowOptions,
    cx: &mut App,
    build: impl FnOnce(&mut Window, &mut App) -> Entity<V>,
) -> anyhow::Result<(AnyWindowHandle, Entity<V>)> {
    let (handle, view) = gpui_kit::open_window(
        WindowOptions {
            // The toolkit blur inserts an opaque backdrop below NSGlassEffectView.
            window_background: WindowBackgroundAppearance::Transparent,
            app_owns_titlebar_drag: true,
            titlebar: Some(TitlebarOptions {
                title: options.titlebar.and_then(|t| t.title),
                appears_transparent: true,
                traffic_light_position: Some(point(px(18.), px(20.))),
            }),
            ..options
        },
        cx,
        build,
    )?;
    handle.update(cx, |_, window, cx| {
        gpui_kit::base::Root::update(window, cx, |root, _, cx| {
            root.style()
                .refine(&StyleRefinement::default().bg(ui::ink(0)));
            cx.notify();
        });
    })?;
    Ok((handle, view))
}

/// A page and its sidebar representation.
pub struct Destination<P> {
    /// Host page opened by this destination.
    pub page: P,
    /// Sidebar label for this destination.
    pub title: SharedString,
    icon: DestinationIcon,
}

enum DestinationIcon {
    Glyph(Glyph),
    Tile {
        emoji: &'static str,
        color: &'static str,
    },
}

impl<P> Destination<P> {
    /// Create a destination represented by a toolkit glyph.
    pub fn new(page: P, title: impl Into<SharedString>, icon: Glyph) -> Self {
        Self {
            page,
            title: title.into(),
            icon: DestinationIcon::Glyph(icon),
        }
    }

    /// Create a destination represented by a colored emoji tile.
    pub fn tile(
        page: P,
        title: impl Into<SharedString>,
        emoji: &'static str,
        color: &'static str,
    ) -> Self {
        Self {
            page,
            title: title.into(),
            icon: DestinationIcon::Tile { emoji, color },
        }
    }
}

/// Page selection and sidebar state for a workspace window.
pub struct Navigation<P> {
    /// Selected application page.
    pub app_page: P,
    /// Selected settings page.
    pub settings_page: P,
    /// Whether the settings navigation is visible.
    pub in_settings: bool,
    standalone: bool,
    wide_collapsed: bool,
    compact_list: bool,
    focus: FocusHandle,
    search: Entity<InputState>,
}
impl<P: Copy> Navigation<P> {
    /// Initialize navigation, search and keyboard focus for a window.
    pub fn new<V: 'static>(
        app_page: P,
        settings_page: P,
        in_settings: bool,
        standalone: bool,
        w: &mut Window,
        cx: &mut Context<V>,
    ) -> Self {
        let focus = cx.focus_handle();
        if w.focused(cx).is_none() {
            focus.focus(w, cx);
        }
        let search = cx.new(|cx| InputState::new(w, cx).placeholder("Search…"));
        cx.subscribe(&search, |_, _, event: &InputEvent, cx| {
            if matches!(event, InputEvent::Change) {
                cx.notify();
            }
        })
        .detach();
        Self {
            app_page,
            settings_page,
            in_settings,
            standalone,
            wide_collapsed: false,
            compact_list: false,
            focus,
            search,
        }
    }
    /// Return the currently visible application or settings page.
    pub fn selected(&self) -> P {
        if self.in_settings {
            self.settings_page
        } else {
            self.app_page
        }
    }
    fn compact(&self, w: &Window) -> bool {
        self.standalone
            || f32::from(w.viewport_size().width)
                < meep_ui::design::current().sidebar + MIN_VIEW_WIDTH + 2. * GUTTER
    }
    /// Compute the width available for content with the current sidebar state.
    pub fn content_width(&self, w: &Window) -> Pixels {
        if self.compact(w) || self.wide_collapsed && !self.in_settings {
            w.viewport_size().width - px(2. * GUTTER)
        } else {
            w.viewport_size().width - px(meep_ui::design::current().sidebar + GUTTER)
        }
    }
}

/// Stores and renders each destination. `render_page` is called only for the visible page.
pub trait WorkspaceHost: Render + Sized {
    /// Host-owned destination identifier.
    type Page: Copy + Eq + 'static;
    /// Read this window's navigation state.
    fn navigation(&self) -> &Navigation<Self::Page>;
    /// Edit this window's navigation state.
    fn navigation_mut(&mut self) -> &mut Navigation<Self::Page>;
    /// List application or settings destinations in sidebar order.
    fn destinations(&self, settings: bool) -> Vec<Destination<Self::Page>>;
    /// Label for returning from Settings to the application.
    fn back_label(&self) -> &'static str;
    /// Render the selected destination inside the workspace.
    fn render_page(
        &mut self,
        page: Self::Page,
        w: &mut Window,
        cx: &mut Context<Self>,
    ) -> AnyElement;
    /// Handle a completed navigation change.
    fn navigated(&mut self, _w: &mut Window, _cx: &mut Context<Self>) {}
}

fn switch<H: WorkspaceHost>(host: &mut H, settings: bool, w: &mut Window, cx: &mut Context<H>) {
    let nav = host.navigation_mut();
    if nav.in_settings == settings {
        return;
    }
    nav.in_settings = settings;
    nav.compact_list = false;
    nav.search.update(cx, |s, cx| s.set_value("", w, cx));
    // The control which opened Settings can have left the dispatch tree.
    // This permanent focus handle keeps window and menu shortcuts routable.
    nav.focus.focus(w, cx);
    host.navigated(w, cx);
    cx.notify();
}

fn toggle<H: WorkspaceHost>(host: &mut H, w: &mut Window, cx: &mut Context<H>) {
    let nav = host.navigation_mut();
    if nav.compact(w) {
        nav.compact_list = !nav.compact_list;
    } else if !nav.in_settings {
        nav.wide_collapsed = !nav.wide_collapsed;
    }
    nav.focus.focus(w, cx);
    cx.notify();
}

fn rail<H: WorkspaceHost>(
    host: &H,
    settings: bool,
    items: &[Destination<H::Page>],
    w: &Window,
    cx: &mut Context<H>,
) -> Div {
    let nav = host.navigation();
    let selected = if settings {
        nav.settings_page
    } else {
        nav.app_page
    };
    let query = if settings {
        nav.search.read(cx).value().trim().to_lowercase()
    } else {
        String::new()
    };
    let mut list = col().gap(px(ui::nav::GAP));
    let mut matched = false;
    for item in items
        .iter()
        .filter(|i| query.is_empty() || i.title.to_lowercase().contains(&query))
    {
        matched = true;
        let page = item.page;
        let active = selected == page;
        list = list.child(
            ui::nav::button(item.title.clone(), active, cx)
                .toggled(active)
                .accessibility_label(item.title.clone())
                .child(
                    row()
                        .w_full()
                        .gap(px(8.))
                        .child(match item.icon {
                            DestinationIcon::Glyph(glyph) => ui::nav::glyph(glyph, active),
                            DestinationIcon::Tile { emoji, color } => {
                                icons::icon(emoji, color, ui::nav::ICON_BOX)
                            }
                        })
                        .child(ui::nav::title(item.title.clone())),
                )
                .on_click(cx.listener(move |host: &mut H, _, w, cx| {
                    let nav = host.navigation_mut();
                    if settings {
                        nav.settings_page = page;
                    } else {
                        nav.app_page = page;
                    }
                    nav.compact_list = false;
                    nav.focus.focus(w, cx);
                    host.navigated(w, cx);
                    cx.notify();
                })),
        );
    }
    if !matched {
        list = list.child(
            ui::caption("No matching settings")
                .id("no-matching-settings")
                .px(px(ui::nav::PAD))
                .py(px(6.)),
        );
    }
    let top = if settings {
        div()
            .h(px(ui::nav::ROW))
            .mb(px(12.))
            .pr(px(ui::nav::TRAIL))
            .rounded(px(ui::nav::RADIUS))
            .bg(rgb(ui::theme::get(4)))
            .flex()
            .items_center()
            .child(
                input::Input::new(&nav.search)
                    .small()
                    .appearance(false)
                    .w_full()
                    .prefix(
                        div().w(px(20.5)).pl(px(1.5)).flex().child(
                            Icon::new(Glyph::Search)
                                .size(px(13.))
                                .text_color(rgb(ui::theme::get(1))),
                        ),
                    )
                    .cleanable(true)
                    .aria_label("Search settings"),
            )
    } else {
        div()
    };
    let footer = if settings {
        let title = host.back_label();
        ui::nav::button("close-settings", false, cx)
            .accessibility_label(title)
            .tooltip(format!("{title} · Esc"))
            .child(
                row()
                    .w_full()
                    .gap(px(8.))
                    .child(ui::nav::glyph(Glyph::ArrowLeft, false))
                    .child(ui::nav::title(title)),
            )
            .on_click(cx.listener(|h: &mut H, _, w, cx| switch(h, false, w, cx)))
    } else {
        settings_button(cx).on_click(cx.listener(|h: &mut H, _, w, cx| switch(h, true, w, cx)))
    };
    sidebar(
        list,
        top.into_any_element(),
        None,
        footer.into_any_element(),
    )
    .when(nav.compact(w), |el| el.w_full())
}

/// Render the host's sidebar, titlebar and selected page.
pub fn render<H: WorkspaceHost>(host: &mut H, w: &mut Window, cx: &mut Context<H>) -> Div {
    let desired = host.navigation().in_settings;
    let phase = ui::motion::presence("workspace-settings", desired, w, cx).progress;
    // View finishes covering the old page before revealing the new one.
    let out = (phase / 0.45).clamp(0., 1.);
    let arrival = ((phase - 0.45) / 0.55).clamp(0., 1.);
    let settings = out >= 1.;
    let nav = host.navigation();
    let compact = nav.compact(w);
    let can_toggle = (compact || !settings) && (!nav.standalone || settings);
    let list_only = compact && nav.compact_list && can_toggle;
    let visible = if compact {
        list_only
    } else {
        settings || !nav.wide_collapsed
    };
    let page = if settings {
        nav.settings_page
    } else {
        nav.app_page
    };
    let items = host.destinations(settings);
    let title = items
        .iter()
        .find(|i| i.page == page)
        .map(|i| i.title.clone())
        .unwrap_or_default();
    let focus = nav.focus.clone();
    // Sample the user's wide-sidebar preference independently of automatic resizing.
    // Crossing the compact breakpoint changes layout immediately.
    let wide = ui::motion::presence("workspace-sidebar", !nav.wide_collapsed, w, cx).progress;
    let rail_width = if !compact && !settings {
        wide
    } else {
        f32::from(visible)
    };
    let mut layout = window_layout(rail_width).items_stretch();
    if rail_width > 0. {
        let sidebar = rail(host, settings, &items, w, cx)
            .relative()
            .left(px(if settings {
                ui::motion::travel(arrival, 8.)
            } else {
                -6. * out
            }))
            .opacity(rail_width * if settings { arrival } else { 1. - out });
        layout = if compact {
            layout.child(sidebar)
        } else {
            layout.child(sidebar_slot(rail_width).child(sidebar))
        };
    }
    if !visible {
        layout = layout.child(
            titlebar_drag("workspace-titlebar")
                .opacity(1. - rail_width)
                .absolute()
                .top_0()
                .left(px(if can_toggle {
                    titlebar::TOGGLE_LEFT + titlebar::BUTTON
                } else {
                    TRAFFIC_LIGHT_END
                }))
                .right_0()
                .h(px(titlebar::band()))
                .pl(px(titlebar::TITLE_GAP))
                .pr(px(16.))
                .flex()
                .items_center()
                .child(
                    div()
                        .truncate()
                        .text_size(px(ui::BODY))
                        .font_weight(FontWeight::MEDIUM)
                        .child(title),
                ),
        );
    }
    if !list_only {
        let page = host.render_page(page, w, cx);
        let body = col()
            .relative()
            .flex_1()
            .min_h_0()
            .w_full()
            .child(page)
            .when(settings, |el| {
                el.left(px(ui::motion::travel(arrival, 8.)))
                    .opacity(arrival)
            });
        layout = layout.child(
            pane(col())
                .relative()
                .flex_1()
                .min_w_0()
                .min_h_0()
                .my(px(GUTTER))
                .mr(px(GUTTER))
                .ml(px(GUTTER * (1. - rail_width)))
                .child(body)
                .when(!settings && out > 0., |el| el.child(veil(out))),
        );
    }
    // Pin controls to window coordinates, independently of scrolling pages.
    let mut shell = root()
        .key_context("MeepWorkspace")
        .track_focus(&focus)
        .capture_key_down(|_, _, cx| ui::motion::set_input(ui::motion::InputOrigin::Keyboard, cx))
        .capture_any_mouse_down(|_, _, cx| {
            ui::motion::set_input(ui::motion::InputOrigin::Pointer, cx)
        })
        .child(layout);
    if can_toggle {
        shell = shell
            .child(sidebar_toggle(visible).on_click(cx.listener(|h, _, w, cx| toggle(h, w, cx))));
    }
    shell
        .on_action(cx.listener(|h, _: &OpenSettings, w, cx| switch(h, true, w, cx)))
        .on_action(cx.listener(|h: &mut H, _: &Back, w, cx| {
            if h.navigation().compact_list {
                toggle(h, w, cx);
            } else if h.navigation().in_settings {
                switch(h, false, w, cx);
            } else {
                cx.propagate();
            }
        }))
        .when(can_toggle, |shell| {
            shell.on_action(cx.listener(|h, _: &ToggleSidebar, w, cx| toggle(h, w, cx)))
        })
        .on_action(cx.listener(|_, _: &CloseWindow, w, _| w.remove_window()))
        .on_action(cx.listener(|_, _: &Minimize, w, _| w.minimize_window()))
        .on_action(cx.listener(|_, _: &Zoom, w, _| w.zoom_window()))
        .on_action(cx.listener(|_, _: &FullScreen, w, _| w.toggle_fullscreen()))
}
