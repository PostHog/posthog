use super::*;
use meep_ui::gpui_kit::component::{
    Disableable,
    menu::{DropdownMenu, PopupMenuItem},
};
#[derive(Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct Preferences {
    pub name: String,
    pub start: Page,
    scheme: Option<String>,
}
impl Default for Preferences {
    fn default() -> Self {
        Self {
            name: "Workspace".into(),
            start: Page::Views,
            scheme: None,
        }
    }
}
impl Preferences {
    pub fn apply(&self, w: &Window, cx: &mut App) {
        let palette = meep_shell::appearance::resolve(self.scheme.as_deref(), w.appearance());
        meep_shell::appearance::set_palette(palette, cx);
    }
}
impl Gallery {
    fn persist(&mut self, next: Preferences, w: &mut Window, cx: &mut Context<Self>) {
        if self.saving {
            return;
        }
        self.saving = true;
        self.error = None;
        cx.notify();
        let db = self.services.db.clone();
        let write = cx.background_executor().spawn(async move {
            let db = db
                .lock()
                .map_err(|_| "Preference store unavailable".to_owned())?;
            meep_store::put(&db, "desktop", "preferences", &next).map_err(|e| e.to_string())?;
            Ok::<_, String>(next)
        });
        cx.spawn_in(w, async move |this, cx| {
            let result = write.await;
            let _ = this.update_in(cx, |this, w, cx| {
                this.saving = false;
                match result {
                    Ok(next) => {
                        next.apply(w, cx);
                        this.preferences = next;
                        this.update_title(w);
                    }
                    Err(error) => this.error = Some(error),
                }
                cx.notify();
            });
        })
        .detach();
    }
    pub(super) fn save_name(&mut self, w: &mut Window, cx: &mut Context<Self>) {
        let name = self.name.read(cx).value().trim().to_owned();
        if name.is_empty() {
            self.error = Some("Enter a workspace name.".into());
            cx.notify();
            return;
        }
        let mut next = self.preferences.clone();
        next.name = name;
        self.persist(next, w, cx);
    }
    pub(super) fn preference_page(
        &self,
        page: Page,
        w: &Window,
        cx: &mut Context<Self>,
    ) -> impl IntoElement {
        let width = self.nav.content_width(w);
        let mut content = ui::column().gap_0();
        match page {
            Page::Appearance => {
                return meep_shell::appearance::picker(
                    self.preferences.scheme.as_deref(),
                    self.saving,
                    width,
                    |g: &mut Self, scheme, w, cx| {
                        let mut next = g.preferences.clone();
                        next.scheme = scheme.map(str::to_owned);
                        g.persist(next, w, cx);
                    },
                    w,
                    cx,
                );
            }
            Page::Personalization => {
                let gallery = cx.entity().downgrade();
                let start = self.preferences.start;
                let picker = settings::menu_pill("start-page", start.title(), cx)
                    .disabled(self.saving)
                    .dropdown_menu(move |menu, _, _| {
                        Page::ALL.into_iter().filter(|p| p.script().is_some()).fold(
                            menu.min_w(px(156.)),
                            |menu, page| {
                                let gallery = gallery.clone();
                                menu.item(
                                    PopupMenuItem::new(page.title())
                                        .checked(start == page)
                                        .on_click(move |_, w, cx| {
                                            let _ = gallery.update(cx, |g, cx| {
                                                let mut next = g.preferences.clone();
                                                next.start = page;
                                                g.persist(next, w, cx);
                                            });
                                        }),
                                )
                            },
                        )
                    });
                content = content
                    .child(settings::header("Personalization", "", None))
                    .child(settings::section("Workspace", "", None, true))
                    .child(settings::group([settings::item(
                        "Start page",
                        "Open this page on launch.",
                        picker,
                    )
                    .into_any_element()]));
            }
            _ => {
                let dirty = self.name.read(cx).value().trim() != self.preferences.name;
                let save = dirty.then(|| {
                    settings::primary_pill("save-name", "Save changes")
                        .disabled(self.saving)
                        .on_click(cx.listener(|g, _, w, cx| g.save_name(w, cx)))
                        .into_any_element()
                });
                let input = div()
                    .w(px(if width < px(420.) { 128. } else { 188. }))
                    .child(ui::forms::input(&self.name, "Workspace name"));
                content = content
                    .child(settings::header("General", "", save))
                    .child(settings::section("Workspace", "", None, true))
                    .child(settings::group([settings::item(
                        "Workspace name",
                        "",
                        input,
                    )
                    .into_any_element()]));
            }
        }
        meep_shell::appearance::settings_body("settings-scroll", width, content)
    }
}
