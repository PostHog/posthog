//! Cached regions: large subtrees, sized by their parent, that skip build,
//! layout and paint on frames that don't change them.
//!
//! GPUI draws a view again when anything inside it animates, hovers or
//! scrolls, so a spinner in a header used to rebuild and lay out every row of
//! a list sixty times a second. A `Scroll` whose size comes from its parent,
//! never from its content (`styles::fixed_size`), is rendered by its own
//! child view and embedded as a cached `ViewElement`: GPUI reuses its last
//! layout and paint until the region itself changes.
//!
//! Changes GPUI sees (hover, scroll, motion, focus, a text field inside the
//! region) notify the region view directly. Everything else a region's
//! content depends on is in `BuildInputs`, compared on every frame: when it
//! changes the view's epoch moves on, and a region that has not rendered at
//! the current epoch is invalidated for the frame being drawn.
use super::{Build, Editor, Node, Tree};
use gpui_kit::*;
use std::collections::{HashMap, HashSet};
use std::rc::Rc;

/// The script view's regions and what they render from this frame.
///
/// A region belongs to whoever embedded it: the script view or a region
/// around it. An owner prunes its own regions, and only when it renders,
/// since a cached owner keeps replaying the regions it embedded last.
#[derive(Default)]
pub(super) struct Regions {
    views: HashMap<String, Entity<Region>>,
    /// The regions each owner embedded when it last rendered.
    children: HashMap<String, Vec<String>>,
    /// The regions owners rendering right now have embedded so far.
    rendering: HashMap<String, HashSet<String>>,
    epoch: u64,
    inputs: Option<BuildInputs>,
}

/// Everything `Build` reads apart from GPUI's own state (hover, scroll,
/// motion, focus), so everything a reused region could be out of date with.
/// Derived from the `Build` itself, and `new` names every field of it: a
/// new field does not compile until it is either compared here or shown to
/// be fixed for the view's lifetime.
pub(super) struct BuildInputs {
    /// The parsed render, styles included: a new palette renders anew.
    tree: Option<Rc<Tree>>,
    read_only: bool,
    /// The text fields' entities: content inside a region embeds them.
    editors: Vec<(String, EntityId)>,
    /// The dragged element and how far it has moved: it follows the pointer.
    drag: Option<(String, Point<Pixels>)>,
}

impl BuildInputs {
    pub(super) fn new(build: &Build, tree: Option<Rc<Tree>>) -> Self {
        let Build {
            read_only,
            inputs,
            shared,
            // Fixed for the view's lifetime.
            scope: _,
            weak: _,
            // Set only inside a region's own render.
            region_root: _,
            region_key: _,
            // Follows from where the region sits in the tree.
            control: _,
        } = build;
        let mut editors: Vec<_> = inputs
            .iter()
            .map(|(key, editor)| {
                let id = match editor {
                    Editor::Line(e) => e.entity_id(),
                    Editor::Area(e) => e.entity_id(),
                    Editor::Date(e, _) => e.entity_id(),
                    Editor::Time(e) => e.entity_id(),
                    Editor::Blocks(e) => e.entity_id(),
                };
                (key.clone(), id)
            })
            .collect();
        editors.sort();
        // Of the shared state, only a drag is read while building; the rest
        // (row caches, scroll handles, handler maps) follows the tree or is
        // written, not read, by `Build`.
        let drag = shared
            .drag
            .borrow()
            .as_ref()
            .map(|d| (d.key.clone(), d.delta()));
        Self {
            tree,
            read_only: *read_only,
            editors,
            drag,
        }
    }
    /// Whether a region built from `self` could differ from one built from
    /// `other`. Trees compare by identity: the previous one is still held,
    /// so a new one cannot reuse its address.
    fn same_as(&self, other: &Self) -> bool {
        fn same<T>(a: &Option<Rc<T>>, b: &Option<Rc<T>>) -> bool {
            match (a, b) {
                (Some(a), Some(b)) => Rc::ptr_eq(a, b),
                (None, None) => true,
                _ => false,
            }
        }
        same(&self.tree, &other.tree)
            && self.read_only == other.read_only
            && self.editors == other.editors
            && self.drag == other.drag
    }
}

/// The script view, as the owner of the regions it embeds directly.
const VIEW: &str = "";

impl Regions {
    /// Called before the view builds with what it builds from.
    pub(super) fn begin(&mut self, inputs: BuildInputs) {
        if !self
            .inputs
            .as_ref()
            .is_some_and(|last| last.same_as(&inputs))
        {
            self.epoch += 1;
        }
        self.inputs = Some(inputs);
        self.start(VIEW);
    }
    /// Called after the view built.
    pub(super) fn end(&mut self) {
        self.finish(VIEW);
    }
    fn start(&mut self, owner: &str) {
        self.rendering.insert(owner.to_owned(), HashSet::new());
    }
    /// Drops the regions `owner` no longer embeds, with theirs.
    fn finish(&mut self, owner: &str) {
        let now = self.rendering.remove(owner).unwrap_or_default();
        let before = self
            .children
            .insert(owner.to_owned(), now.iter().cloned().collect())
            .unwrap_or_default();
        for key in before.iter().filter(|key| !now.contains(*key)) {
            self.remove(key);
        }
    }
    fn remove(&mut self, key: &str) {
        self.views.remove(key);
        for child in self.children.remove(key).unwrap_or_default() {
            self.remove(&child);
        }
    }
    #[cfg(feature = "ui-tests")]
    pub(super) fn keys(&self) -> Vec<String> {
        let mut keys: Vec<String> = self.views.keys().map(|k| k.replace('\u{1}', "/")).collect();
        keys.sort();
        keys
    }
}

/// One region: renders its node with the view's `Build`.
pub(super) struct Region {
    key: Rc<str>,
    build: Build,
    node: Rc<Node>,
    epoch: u64,
    /// The epoch this region last rendered at.
    rendered: Option<u64>,
}

#[cfg(feature = "ui-tests")]
thread_local! {
    static DISABLED: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}
/// Tests compare layouts with and without regions.
#[cfg(feature = "ui-tests")]
pub fn set_enabled(enabled: bool) {
    DISABLED.with(|d| d.set(!enabled));
}

/// The region element for `node`, or `None` to build it inline.
pub(super) fn embed(
    build: &Build,
    node: &Rc<Node>,
    _window: &mut Window,
    cx: &mut App,
) -> Option<AnyElement> {
    #[cfg(feature = "ui-tests")]
    if DISABLED.with(|d| d.get()) {
        return None;
    }
    if !node.region
        || build
            .region_root
            .as_ref()
            .is_some_and(|root| Rc::ptr_eq(root, node))
    {
        return None;
    }
    let (outer, _) = node.style.container.as_ref()?;
    let mut regions = build.shared.regions.borrow_mut();
    let owner = build.region_key.as_deref().unwrap_or(VIEW);
    let key = match owner {
        VIEW => node.key.to_string(),
        // A separator no script `id` contains, so a nested key can't equal
        // a top-level one.
        owner => format!("{owner}\u{1}{}", node.key),
    };
    // A repeated `id` would make two regions share one view.
    if !regions
        .rendering
        .entry(owner.to_owned())
        .or_default()
        .insert(key.clone())
    {
        return None;
    }
    let epoch = regions.epoch;
    let view = regions
        .views
        .entry(key.clone())
        .or_insert_with(|| {
            cx.new(|_| Region {
                key: key.into(),
                build: build.clone(),
                node: node.clone(),
                epoch,
                rendered: None,
            })
        })
        .clone();
    drop(regions);
    let current = view.update(cx, |region, _| {
        region.build = build.clone();
        region.node = node.clone();
        region.epoch = epoch;
        region.rendered == Some(epoch)
    });
    if !current {
        cx.notify(view.entity_id());
    }
    // Independent: the script view renders on every frame anything in it
    // animates, and that must not redraw the regions it embeds.
    Some(view.cached(outer.clone()).into_any_element())
}

impl Render for Region {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        self.rendered = Some(self.epoch);
        self.build.shared.perf.borrow_mut().region_renders += 1;
        let build = Build {
            region_root: Some(self.node.clone()),
            region_key: Some(self.key.clone()),
            ..self.build.clone()
        };
        self.build.shared.regions.borrow_mut().start(&self.key);
        let element = build.node(&self.node, window, cx);
        self.build.shared.regions.borrow_mut().finish(&self.key);
        element
    }
}

/// Regions are cached views nested in the script view's own cached view.
/// When an outer cache is replayed, the views inside it are not visited, so
/// their recorded ranges go stale; they must render, not replay, next time.
#[cfg(all(test, feature = "ui-tests"))]
mod cache_tests {
    // The glob below includes GPUI's `test`; `#[gpui::test]` expands to the
    // built-in one.
    use core::prelude::v1::test;
    use gpui_test as gpui;
    use gpui_test::{prelude::*, *};

    struct Child;
    impl Render for Child {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            canvas(
                |_, window, _| {
                    window.with_element_state::<usize, _>(&GlobalElementId::default(), |_, _| {
                        ((), 0)
                    });
                },
                |_, _, _, _| {},
            )
            .size_full()
        }
    }

    struct Parent {
        child: Entity<Child>,
        independent: bool,
    }
    impl Render for Parent {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let child = self
                .child
                .clone()
                .cached(StyleRefinement::default().size_full());
            div().size_full().child(if self.independent {
                child.independent()
            } else {
                child
            })
        }
    }

    /// Element states recorded before the parent, so that changing their
    /// number moves every later range without moving any bounds.
    struct Root {
        before: usize,
        parent: Entity<Parent>,
    }
    impl Render for Root {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let before = self.before;
            div()
                .size_full()
                .child(
                    canvas(
                        move |_, window, _| {
                            for _ in 0..before {
                                window.with_element_state::<usize, _>(
                                    &GlobalElementId::default(),
                                    |_, _| ((), 0),
                                );
                            }
                        },
                        |_, _, _, _| {},
                    )
                    .size(px(0.)),
                )
                .child(
                    self.parent
                        .clone()
                        .cached(StyleRefinement::default().size_full()),
                )
        }
    }

    fn replay_then_render(cx: &mut TestAppContext, independent: bool) {
        let window = cx.open_window(size(px(400.), px(300.)), |_, cx| {
            let child = cx.new(|_| Child);
            Root {
                before: 100,
                parent: cx.new(|_| Parent { child, independent }),
            }
        });
        let draw = |cx: &mut TestAppContext| {
            cx.update_window(window.into(), |_, window, cx| window.draw(cx).clear(cx))
                .unwrap();
        };
        draw(cx);
        // The parent's cache is replayed at lower offsets; the child is not visited.
        window
            .update(cx, |root, _, cx| {
                root.before = 0;
                cx.notify();
            })
            .unwrap();
        draw(cx);
        // The parent renders; the child must not replay its stale ranges.
        window
            .update(cx, |root, _, cx| {
                root.parent.update(cx, |_, cx| cx.notify())
            })
            .unwrap();
        draw(cx);
        draw(cx);
    }

    #[gpui::test]
    fn an_independent_view_renders_after_its_parent_was_replayed(cx: &mut TestAppContext) {
        replay_then_render(cx, true);
    }

    #[gpui::test]
    fn a_cached_view_renders_after_its_parent_was_replayed(cx: &mut TestAppContext) {
        replay_then_render(cx, false);
    }
}
