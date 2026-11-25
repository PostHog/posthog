use gpui::Pixels;

use super::node::{NodeKind, PaneNode};
use super::tree::{PaneTree, RootKind};

/// Upper bound on `normalize` passes. Every pass that changes anything
/// strictly reduces node count or nesting depth, so real dock layouts
/// converge in a small handful of passes; this is a generous ceiling against
/// a future rule change that fights another rule rather than a bound tuned
/// to today's rule set.
const MAX_NORMALIZE_PASSES: u32 = 64;

impl PaneTree {
    /// Collapse the tree to canonical shape.
    ///
    /// One post-order pass repeated to a fixpoint. This is the only place a
    /// container is removed for being empty, replacing the mutually recursive
    /// `remove_self_if_empty` pair the old implementation used. It needs no
    /// parent pointers and no deferred work, so the tree is self-consistent
    /// the instant an edit returns.
    ///
    /// Rules, applied bottom up:
    ///
    /// 1. An empty `Tabs` or `Split` is removed from its parent.
    /// 2. A `Split` with one child is replaced by that child. The child keeps
    ///    its own `NodeId` and inherits the split's slot size.
    /// 3. A `Split` whose child is a `Split` of the same axis splices that
    ///    child's children into itself.
    /// 4. `active_ix` is clamped.
    /// 5. The root is preserved according to [`RootKind`].
    ///
    /// Idempotent: `normalize(normalize(t)) == normalize(t)`.
    pub fn normalize(&mut self) {
        self.normalize_reporting();
    }

    /// [`Self::normalize`], reporting whether it changed anything.
    ///
    /// `edit` uses this instead of comparing whole trees: collapse is the only
    /// thing that can change a tree after a mutation has already reported what
    /// it did, so the two booleans together are exactly the answer, and no
    /// snapshot of the previous tree has to be kept to reach it.
    pub(crate) fn normalize_reporting(&mut self) -> bool {
        let changed = self.run_normalize_passes().1;
        debug_assert!(self.is_normalized(), "normalize did not reach a fixpoint");
        changed
    }

    /// Run passes until nothing changes, or until [`MAX_NORMALIZE_PASSES`] is
    /// exhausted. Returns the number of passes run, and whether any pass
    /// changed the tree.
    ///
    /// Split out from [`Self::normalize`] so a `#[cfg(test)]` caller can pin
    /// how many passes convergence actually takes, without widening the
    /// public API with a pass count nobody outside tests needs.
    fn run_normalize_passes(&mut self) -> (u32, bool) {
        let mut passes = 0;
        let mut changed = true;
        let mut any_change = false;
        // Bounded because every pass that changes anything strictly reduces
        // node count or nesting depth.
        while changed && passes < MAX_NORMALIZE_PASSES {
            changed = false;
            normalize_node(self.root_mut(), &mut changed);
            collapse_root(self, &mut changed);
            any_change |= changed;
            passes += 1;
        }

        // `debug_assert!` in `normalize` disappears in release builds, so a
        // desktop build left silently short of the fixpoint would otherwise
        // render a non-canonical layout with no trace of why. This keeps the
        // failure observable without turning it into a user-facing panic:
        // rendering a slightly non-canonical layout beats crashing the app.
        if changed {
            tracing::warn!(
                passes,
                "PaneTree::normalize exhausted {MAX_NORMALIZE_PASSES} passes without reaching \
                 a fixpoint; the tree may still contain an empty container, a single-child \
                 split, same-axis split nesting, or an unclamped Tabs active_ix"
            );
        }

        (passes, any_change)
    }

    /// Test-only hook so a test can pin how many passes convergence takes,
    /// without exposing a pass count through the public `normalize` API.
    #[cfg(test)]
    pub(crate) fn normalize_pass_count_for_test(&mut self) -> u32 {
        self.run_normalize_passes().0
    }

    /// Whether the tree satisfies every structural invariant.
    pub(crate) fn is_normalized(&self) -> bool {
        let mut ok = true;
        let root_id = self.root().id();
        self.root().walk(&mut |node| match node.kind_ref() {
            NodeKind::Split {
                children,
                sizes,
                axis,
            } => {
                ok &= children.len() == sizes.len();
                // The root may legitimately be an empty or single-child split.
                if node.id() != root_id {
                    ok &= children.len() > 1;
                }
                ok &= !children.iter().any(|child| {
                    matches!(child.kind_ref(), NodeKind::Split { axis: inner, .. } if inner == axis)
                });
            }
            NodeKind::Tabs { panels, active_ix } => {
                ok &= panels.is_empty() || *active_ix < panels.len();
                if node.id() != root_id {
                    ok &= !panels.is_empty();
                }
            }
        });
        ok
    }
}

fn normalize_node(node: &mut PaneNode, changed: &mut bool) {
    match node.kind_mut() {
        NodeKind::Tabs { panels, active_ix } => {
            let clamped = (*active_ix).min(panels.len().saturating_sub(1));
            if *active_ix != clamped {
                *active_ix = clamped;
                *changed = true;
            }
        }
        NodeKind::Split {
            axis,
            children,
            sizes,
        } => {
            let axis = *axis;

            for child in children.iter_mut() {
                normalize_node(child, changed);
            }

            // Rule 1: drop empty children.
            let mut ix = 0;
            while ix < children.len() {
                if is_empty_container(&children[ix]) {
                    children.remove(ix);
                    sizes.remove(ix);
                    *changed = true;
                } else {
                    ix += 1;
                }
            }

            // Rule 2: a single-child split child is replaced by its child,
            // which inherits the slot size the split occupied. The child is
            // moved out rather than cloned — it can carry an arbitrarily deep
            // subtree, and this runs on every edit.
            for ix in 0..children.len() {
                let is_single = matches!(
                    children[ix].kind_ref(),
                    NodeKind::Split { children: inner, .. } if inner.len() == 1
                );
                if !is_single {
                    continue;
                }
                let NodeKind::Split {
                    children: inner, ..
                } = children[ix].kind_mut()
                else {
                    continue;
                };
                let replacement = inner.remove(0);
                children[ix] = replacement;
                *changed = true;
            }

            // Rule 3: splice same-axis nesting.
            let mut ix = 0;
            while ix < children.len() {
                let same_axis = matches!(
                    children[ix].kind_ref(),
                    NodeKind::Split { axis: inner, .. } if *inner == axis
                );
                if !same_axis {
                    ix += 1;
                    continue;
                }

                // Taken, not cloned: the spliced children move up a level
                // rather than being copied and discarded.
                let NodeKind::Split {
                    children: inner,
                    sizes: inner_sizes,
                    ..
                } = children[ix].kind_mut()
                else {
                    ix += 1;
                    continue;
                };
                let inner = std::mem::take(inner);
                let inner_sizes = std::mem::take(inner_sizes);

                let slot = sizes[ix];
                let inner_sizes = distribute_slot(slot, inner_sizes);
                let count = inner.len();
                children.splice(ix..=ix, inner);
                sizes.splice(ix..=ix, inner_sizes);
                ix += count;
                *changed = true;
            }
        }
    }
}

/// Spread an outer slot size across the inner sizes that replace it.
///
/// When the outer slot is unconstrained the inner sizes pass through. When it
/// is fixed and every inner size is known, they are scaled to fill the slot;
/// otherwise the slot is dropped, matching how an unconstrained child behaves.
fn distribute_slot(slot: Option<Pixels>, inner: Vec<Option<Pixels>>) -> Vec<Option<Pixels>> {
    let Some(slot) = slot else { return inner };
    // `Option<Pixels>` has no `Sum` impl; fold so one unknown size makes the
    // whole total unknown.
    let total = inner
        .iter()
        .try_fold(Pixels::ZERO, |acc, size| size.map(|size| acc + size));
    match total {
        Some(total) if total > Pixels::ZERO => inner
            .into_iter()
            .map(|size| size.map(|size| size * (slot / total)))
            .collect(),
        _ => inner,
    }
}

fn is_empty_container(node: &PaneNode) -> bool {
    match node.kind_ref() {
        NodeKind::Split { children, .. } => children.is_empty(),
        NodeKind::Tabs { panels, .. } => panels.is_empty(),
    }
}

/// Rule 5. A `RootKind::Split` tree keeps a split root no matter what, so an
/// empty center still serializes as a `StackPanel`. A `RootKind::Any` tree
/// lets rule 2 collapse the root like any other node.
fn collapse_root(tree: &mut PaneTree, changed: &mut bool) {
    if tree.root_kind() == RootKind::Split {
        return;
    }

    let replacement = match tree.root().kind_ref() {
        NodeKind::Split { children, .. } if children.len() == 1 => Some(children[0].clone()),
        _ => None,
    };

    if let Some(replacement) = replacement {
        tree.replace_root(replacement);
        *changed = true;
    }
}

#[cfg(test)]
mod tests {
    use super::super::*;
    use gpui::{Axis, Pixels, px};

    fn panel(n: u64) -> PanelId {
        PanelId::from_u64(n)
    }

    #[test]
    fn empty_tab_groups_are_dropped() {
        let mut tree = PaneTree::new(RootKind::Split);
        let root = tree.root().id();
        tree.push_tabs_for_test(root, vec![]);
        tree.push_tabs_for_test(root, vec![panel(1)]);

        tree.normalize();

        // The empty tab group is dropped by rule 1, leaving the root split
        // holding the one surviving child.
        assert!(
            matches!(tree.root().kind(), PaneRef::Split { children, .. } if children.len() == 1)
        );
        assert_eq!(tree.panels().collect::<Vec<_>>(), vec![panel(1)]);
    }

    #[test]
    fn a_single_child_split_is_replaced_by_its_child_keeping_the_child_id() {
        let mut tree = PaneTree::new(RootKind::Any);
        let outer = tree.set_root_split_for_test(Axis::Horizontal);
        let inner = tree.push_split_for_test(outer, Axis::Vertical, Some(px(120.)));
        let tabs = tree.push_tabs_for_test(inner, vec![panel(1)]);

        tree.normalize();

        assert_eq!(tree.root().id(), tabs, "child keeps its own NodeId");
        assert!(tree.find_node(inner).is_none());
    }

    #[test]
    fn a_collapsing_split_hands_its_slot_size_to_the_child() {
        let mut tree = PaneTree::new(RootKind::Split);
        let root = tree.root().id();
        let inner = tree.push_split_for_test(root, Axis::Vertical, Some(px(300.)));
        tree.push_tabs_for_test(inner, vec![panel(1)]);
        tree.push_tabs_for_test(root, vec![panel(2)]);

        tree.normalize();

        let PaneRef::Split { sizes, .. } = tree.root().kind() else {
            panic!()
        };
        assert_eq!(
            sizes[0],
            Some(px(300.)),
            "the child inherits the collapsed split's slot"
        );
    }

    #[test]
    fn same_axis_nesting_is_spliced_into_the_parent() {
        let mut tree = PaneTree::new(RootKind::Split);
        tree.set_root_axis_for_test(Axis::Horizontal);
        let root = tree.root().id();
        tree.push_tabs_for_test(root, vec![panel(1)]);
        let inner = tree.push_split_for_test(root, Axis::Horizontal, None);
        tree.push_tabs_for_test(inner, vec![panel(2)]);
        tree.push_tabs_for_test(inner, vec![panel(3)]);

        tree.normalize();

        let PaneRef::Split { children, axis, .. } = tree.root().kind() else {
            panic!()
        };
        assert_eq!(axis, Axis::Horizontal);
        assert_eq!(
            children.len(),
            3,
            "the inner split's children are spliced in"
        );
        assert_eq!(
            tree.panels().collect::<Vec<_>>(),
            vec![panel(1), panel(2), panel(3)],
            "order is preserved"
        );
    }

    #[test]
    fn active_index_is_clamped_to_the_panel_count() {
        let mut tree = PaneTree::new(RootKind::Any);
        let tabs = tree.set_root_tabs_for_test(vec![panel(1), panel(2)], 9);

        tree.normalize();

        let PaneRef::Tabs { active_ix, .. } = tree.find_node(tabs).unwrap().kind() else {
            panic!()
        };
        assert_eq!(active_ix, 1);
    }

    #[test]
    fn a_split_root_survives_being_emptied() {
        let mut tree = PaneTree::new(RootKind::Split);
        let root = tree.root().id();
        tree.push_tabs_for_test(root, vec![]);

        tree.normalize();

        assert!(
            matches!(tree.root().kind(), PaneRef::Split { children, .. } if children.is_empty()),
            "the center must still serialize as a StackPanel when empty"
        );
    }

    /// Rule 3 splices a same-axis child's slots into the parent, scaling them
    /// to the slot they replace. When one inner slot is unconstrained there is
    /// no total to scale against, so they pass through — and then the known
    /// ones are absolute values that no longer relate to the space they landed
    /// in. This pins what actually happens, so a future change to
    /// `distribute_slot` has to decide about this case deliberately.
    #[test]
    fn a_same_axis_splice_with_one_unknown_inner_size_passes_them_through() {
        let mut tree = PaneTree::new(RootKind::Split);
        let root = tree.root().id();
        let inner = tree.push_split_for_test(root, Axis::Horizontal, Some(px(400.)));
        tree.push_sized_tabs_for_test(inner, vec![panel(1)], Some(px(100.)));
        tree.push_sized_tabs_for_test(inner, vec![panel(2)], None);

        tree.normalize();

        let PaneRef::Split { sizes, .. } = tree.root().kind() else {
            panic!()
        };
        assert_eq!(
            sizes,
            &[Some(px(100.)), None],
            "an unknown inner size leaves every sibling unscaled; the 400px \
             slot they replaced constrains nothing"
        );
    }

    /// Dropping a container mid-row hands its space to nobody in the tree —
    /// the surviving slots keep their absolute sizes and no longer sum to
    /// anything in particular. The renderer's own resizable state is what
    /// redistributes on the next layout pass.
    #[test]
    fn removing_a_middle_container_leaves_its_siblings_untouched() {
        let mut tree = PaneTree::new(RootKind::Split);
        let root = tree.root().id();
        tree.push_sized_tabs_for_test(root, vec![panel(1)], Some(px(400.)));
        tree.push_sized_tabs_for_test(root, vec![], Some(px(800.)));
        tree.push_sized_tabs_for_test(root, vec![panel(3)], Some(px(400.)));

        tree.normalize();

        let PaneRef::Split {
            sizes, children, ..
        } = tree.root().kind()
        else {
            panic!()
        };
        assert_eq!(children.len(), 2);
        assert_eq!(
            sizes,
            &[Some(px(400.)), Some(px(400.))],
            "the survivors keep their own sizes; the 800px the empty group \
             held is not handed to either of them here"
        );
    }

    #[test]
    fn normalize_is_idempotent() {
        let mut tree = PaneTree::new(RootKind::Split);
        let root = tree.root().id();
        let inner = tree.push_split_for_test(root, Axis::Horizontal, None);
        tree.push_tabs_for_test(inner, vec![panel(1)]);
        tree.push_tabs_for_test(inner, vec![]);
        tree.push_tabs_for_test(root, vec![panel(2)]);

        tree.normalize();
        let once = tree.clone();
        tree.normalize();

        assert_eq!(once, tree);
    }

    #[test]
    fn same_axis_splice_scales_inner_sizes_to_fill_the_outer_slot() {
        // Every other test that reaches a same-axis splice pushes children
        // with an unknown (`None`) size, so it only ever exercises
        // `distribute_slot`'s pass-through branches. This is the one test
        // that gives every sibling a known size, forcing the scaling arm.
        let mut tree = PaneTree::new(RootKind::Split);
        let root = tree.root().id();
        let inner = tree.push_split_for_test(root, Axis::Horizontal, Some(px(400.)));
        tree.push_sized_tabs_for_test(inner, vec![panel(1)], Some(px(50.)));
        tree.push_sized_tabs_for_test(inner, vec![panel(2)], Some(px(150.)));

        tree.normalize();

        let PaneRef::Split { sizes, .. } = tree.root().kind() else {
            panic!()
        };
        assert_eq!(
            sizes,
            &[Some(px(100.)), Some(px(300.))],
            "sizes scale by the outer/inner ratio (400/200 = 2x), not by its reverse"
        );
        let total: Pixels = sizes.iter().flatten().copied().sum();
        assert_eq!(
            total,
            px(400.),
            "the scaled sizes sum back to the outer slot"
        );
    }

    #[test]
    fn normalize_converges_within_two_passes_on_an_adversarial_tree() {
        // root(H) -> D(V) -> A(H) -> { empty, B(V) -> C(V) -> [leaf1, leaf2] }
        //
        // `RootKind::Any` lets rule 5 collapse the root itself, so this tree
        // combines every rule at once: single-child splits nested five
        // levels deep (root, D, A, B all start single-child), an empty
        // container dropped mid-chain (under A), and same-axis nesting
        // spliced twice (C into B, then the surviving B into D). Everything
        // still has to bottom out at a fixpoint within 2 passes: one pass
        // that resolves every rule bottom-up plus the root collapse, one
        // pass that confirms nothing is left to change.
        let mut tree = PaneTree::new(RootKind::Any);
        let root = tree.root().id();
        let d = tree.push_split_for_test(root, Axis::Vertical, None);
        let a = tree.push_split_for_test(d, Axis::Horizontal, None);
        tree.push_tabs_for_test(a, vec![]);
        let b = tree.push_split_for_test(a, Axis::Vertical, None);
        let c = tree.push_split_for_test(b, Axis::Vertical, None);
        tree.push_tabs_for_test(c, vec![panel(1)]);
        tree.push_tabs_for_test(c, vec![panel(2)]);

        let passes = tree.normalize_pass_count_for_test();

        assert!(
            passes <= 2,
            "expected the fixpoint within 2 passes, took {passes}"
        );
        assert!(tree.is_normalized());
        assert_eq!(
            tree.panels().collect::<Vec<_>>(),
            vec![panel(1), panel(2)],
            "every panel survives the collapse, in order"
        );
    }
}
