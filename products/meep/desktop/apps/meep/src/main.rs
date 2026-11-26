//! Meep: the native, replica-backed topics workspace.
mod backend;
#[cfg(feature = "demo-driver")]
mod demo_driver;
mod desktop;
mod details;
mod files;
mod folds;
mod mcp_settings;
mod navigation;
mod overview;
mod pages;
mod preferences;
mod scroll_motion;
mod shortcuts;
mod sidebar;
mod tables;
mod tasks_view;
mod topic_card;
mod topic_icon;
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
                    let host = Host {
                        motion: Default::default(),
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
    options: Options,
    runtime: Arc<Runtime>,
    view: Option<Entity<Desktop>>,
    error: Option<String>,
}
impl Host {
    fn connect(&self, w: &Window, cx: &mut Context<Self>) {
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
        if let Some(view) = &self.view {
            return div()
                .relative()
                .size_full()
                .child(self.motion.listener())
                .child(view.clone())
                .into_any_element();
        }
        let reduced = cx.reduce_motion();
        let (slug, title, line) = match &self.error {
            None => ("coffee-run", "Opening your workspace", boot_line(None)),
            Some(e) => (
                "error",
                "Meep couldn't open your workspace",
                boot_line(Some(e)),
            ),
        };
        ui::page()
            .justify_center()
            .items_center()
            .pb(px(48.))
            .child(topic_icon::bob(
                "boot-hog",
                topic_icon::hero(slug, 128.),
                reduced,
            ))
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
