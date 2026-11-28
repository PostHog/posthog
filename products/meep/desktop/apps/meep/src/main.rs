//! Meep: the native, replica-backed topics workspace.
mod backend;
mod brand;
#[cfg(feature = "demo-driver")]
mod demo_driver;
mod desktop;
mod details;
mod files;
mod folds;
mod github;
mod mcp_settings;
mod navigation;
mod overview;
mod pages;
mod preferences;
mod previews;
mod scroll_motion;
mod shortcuts;
mod sidebar;
mod sources;
#[cfg(feature = "demo-driver")]
mod state_preview;
mod tables;
mod tasks_view;
mod topic_card;
mod topic_icon;
mod topic_pages;
mod views;

use anyhow::Result;
use backend::{Backend, Identity, Options, Region};
use clap::Parser;
use desktop::*;
use meep_client::{Client, Status};
use meep_shell::chat::{ActivityIndicator, ChatHost, TranscriptHost};
use meep_topic::*;
use meep_ui::{
    components as ui,
    gpui_kit::{
        self,
        assets::IconName as Glyph,
        component::{
            button::Button,
            input::{Input, InputEvent, InputState, TextareaState},
        },
        prelude::FluentBuilder,
        *,
    },
};
use meep_wire::NeedsYouItem;
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, HashSet},
    sync::Arc,
};
use tokio::runtime::Runtime;
use uuid::Uuid;

fn main() -> Result<()> {
    let options = Options::parse();
    let runtime = Arc::new(Runtime::new()?);
    gpui_kit::application()
        .with_assets(gpui_kit::assets::AllAssets)
        .run(move |cx| {
            meep_render::init(cx);
            #[cfg(target_os = "macos")]
            brand::install_dock_icon();
            meep_shell::puppet::preload();
            meep_shell::workspace::install_menus("Meep", cx);
            let options_window = WindowOptions {
                window_bounds: Some(WindowBounds::Windowed(Bounds::centered(
                    None,
                    size(px(1180.), px(780.)),
                    cx,
                ))),
                window_min_size: Some(size(px(760.), px(480.))),
                titlebar: Some(TitlebarOptions {
                    title: Some("Meep".into()),
                    ..Default::default()
                }),
                ..Default::default()
            };
            let opened = meep_shell::workspace::open_window(options_window, cx, |w, cx| {
                cx.new(|cx| {
                    meep_shell::appearance::set_palette(
                        meep_shell::appearance::resolve(None, w.appearance()),
                        cx,
                    );
                    cx.observe_window_appearance(w, |s: &mut Host, w, cx| {
                        if s.view.is_none() {
                            meep_shell::appearance::set_palette(
                                meep_shell::appearance::resolve(None, w.appearance()),
                                cx,
                            );
                            cx.notify();
                        }
                    })
                    .detach();
                    let host = Host {
                        motion: Default::default(),
                        gaze: 4,
                        eye_center: Default::default(),
                        #[cfg(feature = "demo-driver")]
                        preview: Default::default(),
                        options,
                        runtime,
                        view: None,
                        error: None,
                    };
                    host.connect(w, cx);
                    host
                })
            });
            match opened {
                #[cfg(feature = "demo-driver")]
                Ok((window, _)) => demo_driver::start(window, cx),
                #[cfg(not(feature = "demo-driver"))]
                Ok(_) => {}
                Err(e) => {
                    eprintln!("Could not open Topics: {e}");
                    cx.quit();
                }
            }
            cx.on_window_closed(|cx, _| {
                if cx.windows().is_empty() {
                    cx.quit()
                }
            })
            .detach();
            // A recorded demo runs behind the person's own work; don't take focus.
            if std::env::var_os("MEEP_DEMO_SOCKET").is_none() {
                cx.activate(true);
            }
        });
    Ok(())
}

struct Host {
    motion: std::rc::Rc<scroll_motion::ScrollMotion>,
    gaze: usize,
    eye_center: std::rc::Rc<std::cell::Cell<Option<Point<Pixels>>>>,
    #[cfg(feature = "demo-driver")]
    preview: state_preview::Scene,
    options: Options,
    runtime: Arc<Runtime>,
    view: Option<Entity<Desktop>>,
    error: Option<String>,
}
impl Host {
    fn connect(&self, w: &Window, cx: &mut Context<Self>) {
        #[cfg(feature = "demo-driver")]
        if self.options.preview_states {
            return;
        }
        let options = self.options.clone();
        let task = self.runtime.spawn(async move { options.connect().await });
        cx.spawn_in(w, async move |this, cx| {
            let result = task.await.map_err(anyhow::Error::from).and_then(|r| r);
            let _ = this.update_in(cx, |s, w, cx| {
                match result {
                    Ok(backend) => {
                        s.view = Some(cx.new(|cx| Desktop::new(backend, s.runtime.clone(), w, cx)))
                    }
                    Err(e) => s.error = Some(format!("{e:#}")),
                }
                cx.notify();
            });
        })
        .detach()
    }
}
impl Render for Host {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        #[cfg(feature = "demo-driver")]
        if self.options.preview_states {
            return self.preview_states(cx);
        }
        if let Some(view) = &self.view {
            return div()
                .relative()
                .size_full()
                .child(self.motion.listener())
                .child(view.clone())
                .into_any_element();
        }
        self.opening_screen(cx).into_any_element()
    }
}
impl Host {
    fn opening_screen(&self, cx: &mut Context<Self>) -> AnyElement {
        let (title, line) = match &self.error {
            None => ("Opening your workspace", boot_line(None)),
            Some(e) => ("Meep couldn't open your workspace", boot_line(Some(e))),
        };
        ui::page()
            .relative()
            .child(div().absolute().bottom(px(26.)).child(brand::wordmark(84.)))
            .justify_center()
            .items_center()
            .pb(px(48.))
            .on_mouse_move(cx.listener(|s, event: &MouseMoveEvent, _, cx| {
                if s.error.is_some() || cx.reduce_motion() {
                    return;
                }
                let Some(center) = s.eye_center.get() else {
                    return;
                };
                let axis = |delta: f32| {
                    if delta < -16. {
                        0
                    } else if delta > 16. {
                        2
                    } else {
                        1
                    }
                };
                let gaze = axis(f32::from(event.position.x - center.x))
                    + 3 * axis(f32::from(event.position.y - center.y));
                if s.gaze != gaze {
                    s.gaze = gaze;
                    cx.notify();
                }
            }))
            .child(if self.error.is_some() {
                meep_shell::puppet::connection_error(156.)
            } else {
                let center = self.eye_center.clone();
                meep_shell::puppet::opening(if cx.reduce_motion() { 4 } else { self.gaze }, 156.)
                    .on_children_prepainted(move |children, _, _| {
                        center.set(children.last().map(|eyes| eyes.center()));
                    })
            })
            .child(
                div()
                    .pt(px(16.))
                    .text_size(px(15.))
                    .font_weight(FontWeight::SEMIBOLD)
                    .child(title),
            )
            .child(ui::caption(line).pt(px(6.)).max_w(px(420.)).text_center())
            .when_some(self.error.clone(), |el, e| {
                el.child(
                    div()
                        .mt(px(14.))
                        .max_w(px(420.))
                        .text_center()
                        .text_size(px(11.))
                        .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                        .child(e),
                )
                .child(div().pt(px(18.)).child(
                    ui::primary_button("retry", "Try again").on_click(cx.listener(
                        |s, _, w, cx| {
                            s.error = None;
                            #[cfg(feature = "demo-driver")]
                            {
                                s.preview = Default::default();
                            }
                            s.connect(w, cx);
                            cx.notify()
                        },
                    )),
                ))
            })
            .into_any_element()
    }
}

fn boot_line(error: Option<&str>) -> &'static str {
    let Some(error) = error.map(str::to_lowercase) else {
        return "Getting your topics ready.";
    };
    let has = |words: &[&str]| words.iter().any(|w| error.contains(w));
    if has(&[
        "scope",
        "registration",
        "unauthorized",
        "401",
        "403",
        "oauth",
    ]) {
        "PostHog didn't give Meep the access it needs. Try again and allow every permission PostHog asks for."
    } else if has(&[
        "connect",
        "dns",
        "network",
        "timed out",
        "refused",
        "unreachable",
    ]) {
        "Meep can't reach PostHog. Check your connection, then try again."
    } else {
        "Something stopped Meep while it opened your workspace. The details are below."
    }
}
