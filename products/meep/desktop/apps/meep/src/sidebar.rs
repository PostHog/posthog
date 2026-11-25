//! Arranging the sidebar, as in View. Topics and views can be gathered into
//! named sections that fold away; items in no section sit above the first
//! one. Dragging an item or a section lifts it into a card under the pointer
//! and a line shows where it will land. A section is removed by ungrouping:
//! its items stay, loose, where it was.
use super::*;
use meep_ui::gpui_kit::component::{
    Icon,
    menu::{PopupMenu, PopupMenuItem},
};
use std::collections::HashSet;

/// The top of a section header that still drops an item above the section
/// (out of it) rather than into it.
const HEADER_EDGE: f32 = 0.35;

/// A sidebar entry's stable key in the stored layout.
pub(super) fn topic_key(id: TopicId) -> String {
    format!("topic:{}", id.0)
}
pub(super) fn view_key(id: Uuid) -> String {
    format!("view:{id}")
}

/// Where a drop lands. An item's `section` of `None` means the loose items
/// above the first section; `index` counts the destination as it is now,
/// travelling item included.
#[derive(Clone, Debug, PartialEq)]
pub(super) enum Drop {
    Item { section: Option<Uuid>, index: usize },
    Section { index: usize },
}

/// The sidebar as it is drawn: loose items, then each section's items.
/// Unknown or repeated keys in the stored layout are left out.
#[derive(Clone, Debug, PartialEq)]
pub(super) struct Arrangement {
    pub loose: Vec<String>,
    pub sections: Vec<Section>,
}

impl Layout {
    /// The section holding `key`, if any.
    pub(super) fn home(&self, key: &str) -> Option<Uuid> {
        self.sections
            .iter()
            .find(|s| s.items.iter().any(|k| k == key))
            .map(|s| s.id)
    }
}

impl Arrangement {
    /// `present` keys in their default order, placed by the stored layout.
    /// Keys the layout doesn't know go at the end of the loose items.
    pub(super) fn of(layout: &Layout, present: &[String]) -> Self {
        let here: HashSet<&str> = present.iter().map(String::as_str).collect();
        let mut grouped = HashSet::new();
        let sections: Vec<Section> = layout
            .sections
            .iter()
            .map(|section| Section {
                items: section
                    .items
                    .iter()
                    .filter(|k| here.contains(k.as_str()) && grouped.insert((*k).clone()))
                    .cloned()
                    .collect(),
                ..section.clone()
            })
            .collect();
        let mut seen = HashSet::new();
        let loose = layout
            .loose
            .iter()
            .chain(present)
            .filter(|k| {
                here.contains(k.as_str()) && !grouped.contains(*k) && seen.insert(k.as_str())
            })
            .cloned()
            .collect();
        Self { loose, sections }
    }
    pub(super) fn list(&self, section: Option<Uuid>) -> Option<&Vec<String>> {
        match section {
            None => Some(&self.loose),
            Some(id) => self.sections.iter().find(|s| s.id == id).map(|s| &s.items),
        }
    }
    fn list_mut(&mut self, section: Option<Uuid>) -> Option<&mut Vec<String>> {
        match section {
            None => Some(&mut self.loose),
            Some(id) => self
                .sections
                .iter_mut()
                .find(|s| s.id == id)
                .map(|s| &mut s.items),
        }
    }
    /// The section holding `key`, and its place there.
    pub(super) fn locate(&self, key: &str) -> Option<(Option<Uuid>, usize)> {
        if let Some(i) = self.loose.iter().position(|k| k == key) {
            return Some((None, i));
        }
        self.sections.iter().find_map(|s| {
            s.items
                .iter()
                .position(|k| k == key)
                .map(|i| (Some(s.id), i))
        })
    }
    /// Whether dropping `dragged` at `drop` would leave everything as it is.
    pub(super) fn unchanged(&self, dragged: &str, drop: &Drop) -> bool {
        match drop {
            Drop::Item { section, index } => self
                .locate(dragged)
                .is_some_and(|(from, at)| from == *section && (*index == at || *index == at + 1)),
            Drop::Section { index } => self
                .sections
                .iter()
                .position(|s| s.id.to_string() == dragged)
                .is_some_and(|at| *index == at || *index == at + 1),
        }
    }
    /// Moves `dragged` (an item key, or a section's id) to `drop`.
    pub(super) fn apply(&mut self, dragged: &str, drop: &Drop) -> bool {
        match drop {
            Drop::Item { section, index } => {
                let Some((from, at)) = self.locate(dragged) else {
                    return false;
                };
                if self.list(*section).is_none() {
                    return false;
                }
                let mut index = *index;
                if from == *section && at < index {
                    index -= 1;
                }
                let key = self.list_mut(from).expect("located").remove(at);
                let list = self.list_mut(*section).expect("checked");
                list.insert(index.min(list.len()), key);
                true
            }
            Drop::Section { index } => {
                let Some(at) = self
                    .sections
                    .iter()
                    .position(|s| s.id.to_string() == dragged)
                else {
                    return false;
                };
                let section = self.sections.remove(at);
                let index = if at < *index { index - 1 } else { *index };
                self.sections
                    .insert(index.min(self.sections.len()), section);
                true
            }
        }
    }
}

/// What an item's menu offers for its section.
#[derive(Clone)]
pub(super) enum SectionChoice {
    MoveTo { id: Uuid, name: String },
    Leave { name: String },
    New,
}

pub(super) fn section_choices(arrangement: &Arrangement, key: &str) -> Vec<SectionChoice> {
    let current = arrangement.locate(key).and_then(|(section, _)| section);
    let mut choices: Vec<SectionChoice> = arrangement
        .sections
        .iter()
        .filter(|s| Some(s.id) != current)
        .map(|s| SectionChoice::MoveTo {
            id: s.id,
            name: s.name.clone(),
        })
        .collect();
    if let Some(section) = current.and_then(|id| arrangement.sections.iter().find(|s| s.id == id)) {
        choices.push(SectionChoice::Leave {
            name: section.name.clone(),
        });
    }
    choices.push(SectionChoice::New);
    choices
}

/// The "Section" part of an item's menu: one plain item when there is
/// nothing to move to, otherwise a submenu.
pub(super) fn section_menu_items(
    m: PopupMenu,
    owner: WeakEntity<Desktop>,
    key: String,
    w: &mut Window,
    cx: &mut Context<PopupMenu>,
) -> PopupMenu {
    let Some(arrangement) = owner.upgrade().map(|e| e.read(cx).arrangement()) else {
        return m;
    };
    let choices = section_choices(&arrangement, &key);
    if let [SectionChoice::New] = choices.as_slice() {
        return m.item(section_item(&choices[0], &owner, &key));
    }
    let moves = choices
        .iter()
        .filter(|c| matches!(c, SectionChoice::MoveTo { .. }))
        .count();
    m.submenu_with_icon(
        Some(Icon::new(Glyph::Folder)),
        "Section",
        w,
        cx,
        move |mut sub, _, _| {
            sub = sub.min_w(px(168.));
            for (i, choice) in choices.iter().enumerate() {
                if i == moves && moves > 0 {
                    sub = sub.separator();
                }
                sub = sub.item(section_item(choice, &owner, &key));
            }
            sub
        },
    )
}

/// One of an item's section choices, as a menu row.
fn section_item(choice: &SectionChoice, owner: &WeakEntity<Desktop>, key: &str) -> PopupMenuItem {
    let owner = owner.clone();
    let key = key.to_owned();
    match choice {
        SectionChoice::MoveTo { id, name } => {
            let id = *id;
            PopupMenuItem::new(name.clone())
                .icon(Icon::new(Glyph::Folder))
                .on_click(move |_, _, cx| {
                    let _ = owner.update(cx, |s, cx| s.move_to_section(&key, Some(id), cx));
                })
        }
        SectionChoice::Leave { name } => PopupMenuItem::new(format!("Take out of {name}"))
            .icon(Icon::new(Glyph::FolderOpen))
            .on_click(move |_, _, cx| {
                let _ = owner.update(cx, |s, cx| s.move_to_section(&key, None, cx));
            }),
        SectionChoice::New => PopupMenuItem::new("New section…")
            .icon(Icon::new(Glyph::FolderPlus))
            .on_click(move |_, w, cx| {
                let _ = owner.update(cx, |s, cx| s.new_section_with(Some(&key), w, cx));
            }),
    }
}

/// A section header's menu: name it, or let its items go.
pub(super) fn section_menu(m: PopupMenu, owner: WeakEntity<Desktop>, id: Uuid) -> PopupMenu {
    let rename = owner.clone();
    m.min_w(px(168.))
        .item(
            PopupMenuItem::new("Rename section…")
                .icon(Icon::new(Glyph::Pencil))
                .on_click(move |_, w, cx| {
                    let _ = rename.update(cx, |s, cx| s.start_section_rename(id, w, cx));
                }),
        )
        .separator()
        .item(
            PopupMenuItem::new("Remove section")
                .icon(Icon::new(Glyph::FolderOpen))
                .on_click(move |_, w, cx| {
                    let _ = owner.update(cx, |s, cx| {
                        s.ungroup_section(id, cx);
                        s.focus.focus(w, cx);
                    });
                }),
        )
}

impl Desktop {
    /// Every sidebar entry that is drawn, in its default order.
    fn present(&self) -> Vec<String> {
        self.states
            .iter()
            .filter(|s| !s.archived)
            .map(|s| topic_key(s.topic.id))
            .chain(self.views.rows.iter().map(|v| view_key(v.id)))
            .collect()
    }
    pub(super) fn arrangement(&self) -> Arrangement {
        Arrangement::of(&self.layout, &self.present())
    }
    /// Shows and keeps `arrangement`.
    pub(super) fn arrange(&mut self, arrangement: Arrangement, cx: &mut Context<Self>) {
        self.layout.loose = arrangement.loose;
        // Items not drawn now (an archived topic) keep their section.
        let drawn: HashSet<String> = self.present().into_iter().collect();
        let previous = std::mem::take(&mut self.layout.sections);
        self.layout.sections = arrangement
            .sections
            .into_iter()
            .map(|mut s| {
                if let Some(old) = previous.iter().find(|p| p.id == s.id) {
                    s.items
                        .extend(old.items.iter().filter(|k| !drawn.contains(*k)).cloned());
                }
                s
            })
            .collect();
        self.save_layout();
        cx.notify();
    }
    pub(super) fn toggle_section(&mut self, id: Uuid, cx: &mut Context<Self>) {
        let mut arrangement = self.arrangement();
        if let Some(section) = arrangement.sections.iter_mut().find(|s| s.id == id) {
            section.collapsed = !section.collapsed;
            self.arrange(arrangement, cx);
        }
    }
    /// Moves `key` into `section`, at its end, or out of every section.
    pub(super) fn move_to_section(
        &mut self,
        key: &str,
        section: Option<Uuid>,
        cx: &mut Context<Self>,
    ) {
        let mut arrangement = self.arrangement();
        let index = arrangement.list(section).map_or(0, |l| l.len());
        if arrangement.apply(key, &Drop::Item { section, index }) {
            if let Some(s) =
                section.and_then(|id| arrangement.sections.iter_mut().find(|s| s.id == id))
            {
                s.collapsed = false;
            }
            self.arrange(arrangement, cx);
        }
    }
    /// Starts a section, holding `key` when given, and names it in place.
    pub(super) fn new_section_with(
        &mut self,
        key: Option<&str>,
        w: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let mut arrangement = self.arrangement();
        let id = Uuid::new_v4();
        arrangement.sections.push(Section {
            id,
            name: "New section".into(),
            collapsed: false,
            items: vec![],
        });
        if let Some(key) = key {
            arrangement.apply(
                key,
                &Drop::Item {
                    section: Some(id),
                    index: 0,
                },
            );
        }
        self.arrange(arrangement, cx);
        self.start_section_rename(id, w, cx);
    }
    /// Removes a section; its items stay, loose, where it was.
    pub(super) fn ungroup_section(&mut self, id: Uuid, cx: &mut Context<Self>) {
        let mut arrangement = self.arrangement();
        if let Some(at) = arrangement.sections.iter().position(|s| s.id == id) {
            let section = arrangement.sections.remove(at);
            arrangement.loose.extend(section.items);
            self.arrange(arrangement, cx);
        }
    }
    pub(super) fn start_section_rename(
        &mut self,
        id: Uuid,
        w: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let Some(name) = self
            .layout
            .sections
            .iter()
            .find(|s| s.id == id)
            .map(|s| s.name.clone())
        else {
            return;
        };
        self.renaming_section = Some(id);
        self.section_name.update(cx, |e, cx| {
            e.set_value(name, w, cx);
            e.focus(w, cx);
            e.select_all(w, cx);
        });
        cx.notify();
    }
    /// Ends a section rename, keeping a non-empty name when `keep`.
    pub(super) fn finish_section_rename(
        &mut self,
        keep: bool,
        w: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let Some(id) = self.renaming_section.take() else {
            return;
        };
        let name = self.section_name.read(cx).value().trim().to_owned();
        if keep
            && !name.is_empty()
            && name.chars().count() <= 80
            && let Some(section) = self.layout.sections.iter_mut().find(|s| s.id == id)
        {
            section.name = name;
            self.save_layout();
        }
        self.focus.focus(w, cx);
        cx.notify();
    }
    pub(super) fn set_drop(&mut self, source: &str, drop: Option<Drop>, cx: &mut Context<Self>) {
        let drop = drop.filter(|d| !self.arrangement().unchanged(source, d));
        if self.drop_hint != drop || self.drag_source.as_deref() != Some(source) {
            self.drop_hint = drop;
            self.drag_source = Some(source.to_owned());
            cx.notify();
        }
    }
    /// An item dragged over another item's row lands above it from the upper
    /// half and beneath it from the lower half.
    pub(super) fn hover_item_row(
        &mut self,
        target: &str,
        source: &str,
        bounds: Bounds<Pixels>,
        position: Point<Pixels>,
        cx: &mut Context<Self>,
    ) {
        if !bounds.contains(&position) {
            return;
        }
        let Some((section, at)) = self.arrangement().locate(target) else {
            return;
        };
        let lower = position.y > bounds.center().y;
        self.set_drop(
            source,
            Some(Drop::Item {
                section,
                index: at + usize::from(lower),
            }),
            cx,
        );
    }
    /// An item dragged onto a section header goes into the section: first when
    /// it is open, last when it is folded. The top edge of the first header
    /// drops it out of every section instead.
    pub(super) fn hover_header_with_item(
        &mut self,
        section: Uuid,
        source: &str,
        bounds: Bounds<Pixels>,
        position: Point<Pixels>,
        cx: &mut Context<Self>,
    ) {
        if !bounds.contains(&position) {
            return;
        }
        let arrangement = self.arrangement();
        let Some(k) = arrangement.sections.iter().position(|s| s.id == section) else {
            return;
        };
        let edge = bounds.top() + bounds.size.height * HEADER_EDGE;
        let drop = if k == 0 && position.y < edge {
            Drop::Item {
                section: None,
                index: arrangement.loose.len(),
            }
        } else {
            let target = &arrangement.sections[k];
            Drop::Item {
                section: Some(section),
                index: if target.collapsed {
                    target.items.len()
                } else {
                    0
                },
            }
        };
        self.set_drop(source, Some(drop), cx);
    }
    /// A section dragged over another header lands above it from the upper
    /// half and beneath its group from the lower half.
    pub(super) fn hover_header_with_section(
        &mut self,
        section: Uuid,
        source: &str,
        bounds: Bounds<Pixels>,
        position: Point<Pixels>,
        cx: &mut Context<Self>,
    ) {
        if !bounds.contains(&position) {
            return;
        }
        let Some(k) = self
            .arrangement()
            .sections
            .iter()
            .position(|s| s.id == section)
        else {
            return;
        };
        let lower = position.y > bounds.center().y;
        self.set_drop(
            source,
            Some(Drop::Section {
                index: k + usize::from(lower),
            }),
            cx,
        );
    }
    pub(super) fn leave_list(
        &mut self,
        bounds: Bounds<Pixels>,
        position: Point<Pixels>,
        cx: &mut Context<Self>,
    ) {
        if !bounds.contains(&position) && self.drop_hint.is_some() {
            self.drop_hint = None;
            cx.notify();
        }
    }
    pub(super) fn finish_drop(&mut self, dragged: &str, cx: &mut Context<Self>) {
        let drop = self.drop_hint.take();
        self.drag_source = None;
        if let Some(drop) = drop {
            let mut arrangement = self.arrangement();
            if arrangement.apply(dragged, &drop) {
                self.arrange(arrangement, cx);
                return;
            }
        }
        cx.notify();
    }
}

/// The card that follows the pointer: the row, lifted off the glass.
pub(super) struct Lifted {
    pub glyph: Glyph,
    pub title: String,
    pub trailing: Option<String>,
}
impl Render for Lifted {
    fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
        ui::row()
            .h(px(ui::nav::ROW))
            .w(px(
                super::navigation::TOPIC_SIDEBAR_WIDTH - 2. * ui::nav::INSET
            ))
            .px(px(ui::nav::PAD))
            .gap(px(8.))
            .rounded(px(ui::nav::RADIUS))
            .bg(rgb(ui::theme::color(ui::CANVAS)))
            .border_1()
            .border_color(ui::ink(0x0f))
            .shadow(vec![
                BoxShadow {
                    color: rgba(0x0000000d).into(),
                    offset: point(px(0.), px(1.)),
                    blur_radius: px(2.),
                    spread_radius: px(0.),
                    inset: false,
                },
                BoxShadow {
                    color: rgba(0x00000024).into(),
                    offset: point(px(0.), px(8.)),
                    blur_radius: px(24.),
                    spread_radius: px(-4.),
                    inset: false,
                },
            ])
            .child(ui::nav::glyph(self.glyph, true))
            .child(ui::nav::title(self.title.clone()))
            .when_some(self.trailing.clone(), |card, t| {
                card.child(
                    div()
                        .flex_none()
                        .text_size(px(11.))
                        .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                        .child(t),
                )
            })
    }
}

/// The insertion line: a short rule with a ring at its leading end, centred
/// on `y` in the gap between rows.
pub(super) fn drop_line(y: f32) -> Div {
    const RING: f32 = 7.;
    div()
        .absolute()
        .top(px(y - 1.))
        .left(px(ui::nav::PAD - RING / 2. + 2.))
        .right(px(4.))
        .h(px(2.))
        .rounded_full()
        .bg(rgb(ui::theme::color(ui::INK)))
        .child(
            div()
                .absolute()
                .left(px(-RING + 1.))
                .top(px(1. - RING / 2.))
                .size(px(RING))
                .rounded_full()
                .border_2()
                .border_color(rgb(ui::theme::color(ui::INK)))
                .bg(rgb(ui::theme::color(ui::CANVAS))),
        )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[::core::prelude::v1::test]
    fn items_move_within_and_between_sections() {
        let (a, b, c) = (
            TopicId(Uuid::from_u128(1)),
            TopicId(Uuid::from_u128(2)),
            Uuid::from_u128(3),
        );
        let product = Uuid::from_u128(9);
        let layout = Layout {
            sections: vec![Section {
                id: product,
                name: "Product".into(),
                collapsed: true,
                items: vec![topic_key(a), view_key(c)],
            }],
            loose: vec![topic_key(b)],
        };
        let present = [topic_key(a), topic_key(b), view_key(c)].map(String::from);
        let mut arr = Arrangement::of(&layout, &present);
        assert_eq!(arr.loose, [topic_key(b)]);
        assert_eq!(arr.sections[0].items, [topic_key(a), view_key(c)]);
        assert!(arr.sections[0].collapsed);
        // Dropping beside itself changes nothing; dropping lower moves it.
        assert!(arr.unchanged(
            &topic_key(a),
            &Drop::Item {
                section: Some(product),
                index: 1
            }
        ));
        assert!(arr.apply(
            &topic_key(a),
            &Drop::Item {
                section: Some(product),
                index: 2
            }
        ));
        assert_eq!(arr.sections[0].items, [view_key(c), topic_key(a)]);
        // Out to the loose items, then the section ungroups into them.
        assert!(arr.apply(
            &view_key(c),
            &Drop::Item {
                section: None,
                index: 0
            }
        ));
        assert_eq!(arr.loose, [view_key(c), topic_key(b)]);
    }
}
