//! A script's element tree, parsed once each time the script renders.
//!
//! The script hands over JSON (`{t, p, c}`). Everything the renderer needs
//! that stays the same until the next render is worked out here, once: each
//! element's identity, its resolved style, whether its parent alone decides
//! its size (so it can be a cached region) and whether the view's root
//! builds it (a sheet or dialog). Frames read these typed fields instead of
//! looking props up by name, and nothing is keyed by address.
use super::styles::{Entry, Memo, Parent};
use super::*;

pub(super) struct Node {
    /// One of `script::ELEMENTS` or `script_contract::COMPONENTS`.
    pub(super) kind: &'static str,
    /// The element's props, for the element-specific arms.
    pub(super) p: Value,
    /// Its identity: the `id` prop, else its position. Positions start with
    /// `r.`, so they never collide with a script's IDs.
    pub(super) key: SharedString,
    /// Its position (`r.0.2` is the root's first child's third).
    pub(super) path: SharedString,
    pub(super) children: Vec<Rc<Node>>,
    pub(super) style: Rc<Entry>,
    #[cfg(not(target_family = "wasm"))]
    pub(super) image: Option<images::Spec>,
    /// Its parent alone decides its size: it renders as a cached region.
    pub(super) region: bool,
    /// An absolute sheet or dialog (layer 2 or 3), built by the view's root
    /// so it is placed against the whole view, as CSS places `position:
    /// fixed`; built in place, a sheet declared inside a `Scroll` would cover
    /// only the scroll's content box and travel with it.
    pub(super) view_layer: bool,
}

/// A whole render: the root, and what the view handles apart from building.
pub(super) struct Tree {
    pub(super) root: Rc<Node>,
    /// Sheets and dialogs the view's root builds (see `layers`).
    pub(super) layers: Vec<Rc<Node>>,
    /// Text fields, which keep native state across renders (see `inputs`).
    pub(super) fields: Vec<Rc<Node>>,
    /// The palette its colors were resolved with.
    pub(super) palette: [u32; 14],
}

impl Tree {
    /// Parses a render. `value` has passed `script::check_tree`.
    pub(super) fn compile(value: Value, memo: &mut Memo) -> Result<Self, String> {
        memo.prepare();
        let mut found = Found::default();
        let at = Place {
            parent: Some(Parent::body()),
            search_layers: true,
        };
        let root = compile(value, "r".into(), at, memo, &mut found)?;
        Ok(Self {
            root,
            layers: found.layers,
            fields: found.fields,
            palette: memo.palette(),
        })
    }
}

impl Node {
    /// Parses an element built outside the render: a list row or a table
    /// cell. It is never a region or a layer, and holds no text fields.
    pub(super) fn fragment(
        value: Value,
        path: String,
        memo: &mut Memo,
    ) -> Result<Rc<Self>, String> {
        memo.prepare();
        let at = Place {
            parent: None,
            search_layers: false,
        };
        compile(value, path, at, memo, &mut Found::default())
    }
}

/// What a node's position tells it.
#[derive(Clone, Copy)]
struct Place {
    /// The parent's layout, when it is a known container whose size is set.
    parent: Option<Parent>,
    /// Sheets and dialogs are looked for only through plain containers: one
    /// under something that hides or rebuilds its children stays in place.
    search_layers: bool,
}

#[derive(Default)]
struct Found {
    layers: Vec<Rc<Node>>,
    fields: Vec<Rc<Node>>,
}

fn compile(
    value: Value,
    path: String,
    at: Place,
    memo: &mut Memo,
    found: &mut Found,
) -> Result<Rc<Node>, String> {
    let Value::Object(mut map) = value else {
        return Err("Elements must be objects".into());
    };
    let name = map.remove("t");
    let name = name.as_ref().and_then(Value::as_str).unwrap_or("");
    let kind = script::ELEMENTS
        .iter()
        .chain(COMPONENTS.iter())
        .copied()
        .find(|k| *k == name)
        .ok_or_else(|| format!("Unknown element \"{name}\""))?;
    let p = map.remove("p").unwrap_or(Value::Null);
    let style = memo.entry(kind, &p);
    let (region, inner) = styles::place(kind, &p, &style, at.parent);
    let view_layer = at.search_layers
        && p["position"] == "absolute"
        && p["layer"].as_u64().is_some_and(|layer| layer >= 2);
    let below = Place {
        parent: inner,
        // Plain containers: the kinds `container_base` knows.
        search_layers: at.search_layers
            && !view_layer
            && style.container.is_some()
            && !crate::script_motion::declared(&p),
    };
    let children = match map.remove("c") {
        Some(Value::Array(children)) => children
            .into_iter()
            .enumerate()
            .map(|(i, child)| compile(child, child_path(kind, &path, i), below, memo, found))
            .collect::<Result<_, _>>()?,
        _ => Vec::new(),
    };
    let key = p["id"]
        .as_str()
        .filter(|id| !id.is_empty())
        .map(SharedString::from)
        .unwrap_or_else(|| SharedString::from(path.clone()));
    let node = Rc::new(Node {
        kind,
        #[cfg(not(target_family = "wasm"))]
        image: (kind == "image").then(|| images::Spec::new(&p)),
        p,
        key,
        path: path.into(),
        children,
        style,
        region,
        view_layer,
    });
    if view_layer {
        found.layers.push(node.clone());
    }
    if matches!(
        kind,
        "input" | "textarea" | "date_picker" | "time_picker" | "block_editor"
    ) {
        found.fields.push(node.clone());
    }
    Ok(node)
}

/// Child `i`'s position. A hover card's or popover's content (every child
/// after the trigger) is numbered on its own, under `.content`.
fn child_path(kind: &str, path: &str, i: usize) -> String {
    match (kind, i) {
        ("hover_card" | "popover", 1..) => format!("{path}.content.{}", i - 1),
        _ => format!("{path}.{i}"),
    }
}

#[cfg(test)]
mod tests {
    // `super::*` includes GPUI's `test` attribute; tests use the built-in one.
    use super::*;
    use core::prelude::v1::test;
    use serde_json::json;

    fn compile(value: Value) -> Tree {
        Tree::compile(value, &mut Memo::default()).unwrap()
    }

    #[test]
    fn popover_content_keeps_its_own_numbering() {
        let tree = compile(json!({"t": "page", "c": [{"t": "popover", "c": [
            {"t": "button"}, {"t": "text"}, {"t": "text"},
        ]}]}));
        let popover = &tree.root.children[0];
        let paths: Vec<_> = popover
            .children
            .iter()
            .map(|c| c.path.to_string())
            .collect();
        assert_eq!(paths, ["r.0.0", "r.0.content.0", "r.0.content.1"]);
    }

    #[test]
    fn unknown_elements_are_refused() {
        let error = Tree::compile(
            json!({"t": "page", "c": [{"t": "blink"}]}),
            &mut Memo::default(),
        );
        assert!(error.is_err_and(|e| e.contains("blink")));
    }

    #[test]
    fn fields_and_view_layers_are_collected() {
        let tree = compile(json!({"t": "page", "c": [
            {"t": "input", "p": {"id": "q"}},
            {"t": "column", "c": [{"t": "textarea"}]},
            {"t": "box", "p": {"position": "absolute", "layer": 2, "id": "sheet"}, "c": [
                {"t": "box", "p": {"position": "absolute", "layer": 3, "id": "inner"}},
            ]},
            // Under motion a layer stays where it is.
            {"t": "column", "p": {"motion": {"animate": {"opacity": 1}}}, "c": [
                {"t": "box", "p": {"position": "absolute", "layer": 2, "id": "moving"}},
            ]},
        ]}));
        let fields: Vec<_> = tree.fields.iter().map(|f| f.key.to_string()).collect();
        assert_eq!(fields, ["q", "r.1.0"]);
        let layers: Vec<_> = tree.layers.iter().map(|l| l.key.to_string()).collect();
        assert_eq!(layers, ["sheet"], "nested and moving layers stay in place");
    }
}
