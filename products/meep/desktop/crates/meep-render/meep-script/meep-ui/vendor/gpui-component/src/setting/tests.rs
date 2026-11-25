use super::*;
use crate::{
    Root,
    group_box::GroupBoxVariant,
    setting::{SettingGroup, SettingItem},
};
use gpui::{
    Context, Render, ScrollDelta, ScrollEvent, TestAppContext, VisualTestContext, point, size,
};

struct SettingsHost {
    pages: Vec<SettingPage>,
    state: Option<Entity<SettingsState>>,
}

impl Render for SettingsHost {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let settings = Settings::new("search-test")
            .pages(self.pages.clone())
            .default_selected_index(SelectIndex {
                page_ix: 1,
                group_ix: None,
            })
            .render(window, cx)
            .into_any_element();
        self.state = Some(window.use_keyed_state("search-test", cx, |_, _| unreachable!()));
        div().size_full().child(settings)
    }
}

fn item(keyword: &'static str) -> SettingItem {
    item_with_height(keyword, 80.)
}

fn item_with_height(keyword: &'static str, height: f32) -> SettingItem {
    SettingItem::render(move |options, _, _| {
        let selector = format!(
            "setting-{}-{}-{}",
            options.page_ix(),
            options.group_ix(),
            options.item_ix()
        );
        div()
            .h(px(height))
            .child("Setting")
            .debug_selector(move || selector.clone())
    })
    .keywords([keyword])
}

fn setup(cx: &mut TestAppContext) -> (Entity<SettingsHost>, &mut VisualTestContext) {
    cx.update(|cx| {
        crate::init(cx);
        crate::Theme::global_mut(cx).font_size = px(16.);
    });
    let pages = vec![
        SettingPage::new("General").group(SettingGroup::new().item(item("language"))),
        SettingPage::new("Appearance").default_open(true).groups([
            SettingGroup::new().item(item("unrelated")),
            SettingGroup::new()
                .title("Colors")
                .item(item("theme colors")),
            SettingGroup::new()
                .title("Fonts")
                .items([item("unrelated"), item("theme font")]),
        ]),
        SettingPage::new("Editor").group(SettingGroup::new().item(item("theme editor"))),
    ];
    let mut host = None;
    let (_, cx) = cx.add_window_view(|window, cx| {
        let view = cx.new(|_| SettingsHost { pages, state: None });
        host = Some(view.clone());
        Root::new(view, window, cx)
    });
    cx.simulate_resize(size(px(1000.), px(700.)));
    draw(cx);
    (host.unwrap(), cx)
}

fn draw(cx: &mut VisualTestContext) {
    cx.run_until_parked();
    cx.update(|window, cx| window.draw(cx).clear(cx));
}

fn search(host: &Entity<SettingsHost>, query: &str, cx: &mut VisualTestContext) {
    cx.update(|window, cx| {
        let input = host
            .read(cx)
            .state
            .as_ref()
            .unwrap()
            .read(cx)
            .search_input
            .clone();
        input.update(cx, |input, cx| input.set_value(query, window, cx));
    });
    draw(cx);
}

fn selection(host: &Entity<SettingsHost>, cx: &mut VisualTestContext) -> (usize, Option<usize>) {
    cx.update(|_, cx| {
        let selected = host
            .read(cx)
            .state
            .as_ref()
            .unwrap()
            .read(cx)
            .selected_index;
        (selected.page_ix, selected.group_ix)
    })
}

fn click_nav(y: f32, cx: &mut VisualTestContext) {
    // Fixed-size fixture with a 16px rem; click the label area, away from carets.
    cx.simulate_click(point(px(50.), px(y)), Default::default());
    draw(cx);
}

#[gpui::test]
fn search_preserves_the_page_and_clicks_use_original_indices(cx: &mut TestAppContext) {
    let (host, cx) = setup(cx);
    // The old numeric index is still in range, but would point to Editor.
    search(&host, "theme", cx);
    assert_eq!(selection(&host, cx), (1, None));
    assert!(cx.debug_bounds("setting-1-1-0").is_some());
    assert!(cx.debug_bounds("setting-2-0-0").is_none());

    // Only Appearance matches; the old implementation renders a blank page.
    search(&host, "font", cx);
    assert_eq!(selection(&host, cx), (1, None));
    assert!(cx.debug_bounds("setting-1-2-1").is_some());

    // Select Editor from the compressed result list, then clear the query.
    search(&host, "theme", cx);
    click_nav(156., cx);
    assert_eq!(selection(&host, cx), (2, None));
    search(&host, "", cx);
    assert_eq!(selection(&host, cx), (2, None));
    assert!(cx.debug_bounds("setting-2-0-0").is_some());

    // The current page disappears: choose the first matching page.
    search(&host, "font", cx);
    assert_eq!(selection(&host, cx), (1, None));
    assert!(cx.debug_bounds("setting-1-2-1").is_some());
    search(&host, "no matching setting", cx);
    assert_eq!(selection(&host, cx), (1, None));
    assert!(cx.debug_bounds("setting-1-2-1").is_none());
    assert!(cx.debug_bounds("settings-no-results").is_some());
    search(&host, "", cx);
    assert_eq!(selection(&host, cx), (1, None));
    assert!(cx.debug_bounds("settings-no-results").is_none());
}

#[gpui::test]
fn scrolling_marks_the_group_at_the_top(cx: &mut TestAppContext) {
    let (host, cx) = setup(cx);
    cx.update(|_, cx| {
        host.update(cx, |host, cx| {
            host.pages[1].groups[1].items = vec![item_with_height("theme colors", 900.)];
            cx.notify();
        });
    });
    draw(cx);
    assert_eq!(selection(&host, cx), (1, None));

    let scroll = |delta: f32, cx: &mut VisualTestContext| {
        cx.simulate_event(ScrollEvent {
            position: point(px(600.), px(400.)),
            delta: ScrollDelta::Pixels(point(px(0.), px(delta))),
            ..Default::default()
        });
        draw(cx);
    };
    // Past the untitled first group, Colors reaches the top.
    scroll(-200., cx);
    assert_eq!(selection(&host, cx), (1, Some(1)));
    // At the end of the list, the last group is marked.
    scroll(-2000., cx);
    assert_eq!(selection(&host, cx), (1, Some(2)));
    // Back at the top, the untitled group marks the page itself.
    scroll(4000., cx);
    assert_eq!(selection(&host, cx), (1, None));
}

#[gpui::test]
fn search_preserves_group_and_item_identity(cx: &mut TestAppContext) {
    let (host, cx) = setup(cx);
    // Make the target group require scrolling, with an unnamed group before it.
    cx.update(|_, cx| {
        host.update(cx, |host, cx| {
            host.pages[1].groups[1].items = vec![item_with_height("theme colors", 450.)];
            cx.notify();
        });
    });
    draw(cx);
    click_nav(156., cx);
    assert_eq!(selection(&host, cx), (1, Some(2)));
    search(&host, "theme", cx);
    assert_eq!(selection(&host, cx), (1, Some(2)));
    assert!(cx.debug_bounds("setting-1-2-1").is_some());
    assert!(cx.debug_bounds("setting-1-2-0").is_none());
    // Click Fonts after the leading page/group/item have been filtered out.
    click_nav(120., cx);
    assert_eq!(selection(&host, cx), (1, Some(2)));
    let target = cx.debug_bounds("setting-1-2-1").unwrap();
    assert!(target.top() >= px(0.) && target.bottom() <= px(700.));
    search(&host, "font", cx);
    assert_eq!(selection(&host, cx), (1, Some(2)));
    search(&host, "", cx);
    assert_eq!(selection(&host, cx), (1, Some(2)));
    search(&host, "colors", cx);
    assert_eq!(selection(&host, cx), (1, None));
    assert!(cx.debug_bounds("setting-1-1-0").is_some());
}

#[gpui::test]
fn footer_follows_group_search_visibility(cx: &mut TestAppContext) {
    let (host, cx) = setup(cx);
    cx.update(|_, cx| {
        host.update(cx, |host, cx| {
            host.pages[1].groups[2] = host.pages[1].groups[2].clone().footer(|_, _| {
                div()
                    .child("Changes apply to this device only.")
                    .debug_selector(|| "font-footer".into())
            });
            cx.notify();
        });
    });
    search(&host, "font", cx);
    assert!(cx.debug_bounds("setting-1-2-1").is_some());
    assert!(cx.debug_bounds("font-footer").is_some());

    // Footer copy does not independently make a group match the query.
    search(&host, "colors", cx);
    assert!(cx.debug_bounds("setting-1-1-0").is_some());
    assert!(cx.debug_bounds("font-footer").is_none());

    search(&host, "font", cx);
    assert!(cx.debug_bounds("font-footer").is_some());
    assert_eq!(selection(&host, cx), (1, None));
}

#[gpui::test]
fn resetting_search_results_leaves_hidden_settings_unchanged(cx: &mut TestAppContext) {
    use std::{cell::Cell, rc::Rc};

    let (_, cx) = setup(cx);
    let visible = Rc::new(Cell::new(false));
    let hidden = Rc::new(Cell::new(true));
    let resettable_item = |keyword, dirty: &Rc<Cell<bool>>| {
        let read = dirty.clone();
        let reset = dirty.clone();
        item(keyword).on_reset(move |_| read.get(), move |_, _| reset.set(false))
    };
    let group = SettingGroup::new().items([
        resettable_item("theme", &visible),
        resettable_item("hidden", &hidden),
    ]);
    cx.update(|window, cx| {
        assert!(!group.is_resettable("theme", cx));
        visible.set(true);
        assert!(group.is_resettable("theme", cx));
        group.reset("theme", window, cx);
    });
    assert!(!visible.get());
    assert!(hidden.get());
}

struct VariantHost {
    pages: Vec<SettingPage>,
    outline: bool,
}

impl Render for VariantHost {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let mut settings = Settings::new("variant-test").pages(self.pages.clone());
        if self.outline {
            settings = settings.with_group_variant(GroupBoxVariant::Outline);
        }
        div()
            .size_full()
            .child(settings.render(window, cx).into_any_element())
    }
}

fn variant_pages(override_first_group: bool) -> Vec<SettingPage> {
    let first = if override_first_group {
        SettingGroup::new().variant(GroupBoxVariant::Normal)
    } else {
        SettingGroup::new()
    };
    vec![SettingPage::new("General").groups([
        first.item(item("plain")),
        SettingGroup::new().item(item("outlined")),
    ])]
}

#[gpui::test]
fn group_variant_overrides_the_settings_default(cx: &mut TestAppContext) {
    cx.update(|cx| {
        crate::init(cx);
        crate::Theme::global_mut(cx).font_size = px(16.);
    });

    let open_window = |pages, outline, cx: &mut TestAppContext| {
        let (_, cx) = cx.add_window_view(|window, cx| {
            let view = cx.new(|_| VariantHost { pages, outline });
            Root::new(view, window, cx)
        });
        cx.simulate_resize(size(px(1000.), px(700.)));
        draw(cx);
        (
            cx.debug_bounds("setting-0-0-0").unwrap(),
            cx.debug_bounds("setting-0-1-0").unwrap(),
        )
    };

    // Baseline: no global variant, so both groups present their items directly.
    let (baseline_first, baseline_second) = open_window(variant_pages(false), false, cx);
    // A global Outline default with the first group overriding back to Normal.
    let (overridden_first, inherited_second) = open_window(variant_pages(true), true, cx);

    // The override presents the group exactly like the settings-level default.
    assert_eq!(
        f64::from(overridden_first.top() - baseline_first.top()),
        0.,
        "the overridden group must lose the global Outline chrome"
    );
    // A group without the override keeps the global Outline chrome:
    // a 1px border and 16px padding above its items.
    assert_eq!(
        f64::from(inherited_second.top() - baseline_second.top()),
        17.,
        "groups without an override must keep the settings-level variant"
    );
}

#[gpui::test]
fn selecting_a_group_from_another_page_scrolls_to_it(cx: &mut TestAppContext) {
    let (host, cx) = setup(cx);
    // Push Fonts below the viewport.
    cx.update(|_, cx| {
        host.update(cx, |host, cx| {
            host.pages[1].groups[1].items = vec![item_with_height("theme colors", 900.)];
            cx.notify();
        });
    });
    draw(cx);
    let select = |page_ix, group_ix: Option<usize>, cx: &mut VisualTestContext| {
        cx.update(|_, cx| {
            let state = host.read(cx).state.clone().unwrap();
            state.update(cx, |state, cx| {
                state.selected_index = SelectIndex { page_ix, group_ix };
                state.deferred_scroll_group_ix = group_ix;
                cx.notify();
            });
        });
        draw(cx);
    };

    // Leaving the page drops its list state; the jump back must not land at the top.
    select(0, None, cx);
    select(1, Some(2), cx);
    let target = cx.debug_bounds("setting-1-2-1").unwrap();
    assert!(target.top() >= px(0.) && target.bottom() <= px(700.));
}
