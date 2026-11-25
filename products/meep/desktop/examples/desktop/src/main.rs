//! Example host. Navigation, preference storage and source registration belong here.
mod fixture;
mod preferences;
mod service;

use anyhow::Result;
use clap::{Parser, ValueEnum};
use meep_render::{
    gpui_kit::{
        self,
        assets::IconName as Glyph,
        component::input::{InputEvent, InputState},
        *,
    },
    sdk::{MountedView, ViewContext},
};
use meep_shell::workspace::{self, Destination, Navigation, WorkspaceHost};
use meep_ui::{components as ui, settings};
use preferences::Preferences;
use serde::{Deserialize, Serialize};
use service::{Services, Source};
use std::{collections::HashMap, path::PathBuf, sync::Arc};

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Hash, ValueEnum, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
enum Page {
    #[default]
    Views,
    Document,
    Tasks,
    Tools,
    Storage,
    Workflows,
    Settings,
    Appearance,
    Personalization,
}
impl Page {
    const ALL: [Self; 9] = [
        Self::Views,
        Self::Document,
        Self::Tasks,
        Self::Tools,
        Self::Storage,
        Self::Workflows,
        Self::Settings,
        Self::Appearance,
        Self::Personalization,
    ];
    fn title(self) -> &'static str {
        match self {
            Self::Views => "Reading list",
            Self::Document => "Document",
            Self::Tasks => "Tasks",
            Self::Tools => "Tool servers",
            Self::Storage => "Notes",
            Self::Workflows => "Workflows",
            Self::Settings => "General",
            Self::Appearance => "Appearance",
            Self::Personalization => "Personalization",
        }
    }
    fn destination(self) -> Destination<Self> {
        let (emoji, color) = match self {
            Self::Views => ("📚", "moss"),
            Self::Document => ("📝", "ink"),
            Self::Tasks => ("☑️", "teal"),
            Self::Tools => ("🔌", "plum"),
            Self::Storage => ("📒", "mustard"),
            Self::Workflows => ("⚙️", "orange"),
            Self::Settings => {
                return Destination::new(self, self.title(), Glyph::SlidersHorizontal);
            }
            Self::Appearance => return Destination::new(self, self.title(), Glyph::Settings2),
            Self::Personalization => return Destination::new(self, self.title(), Glyph::PanelLeft),
        };
        Destination::tile(self, self.title(), emoji, color)
    }
    fn script(self) -> Option<(Source, &'static str)> {
        Some(match self {
            Self::Views => (Source::StateOnly, include_str!("../views/reading.js")),
            Self::Document => (Source::StateOnly, include_str!("../views/document.js")),
            Self::Tasks => (Source::Tasks, include_str!("../views/tasks.js")),
            Self::Tools => (Source::Tools, include_str!("../views/tools.js")),
            Self::Storage => (Source::Storage, include_str!("../views/storage.js")),
            Self::Workflows => (Source::Workflows, include_str!("../views/workflows.js")),
            _ => return None,
        })
    }
}

#[derive(Parser)]
#[command(about = "Native desktop examples with an isolated local PostHog project")]
struct Options {
    /// Open a particular example. Without this, open the saved start page.
    #[arg(long, value_enum)]
    open: Option<Page>,
    /// Open the selected example on its own.
    #[arg(long, requires = "open")]
    standalone: bool,
    /// Bind the example's activity source to local data or a loopback PostHog workflow.
    #[arg(long, value_enum, default_value_t = service::WorkflowBackend::Local)]
    workflow_backend: service::WorkflowBackend,
    /// A manual version 2 workflow JSON file to register in the workflow example.
    #[arg(long)]
    workflow_file: Option<PathBuf>,
    /// Keep preferences and notes across launches using this SQLite file.
    #[arg(long)]
    data: Option<PathBuf>,
}

struct Gallery {
    nav: Navigation<Page>,
    preferences: Preferences,
    name: Entity<InputState>,
    mounted: HashMap<Page, MountedView>,
    services: Arc<Services>,
    runtime: Arc<tokio::runtime::Runtime>,
    error: Option<String>,
    saving: bool,
}
impl Gallery {
    fn update_title(&self, w: &mut Window) {
        w.set_window_title(&format!(
            "{} · {}",
            self.preferences.name,
            self.nav.selected().title()
        ));
    }

    fn new(
        open: Option<Page>,
        standalone: bool,
        preferences: Preferences,
        services: Arc<Services>,
        runtime: Arc<tokio::runtime::Runtime>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> Self {
        preferences.apply(window, cx);
        let name = cx.new(|cx| InputState::new(window, cx));
        name.update(cx, |i, cx| {
            i.set_value(preferences.name.clone(), window, cx)
        });
        cx.subscribe_in(
            &name,
            window,
            |this: &mut Self, _, event: &InputEvent, window, cx| {
                if matches!(event, InputEvent::PressEnter { .. }) {
                    this.save_name(window, cx);
                }
                cx.notify();
            },
        )
        .detach();
        cx.observe_window_appearance(window, |this, window, cx| {
            this.preferences.apply(window, cx);
            cx.notify();
        })
        .detach();
        let page = open.unwrap_or(preferences.start);
        let settings = page.script().is_none();
        let nav = Navigation::new(
            if settings { preferences.start } else { page },
            if settings { page } else { Page::Settings },
            settings,
            standalone,
            window,
            cx,
        );
        let mut gallery = Self {
            nav,
            preferences,
            name,
            mounted: HashMap::new(),
            services,
            runtime,
            error: None,
            saving: false,
        };
        gallery.navigated(window, cx);
        gallery
    }
}
impl WorkspaceHost for Gallery {
    type Page = Page;
    fn navigation(&self) -> &Navigation<Page> {
        &self.nav
    }
    fn navigation_mut(&mut self) -> &mut Navigation<Page> {
        &mut self.nav
    }
    fn back_label(&self) -> &'static str {
        "Back to workspace"
    }
    fn destinations(&self, settings: bool) -> Vec<Destination<Page>> {
        Page::ALL
            .into_iter()
            .filter(|page| page.script().is_none() == settings)
            .map(Page::destination)
            .collect()
    }
    fn navigated(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let page = self.nav.selected();
        self.error = None;
        if let Some((scope, script)) = page.script()
            && !self.mounted.contains_key(&page)
        {
            let context = ViewContext::new(
                page.title().into(),
                serde_json::json!({}),
                self.services.for_view(scope),
                self.runtime.clone(),
                "1".into(),
                true,
            );
            match meep_render::mount(script, window, cx, context) {
                Ok(view) => {
                    self.mounted.insert(page, view);
                }
                Err(error) => self.error = Some(error.to_string()),
            }
        }
        self.update_title(window);
        cx.notify();
    }
    fn render_page(
        &mut self,
        page: Page,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> AnyElement {
        let mut content = ui::column().gap_0().size_full();
        if let Some(error) = &self.error {
            content = content.child(ui::error_message("example-error", error.clone()).m(px(16.)));
        }
        if let Some(view) = self.mounted.get(&page) {
            content = content.child(div().flex_1().min_h_0().child(view.view.clone()));
        } else if page.script().is_none() {
            content = content.child(self.preference_page(page, window, cx));
        }
        content.into_any_element()
    }
}
impl Render for Gallery {
    fn render(&mut self, w: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        workspace::render(self, w, cx)
    }
}

fn main() -> Result<()> {
    let options = Options::parse();
    let runtime = Arc::new(tokio::runtime::Runtime::new()?);
    let db = if let Some(path) = options.data {
        meep_store::Connection::open(path)?
    } else {
        meep_store::Connection::open_in_memory()?
    };
    meep_store::initialize(&db)?;
    let preferences = meep_store::get(&db, "desktop", "preferences")?.unwrap_or_default();
    let mut services = Services::new(db, options.workflow_backend);
    if let Some(path) = options.workflow_file {
        let definition = serde_json::from_slice(&std::fs::read(path)?)?;
        services.install_workflow(definition)?;
    }
    let services = Arc::new(services);
    gpui_kit::application()
        .with_assets(gpui_kit::assets::AllAssets)
        .run(move |cx| {
            meep_render::init(cx);
            workspace::install_menus("Meep Examples", cx);
            let bounds = Bounds::centered(None, size(px(880.), px(620.)), cx);
            let options_window = WindowOptions {
                window_bounds: Some(WindowBounds::Windowed(bounds)),
                window_min_size: Some(size(px(350.), px(350.))),
                titlebar: Some(TitlebarOptions {
                    title: Some("Desktop examples".into()),
                    ..Default::default()
                }),
                ..Default::default()
            };
            workspace::open_window(options_window, cx, |w, cx| {
                cx.new(|cx| {
                    Gallery::new(
                        options.open,
                        options.standalone,
                        preferences,
                        services,
                        runtime,
                        w,
                        cx,
                    )
                })
            })
            .expect("open examples");
            cx.on_window_closed(|cx, _| {
                if cx.windows().is_empty() {
                    cx.quit()
                }
            })
            .detach();
            cx.activate(true);
        });
    Ok(())
}
