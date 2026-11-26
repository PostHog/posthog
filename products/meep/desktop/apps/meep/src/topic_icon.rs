use super::*;
use meep_ui::gpui_kit::component::{Icon, Selectable, button::ButtonVariants, popover::Popover};
use std::sync::LazyLock;

macro_rules! hedgehogs {
    ($($slug:literal => $label:literal, $terms:literal;)*) => {
        &[$(($slug, $label, $terms, include_bytes!(concat!(env!("CARGO_MANIFEST_DIR"), "/assets/topic-icons/", $slug, ".png")))),*]
    };
}
const ART: &[(&str, &str, &str, &[u8])] = include!("../../../crates/meep-topic/src/hedgehogs.in");
const COLUMNS: usize = 8;
const CELL: f32 = 34.;
const GAP: f32 = 6.;

fn search_key(text: &str) -> String {
    text.chars()
        .filter(char::is_ascii_alphanumeric)
        .map(|c| c.to_ascii_lowercase())
        .collect()
}

fn search_terms(query: &str) -> Vec<String> {
    query
        .split_whitespace()
        .map(search_key)
        .filter(|word| !word.is_empty())
        .collect()
}

fn matches_search(slug: &str, label: &str, aliases: &str, terms: &[String]) -> bool {
    terms.iter().all(|term| {
        [slug, label]
            .into_iter()
            .chain(aliases.split(", "))
            .any(|name| search_key(name).contains(term))
    })
}

static IMAGES: LazyLock<BTreeMap<&str, Arc<Image>>> = LazyLock::new(|| {
    ART.iter()
        .map(|&(slug, _, _, bytes)| {
            (
                slug,
                Arc::new(Image::from_bytes(ImageFormat::Png, bytes.to_vec())),
            )
        })
        .collect()
});

pub(super) fn art(slug: &str) -> Arc<Image> {
    IMAGES.get(slug).unwrap_or(&IMAGES["wizard-1"]).clone()
}

pub(super) fn hero(slug: &str, size: f32) -> Div {
    const BLEED: f32 = 2.;
    div()
        .flex_none()
        .relative()
        .size(px(size))
        .overflow_hidden()
        .child(
            img(art(slug))
                .absolute()
                .left(px(-BLEED))
                .top(px(-BLEED))
                .size(px(size + 2. * BLEED))
                .object_fit(ObjectFit::Contain),
        )
}

pub(super) fn bob(id: impl Into<ElementId>, el: Div, reduced: bool) -> AnyElement {
    if reduced {
        return el.into_any_element();
    }
    el.with_animation(
        id,
        Animation::new(std::time::Duration::from_millis(3600)).repeat(),
        |el, t| el.mt(px((t * std::f32::consts::TAU).sin() * 3.)),
    )
    .into_any_element()
}

static SIDEBAR_SPRITES: LazyLock<BTreeMap<&str, Arc<Image>>> = LazyLock::new(|| {
    [
        (
            "wizard-1",
            include_bytes!("../assets/topic-icons/sidebar/wizard-1.png").as_slice(),
        ),
        (
            "pinata",
            include_bytes!("../assets/topic-icons/sidebar/pinata.png").as_slice(),
        ),
        (
            "coffee-cup",
            include_bytes!("../assets/topic-icons/sidebar/coffee-cup.png").as_slice(),
        ),
    ]
    .into_iter()
    .map(|(slug, png)| {
        (
            slug,
            Arc::new(Image::from_bytes(ImageFormat::Png, png.to_vec())),
        )
    })
    .collect()
});

pub(super) fn sidebar_tile(icon: &TopicIcon) -> Div {
    icon_tile(icon, 34., 24., SIDEBAR_SPRITES.get(icon.hedgehog.as_str()))
}

pub(super) fn small_sidebar_tile(icon: &TopicIcon, size: f32) -> Div {
    icon_tile(
        icon,
        size,
        size * 24. / 34.,
        SIDEBAR_SPRITES.get(icon.hedgehog.as_str()),
    )
}

pub(super) fn tile(icon: &TopicIcon, size: f32) -> Div {
    icon_tile(icon, size, size * 0.76, None)
}

fn icon_tile(icon: &TopicIcon, size: f32, art_size: f32, sprite: Option<&Arc<Image>>) -> Div {
    let image = sprite
        .or_else(|| IMAGES.get(icon.hedgehog.as_str()))
        .unwrap_or(&IMAGES["wizard-1"]);
    let (_, background) = meep_shell::icons::inks(&icon.color);
    div()
        .flex_none()
        .size(px(size))
        .relative()
        .rounded_full()
        .bg(rgb(background))
        .overflow_hidden()
        .flex()
        .items_center()
        .justify_center()
        .child(
            img(image.clone())
                .flex_none()
                .size(px(art_size))
                .object_fit(ObjectFit::Contain),
        )
        .child(
            div()
                .absolute()
                .inset_0()
                .rounded_full()
                .border(px(1.))
                .border_color(meep_shell::icons::tile_edge()),
        )
}

pub(super) fn picker(topic: TopicId, icon: &TopicIcon, cx: &Context<Desktop>) -> Popover {
    let owner = cx.entity().downgrade();
    Popover::new(SharedString::from(format!("topic-icon-picker-{topic}")))
        .trigger(
            Button::new("change-topic-icon")
                .ghost()
                .compact()
                .p_0()
                .size(px(28.))
                .accessibility_label("Change topic icon")
                .tooltip("Change topic icon")
                .child(tile(icon, 20.)),
        )
        .content(move |_, w, cx| {
            let Some(desktop) = owner.upgrade() else {
                return div();
            };
            let Some(topic) = desktop
                .read(cx)
                .states
                .iter()
                .find(|s| s.topic.id == topic)
                .map(|s| &s.topic)
            else {
                return div();
            };
            let id = topic.id;
            let icon = topic.display_icon();
            let search = w.use_keyed_state("topic-hedgehog-search", cx, |w, cx| {
                InputState::new(w, cx).placeholder("Search hedgehogs")
            });
            let query = search_terms(&search.read(cx).value());
            let results: Vec<_> = ART
                .iter()
                .filter(|(slug, label, aliases, _)| matches_search(slug, label, aliases, &query))
                .collect();
            let choice = |value: &'static str,
                          label: &'static str,
                          image: Div,
                          selected: bool,
                          is_color: bool| {
                let owner = owner.clone();
                Button::new(value)
                    .ghost()
                    .compact()
                    .p_0()
                    .size(px(CELL))
                    .cursor_pointer()
                    .accessibility_label(label)
                    .tooltip(label)
                    .selected(selected)
                    .child(
                        div()
                            .size_full()
                            .flex()
                            .items_center()
                            .justify_center()
                            .rounded(px(10.))
                            .when(is_color, |cell| cell.rounded_full())
                            .when(selected, |cell| {
                                cell.border_2().border_color(rgb(ui::theme::color(ui::INK)))
                            })
                            .child(image),
                    )
                    .on_click(cx.listener(move |_, _, _, cx| {
                        let _ = owner.update(cx, |s, cx| {
                            if let Some(topic) = s.states.iter().find(|state| state.topic.id == id)
                            {
                                let mut icon = topic.topic.display_icon();
                                let field = if is_color {
                                    &mut icon.color
                                } else {
                                    &mut icon.hedgehog
                                };
                                if field != value {
                                    *field = value.into();
                                    s.issue(id, Command::SetTopicIcon { icon });
                                    cx.notify();
                                }
                            }
                        });
                        cx.notify();
                    }))
            };
            let mut hogs = ui::column().gap(px(GAP));
            for row in results.chunks(COLUMNS) {
                hogs = hogs.child(ui::row().flex_none().gap(px(GAP)).children(row.iter().map(
                    |&&(slug, label, _, _)| {
                        let preview = TopicIcon {
                            hedgehog: slug.into(),
                            color: icon.color.clone(),
                        };
                        choice(
                            slug,
                            label,
                            tile(&preview, 28.),
                            slug == icon.hedgehog,
                            false,
                        )
                    },
                )));
            }
            if results.is_empty() {
                hogs = hogs.child(ui::caption("No hedgehogs match your search.").py(px(8.)));
            }
            let colors = ui::row().gap(px(6.)).children(
                TopicIcon::COLORS
                    .into_iter()
                    .zip(["Blue", "Orange", "Green", "Pink", "Yellow", "Lime", "Clay"])
                    .map(|(color, label)| {
                        let swatch = div()
                            .size(px(22.))
                            .rounded_full()
                            .bg(rgb(meep_shell::icons::inks(color).1));
                        choice(color, label, swatch, color == icon.color, true)
                    }),
            );
            div().child(
                ui::column()
                    .w(px(COLUMNS as f32 * CELL + (COLUMNS - 1) as f32 * GAP))
                    .gap(px(8.))
                    .child(ui::caption("Background color"))
                    .child(colors)
                    .child(
                        Input::new(&search)
                            .aria_label("Search hedgehogs")
                            .prefix(Icon::new(Glyph::Search).size(px(14.)))
                            .cleanable(true),
                    )
                    .child(
                        div()
                            .id(SharedString::from(format!(
                                "topic-hedgehogs-{}",
                                query.join(" ")
                            )))
                            .max_h(px(220.))
                            .overflow_y_scroll()
                            .child(hogs),
                    ),
            )
        })
}

#[cfg(test)]
mod tests {
    use super::{ART, matches_search, search_terms};

    #[test]
    fn search_finds_pictured_details_without_knowing_the_icon_name() {
        let matching_slugs = |query: &str| {
            let terms = search_terms(query);
            ART.iter()
                .filter(|(slug, label, aliases, _)| matches_search(slug, label, aliases, &terms))
                .map(|&(slug, _, _, _)| slug)
                .collect::<Vec<_>>()
        };

        assert_eq!(matching_slugs("skeleton HOSPITAL"), ["x-ray"]);
        assert_eq!(matching_slugs("xray"), ["x-ray"]);
        assert!(matching_slugs("can watering").contains(&"gardener-1"));
        assert!(matching_slugs("skeleton watering").is_empty());
    }
}
