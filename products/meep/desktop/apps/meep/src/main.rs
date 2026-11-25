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
            return view.clone().into_any_element();
        }
        ui::page()
            .justify_center()
            .items_center()
            .child(ui::heading("app-title", "Meep"))
            .child(ui::caption(
                self.error
                    .clone()
                    .unwrap_or_else(|| "Opening your workspace…".into()),
            ))
            .when(self.error.is_some(), |el| {
                el.child(
                    ui::button("retry", "Try again").on_click(cx.listener(|s, _, w, cx| {
                        s.error = None;
                        s.connect(w, cx);
                        cx.notify()
                    })),
                )
            })
            .into_any_element()
    }
}
