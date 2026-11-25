//! Element styles, resolved once per render instead of once per frame, and
//! the layout facts that decide which `Scroll`s can be cached regions.
//!
//! `style()` reads some fifty props per element, and every frame rebuilds
//! every element: an animation frame does it without the script changing
//! anything. So each node's style is resolved when the tree is parsed
//! (`tree`) and frames apply the stored refinement. Refining onto the base
//! element gives the same style as replaying the setters, because the stored
//! refinement is exactly what those setters write into an empty one.
//! Resolving is memoized by kind and props across renders (`Memo`), since
//! most props repeat.
use super::{container_base, static_style};
use gpui_kit::{
    AlignItems, DefiniteLength, Display, Edges, FlexDirection, Length, Position, Refineable, Size,
    Style, StyleRefinement, Styled, div,
};
use serde_json::Value;
use std::collections::HashMap;
use std::rc::Rc;

/// One element's resolved style. Containers also carry their full style
/// (base and props), which lays a region out, and the facts of it that
/// decide whether their children's sizes are fixed.
pub(super) struct Entry {
    pub(super) refinement: StyleRefinement,
    pub(super) container: Option<(StyleRefinement, Layout)>,
}

/// Resolved styles by element kind and props, kept across renders.
#[derive(Default)]
pub(super) struct Memo {
    palette: Option<[u32; 14]>,
    entries: HashMap<String, Rc<Entry>>,
}

/// The parts of a container's style that decide its children's sizes.
#[derive(Clone, Copy)]
pub(super) struct Layout {
    display: Display,
    direction: FlexDirection,
    align_items: Option<AlignItems>,
    align_self: Option<AlignItems>,
    position: Position,
    size: Size<Length>,
    min_size: Size<Length>,
    basis: Length,
    grow: f32,
    shrink: f32,
    has_margin: bool,
}

/// What a child needs to know about its parent to tell whether its own size
/// is fixed by the outside rather than by its content.
#[derive(Clone, Copy)]
pub(super) struct Parent {
    display: Display,
    direction: FlexDirection,
    align_items: Option<AlignItems>,
    width: bool,
    height: bool,
}

impl Parent {
    /// The view's body: a flex column filling the panel, which embeds the
    /// view as a cached view of a definite size (`ui.rs`).
    pub(super) fn body() -> Self {
        Self {
            display: Display::Flex,
            direction: FlexDirection::Column,
            align_items: None,
            width: true,
            height: true,
        }
    }
}

/// Where an element of `kind` with props `p` and style `entry` sits in
/// `parent`: whether it can be a cached region, and what it tells its own
/// children. Anything but a known container passes nothing down (text,
/// components, reveals): its children's sizes may follow content.
pub(super) fn place(
    kind: &str,
    p: &Value,
    entry: &Entry,
    parent: Option<Parent>,
) -> (bool, Option<Parent>) {
    let (Some((_, layout)), Some(parent)) = (&entry.container, parent) else {
        return (false, None);
    };
    let (width, height) = fixed_size(&parent, layout);
    let region = kind == "scroll" && width && height && region_candidate(p, layout);
    let inner = Parent {
        display: layout.display,
        direction: layout.direction,
        align_items: layout.align_items,
        width,
        height,
    };
    (region, Some(inner))
}

impl Memo {
    /// Colors are resolved into the entries, so a new palette starts over.
    /// The cap keeps a view that renders ever-new props from growing it.
    pub(super) fn prepare(&mut self) {
        let palette = palette();
        if self.palette != Some(palette) || self.entries.len() > 10_000 {
            self.entries.clear();
            self.palette = Some(palette);
        }
    }
    pub(super) fn palette(&self) -> [u32; 14] {
        self.palette.unwrap_or_else(palette)
    }
    pub(super) fn entry(&mut self, kind: &str, p: &Value) -> Rc<Entry> {
        let key = format!("{kind}\u{1}{p}");
        if let Some(entry) = self.entries.get(&key) {
            return entry.clone();
        }
        let refinement = if p.is_object() {
            static_style(div(), p).style().clone()
        } else {
            StyleRefinement::default()
        };
        let container = container_base(kind).map(|mut base| {
            let mut outer = base.style().clone();
            outer.refine(&refinement);
            let mut style = Style::default();
            style.refine(&outer);
            let layout = Layout {
                display: style.display,
                direction: style.flex_direction,
                align_items: style.align_items,
                align_self: style.align_self,
                position: style.position,
                size: style.size,
                min_size: style.min_size,
                basis: style.flex_basis,
                grow: style.flex_grow,
                shrink: style.flex_shrink,
                has_margin: style.margin != Edges::default(),
            };
            (outer, layout)
        });
        let entry = Rc::new(Entry {
            refinement,
            container,
        });
        // Handler IDs change on every render: such props never repeat.
        if !key.contains("\"$fn\"") {
            self.entries.insert(key, entry.clone());
        }
        entry
    }
}

/// The current palette.
pub(super) fn palette() -> [u32; 14] {
    std::array::from_fn(crate::sdk::ui::theme::get)
}

/// Whether the parent alone fixes the child's width and height, so laying
/// the child out from its style gives the same box as laying out its
/// content. Conservative: anything unclear counts as content-sized.
fn fixed_size(parent: &Parent, s: &Layout) -> (bool, bool) {
    if s.position == Position::Absolute {
        return (false, false);
    }
    let row = matches!(
        parent.direction,
        FlexDirection::Row | FlexDirection::RowReverse
    );
    let stretched = match s.align_self {
        Some(align) => align == AlignItems::Stretch,
        None => matches!(parent.align_items, None | Some(AlignItems::Stretch)),
    };
    // Along the parent's main axis the basis decides, then growing and
    // shrinking. Free space comes from the parent and siblings; the content
    // only matters through an automatic minimum size, which shrinking (or
    // growing past it) can run into. So: a fixed basis, or an auto basis
    // with a set size, and either a set minimum or no flexing at all.
    let main = |size: Length, min: Length, parent: bool| {
        let basis = match s.basis {
            Length::Auto => explicit(size, parent),
            basis => explicit(basis, parent),
        };
        let rigid = s.grow == 0. && s.shrink == 0.;
        parent && basis == Some(true) && (rigid || explicit(min, parent) == Some(true))
    };
    // Across it, a set size, or stretching to a fixed parent.
    let cross = |size: Length, parent: bool| explicit(size, parent).unwrap_or(stretched && parent);
    match parent.display {
        Display::Flex if row => (
            main(s.size.width, s.min_size.width, parent.width),
            cross(s.size.height, parent.height),
        ),
        Display::Flex => (
            cross(s.size.width, parent.width),
            main(s.size.height, s.min_size.height, parent.height),
        ),
        // Block children fill the width; their height follows content.
        Display::Block => (
            explicit(s.size.width, parent.width).unwrap_or(parent.width),
            explicit(s.size.height, parent.height).unwrap_or(false),
        ),
        _ => (false, false),
    }
}

/// A set size: fixed when absolute, fixed when relative to a fixed parent.
fn explicit(length: Length, parent: bool) -> Option<bool> {
    match length {
        Length::Definite(DefiniteLength::Absolute(_)) => Some(true),
        Length::Definite(DefiniteLength::Fraction(_)) => Some(parent),
        Length::Auto => None,
    }
}

/// Region roots stay simple: nothing that moves or offsets the box itself,
/// since the cached layout comes from the style alone.
fn region_candidate(p: &Value, s: &Layout) -> bool {
    !crate::script_motion::declared(p) && p["layer"].is_null() && !s.has_margin
}

#[cfg(test)]
mod tests {
    use super::super::tree::{Node, Tree};
    use super::*;
    use serde_json::json;

    /// The ids of the scrolls in `tree` that become regions.
    fn regions(tree: Value) -> Vec<String> {
        let tree = Tree::compile(tree, &mut Memo::default()).unwrap();
        let mut found = vec![];
        let mut stack: Vec<&Rc<Node>> = vec![&tree.root];
        while let Some(node) = stack.pop() {
            if node.region {
                found.push(node.key.to_string());
            }
            stack.extend(node.children.iter());
        }
        found.sort();
        found
    }
    fn el(t: &str, p: Value, c: Vec<Value>) -> Value {
        json!({"t": t, "p": p, "c": c})
    }
    fn scroll(id: &str) -> Value {
        el(
            "scroll",
            json!({"id": id}),
            vec![el("text", json!({"text": "x"}), vec![])],
        )
    }
    fn page(c: Vec<Value>) -> Value {
        el("page", json!({}), c)
    }

    #[test]
    fn a_scroll_filling_the_page_is_a_region() {
        assert_eq!(
            regions(page(vec![
                el("text", json!({"text": "Title"}), vec![]),
                scroll("list")
            ])),
            ["list"]
        );
    }

    #[test]
    fn growing_columns_pass_their_size_down() {
        let tree = page(vec![el(
            "column",
            json!({"grow": true}),
            vec![el(
                "row",
                json!({"grow": true, "align": "stretch"}),
                vec![
                    el("column", json!({"w": 200}), vec![scroll("side")]),
                    el("column", json!({"grow": true}), vec![scroll("main")]),
                ],
            )],
        )]);
        assert_eq!(regions(tree), ["main", "side"]);
    }

    #[test]
    fn content_can_size_a_scroll_in_a_row_or_a_block() {
        // A row centers its children, so their height follows content; along
        // the row a scroll's automatic minimum width does too.
        let row = page(vec![el("row", json!({}), vec![scroll("in-row")])]);
        assert!(regions(row).is_empty());
        let stretched = page(vec![el(
            "row",
            json!({"h": 300, "align": "stretch"}),
            vec![scroll("across")],
        )]);
        assert!(
            regions(stretched).is_empty(),
            "width along the row still follows content"
        );
        let block = page(vec![el("box", json!({"h": 300}), vec![scroll("in-box")])]);
        assert!(
            regions(block).is_empty(),
            "a block child's height follows content"
        );
    }

    #[test]
    fn a_set_size_counts_only_when_nothing_can_shrink_it_to_content() {
        let rigid = page(vec![el(
            "card",
            json!({"h": 120, "shrink": false}),
            vec![scroll("rigid")],
        )]);
        assert_eq!(regions(rigid), ["rigid"]);
        // May shrink, down to an automatic minimum that comes from content.
        let loose = page(vec![el("card", json!({"h": 120}), vec![scroll("loose")])]);
        assert!(regions(loose).is_empty());
    }

    #[test]
    fn region_roots_never_move_or_float() {
        let tree = page(vec![
            el("scroll", json!({"id": "margin", "mt": 8}), vec![]),
            el("scroll", json!({"id": "layer", "layer": 1}), vec![]),
            el(
                "scroll",
                json!({"id": "moving", "motion": {"animate": {"opacity": 1}}}),
                vec![],
            ),
            el(
                "scroll",
                json!({"id": "floating", "position": "absolute", "inset": 0}),
                vec![],
            ),
        ]);
        assert!(regions(tree).is_empty());
    }

    #[test]
    fn unknown_containers_pass_no_size_down() {
        let tree = page(vec![el(
            "reveal",
            json!({"open": true, "grow": true}),
            vec![scroll("revealed")],
        )]);
        assert!(regions(tree).is_empty());
    }

    #[test]
    fn memoized_styles_follow_the_palette() {
        let tree = el("box", json!({"bg": "canvas"}), vec![]);
        let mut memo = Memo::default();
        let before = Tree::compile(tree.clone(), &mut memo)
            .unwrap()
            .root
            .style
            .refinement
            .background
            .clone();
        let mut palette = crate::sdk::ui::theme::DEFAULT;
        palette[3] = 0x101010;
        crate::sdk::ui::theme::set(palette);
        let after = Tree::compile(tree, &mut memo)
            .unwrap()
            .root
            .style
            .refinement
            .background
            .clone();
        crate::sdk::ui::theme::set(crate::sdk::ui::theme::DEFAULT);
        assert_ne!(before, after, "a palette change must not reuse old colors");
    }
}
