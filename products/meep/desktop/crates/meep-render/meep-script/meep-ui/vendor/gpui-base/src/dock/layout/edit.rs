use std::collections::HashMap;

use gpui::Pixels;

use crate::Placement;

use super::node::{NodeId, NodeKind, PaneNode, PanelId};
use super::tree::PaneTree;

/// Where a panel should land.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum InsertTarget {
    /// Into an existing tab group, optionally at a specific index.
    Tabs {
        node: NodeId,
        ix: Option<usize>,
        activate: bool,
    },
    /// Beside an existing node, creating a new tab group for the panel.
    Split {
        node: NodeId,
        placement: Placement,
        size: Option<Pixels>,
    },
}

/// What one edit changed.
///
/// Only whether anything changed, for now. An earlier revision also carried
/// the created and removed nodes, the removed panels, and the activation
/// edges — but nothing outside tests ever read them, and computing them meant
/// cloning the whole tree on every edit to diff against. Fields are private, so
/// any of them can come back the day something needs one.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct EditResult {
    changed: bool,
}

impl EditResult {
    pub fn changed(&self) -> bool {
        self.changed
    }
}

impl PaneTree {
    pub fn insert_panel(&mut self, panel: PanelId, target: InsertTarget) -> EditResult {
        self.edit(|tree| tree.apply_insert(panel, target))
    }

    pub fn remove_panel(&mut self, panel: PanelId) -> EditResult {
        self.edit(|tree| tree.detach_panel(panel))
    }

    /// Move a panel to a new home without ever removing it from the tree's
    /// perspective, so the caller never fires `on_removed` for a drag.
    pub fn move_panel(&mut self, panel: PanelId, target: InsertTarget) -> EditResult {
        self.edit(|tree| {
            let detached = tree.detach_panel(panel);
            let inserted = tree.apply_insert(panel, target);
            detached || inserted
        })
    }

    pub fn split(
        &mut self,
        at: NodeId,
        panel: PanelId,
        placement: Placement,
        size: Option<Pixels>,
    ) -> EditResult {
        self.insert_panel(
            panel,
            InsertTarget::Split {
                node: at,
                placement,
                size,
            },
        )
    }

    pub fn set_active(&mut self, node: NodeId, ix: usize) -> EditResult {
        self.edit(|tree| {
            let Some(path) = tree.path_of_node(node) else {
                return false;
            };
            let NodeKind::Tabs { active_ix, .. } = tree.node_at_mut(&path).kind_mut() else {
                return false;
            };
            if *active_ix == ix {
                return false;
            }
            *active_ix = ix;
            true
        })
    }

    /// Replace a split's slot sizes wholesale.
    ///
    /// A no-op, like every other operation given input it cannot resolve, if
    /// `new_sizes.len()` does not match the split's child count: no rule in
    /// `normalize` repairs a length mismatch, so applying it would otherwise
    /// leave `children.len() != sizes.len()` and trip `normalize`'s
    /// `debug_assert!`.
    pub fn set_sizes(&mut self, node: NodeId, new_sizes: Vec<Option<Pixels>>) -> EditResult {
        self.edit(|tree| {
            let Some(path) = tree.path_of_node(node) else {
                return false;
            };
            let NodeKind::Split {
                children, sizes, ..
            } = tree.node_at_mut(&path).kind_mut()
            else {
                return false;
            };
            if new_sizes.len() != children.len() || *sizes == new_sizes {
                return false;
            }
            *sizes = new_sizes;
            true
        })
    }
}

impl PaneTree {
    /// Replace every split's slot sizes with what that split is actually drawn
    /// at.
    ///
    /// A layout is usually built with unconstrained slots, and `None` stays
    /// `None` in the tree no matter how the split is later measured or
    /// dragged. That is fine until an edit has to divide space — dropping a
    /// panel beside another one has to halve *something*, and it cannot halve
    /// an unknown. Adopting the measured sizes first turns the question into
    /// arithmetic on real pixels, and it matches what the person dragging
    /// sees: the layout on screen is the layout being divided.
    pub(crate) fn adopt_measured_sizes(&mut self, measured: &HashMap<NodeId, Vec<Pixels>>) {
        fn walk(node: &mut PaneNode, measured: &HashMap<NodeId, Vec<Pixels>>) {
            let id = node.id();
            let NodeKind::Split {
                children, sizes, ..
            } = node.kind_mut()
            else {
                return;
            };

            if let Some(actual) = measured.get(&id) {
                if actual.len() == sizes.len() {
                    for (slot, size) in sizes.iter_mut().zip(actual) {
                        // A zero means the split has not been laid out yet, so
                        // the slot keeps whatever it already had.
                        if *size > Pixels::ZERO {
                            *slot = Some(*size);
                        }
                    }
                }
            }

            for child in children.iter_mut() {
                walk(child, measured);
            }
        }

        walk(self.root_mut(), measured);
    }
}

impl PaneTree {
    /// Apply one mutation, then collapse.
    ///
    /// `apply` reports whether it changed anything and normalization reports
    /// the same, so no snapshot of the previous tree is needed to answer the
    /// only question a caller asks. A mutation that cannot resolve its target
    /// returns `false` and the whole edit is a no-op.
    fn edit(&mut self, apply: impl FnOnce(&mut Self) -> bool) -> EditResult {
        let mutated = apply(self);
        let collapsed = self.normalize_reporting();

        EditResult {
            changed: mutated || collapsed,
        }
    }

    /// Whether `panel` is anywhere in this tree.
    pub fn contains_panel(&self, panel: PanelId) -> bool {
        self.panels().any(|candidate| candidate == panel)
    }
}

impl PaneTree {
    /// Returns whether the panel actually landed. A target this tree cannot
    /// resolve — a stale node id, or one whose kind does not match the
    /// target — is a no-op rather than an error, and reports `false`.
    fn apply_insert(&mut self, panel: PanelId, target: InsertTarget) -> bool {
        match target {
            InsertTarget::Tabs { node, ix, activate } => {
                let Some(path) = self.path_of_node(node) else {
                    return false;
                };
                let NodeKind::Tabs { panels, active_ix } = self.node_at_mut(&path).kind_mut()
                else {
                    return false;
                };
                let ix = ix.unwrap_or(panels.len()).min(panels.len());
                panels.insert(ix, panel);
                if activate {
                    *active_ix = ix;
                } else if ix <= *active_ix && panels.len() > 1 {
                    // Keep the displayed panel displayed.
                    *active_ix += 1;
                }
                true
            }
            InsertTarget::Split {
                node,
                placement,
                size,
            } => self.insert_beside(node, panel, placement, size),
        }
    }

    /// Place `panel` in a new tab group beside `node`.
    ///
    /// When the parent split already runs along the placement's axis the new
    /// group becomes a sibling. Otherwise `node` is wrapped in a fresh split of
    /// the placement's axis. Rule 3 of `normalize` then flattens any redundant
    /// nesting this creates, which is why no "reuse the parent split" special
    /// case is needed here.
    fn insert_beside(
        &mut self,
        node: NodeId,
        panel: PanelId,
        placement: Placement,
        size: Option<Pixels>,
    ) -> bool {
        let Some(path) = self.path_of_node(node) else {
            return false;
        };
        let group_id = self.allocate_node_id();
        let group = PaneNode::new(
            group_id,
            NodeKind::Tabs {
                panels: vec![panel],
                active_ix: 0,
            },
        );
        let before = matches!(placement, Placement::Left | Placement::Top);

        if let Some((parent_path, ix)) = split_parent_of(&path) {
            let parent_axis = match self.node_at(&parent_path).kind_ref() {
                NodeKind::Split { axis, .. } => Some(*axis),
                _ => None,
            };

            if parent_axis == Some(placement.axis()) {
                let NodeKind::Split {
                    children, sizes, ..
                } = self.node_at_mut(&parent_path).kind_mut()
                else {
                    return false;
                };
                // The new group splits the slot it landed beside, rather
                // than the whole row being re-divided: drop a panel next to
                // one neighbour and it is that neighbour's space you take.
                // A caller that named a size gets exactly it, and the
                // neighbour is left alone.
                //
                // An unconstrained neighbour halves to another `None`, which
                // is right for the same reason — the two of them go on
                // sharing whatever the fixed slots leave over, now between
                // themselves.
                let share = match size {
                    Some(size) => Some(size),
                    None => {
                        let half = sizes[ix].map(|slot| slot / 2.);
                        sizes[ix] = half;
                        half
                    }
                };
                let at = if before { ix } else { ix + 1 };
                children.insert(at, group);
                sizes.insert(at, share);
                return true;
            }
        }

        // Wrap the target in a new split of the placement's axis. The target
        // is swapped out rather than cloned: it can be a whole subtree, and
        // the placeholder left behind is overwritten two statements later.
        let wrapper_id = self.allocate_node_id();
        let target = std::mem::replace(
            self.node_at_mut(&path),
            PaneNode::new(
                wrapper_id,
                NodeKind::Tabs {
                    panels: Vec::new(),
                    active_ix: 0,
                },
            ),
        );
        let (children, sizes) = if before {
            (vec![group, target], vec![size, None])
        } else {
            (vec![target, group], vec![None, size])
        };
        let wrapper = PaneNode::new(
            wrapper_id,
            NodeKind::Split {
                axis: placement.axis(),
                children,
                sizes,
            },
        );
        *self.node_at_mut(&path) = wrapper;
        true
    }

    /// Remove `panel` wherever it lives. Returns whether it was found.
    fn detach_panel(&mut self, panel: PanelId) -> bool {
        let Some(node) = self.find_panel_node(panel) else {
            return false;
        };
        let Some(path) = self.path_of_node(node) else {
            return false;
        };

        match self.node_at_mut(&path).kind_mut() {
            NodeKind::Tabs { panels, active_ix } => {
                let Some(ix) = panels.iter().position(|p| *p == panel) else {
                    return false;
                };
                panels.remove(ix);
                if ix < *active_ix {
                    *active_ix -= 1;
                }
                true
            }
            NodeKind::Split { .. } => false,
        }
    }
}

/// Split the path into its parent path and the child index, or `None` at the root.
fn split_parent_of(path: &super::tree::NodePath) -> Option<(super::tree::NodePath, usize)> {
    let (&ix, parent) = path.split_last()?;
    Some((parent.iter().copied().collect(), ix))
}

#[cfg(test)]
mod tests {
    use super::super::*;
    use crate::Placement;
    use gpui::{Axis, px};

    fn panel(n: u64) -> PanelId {
        PanelId::from_u64(n)
    }

    fn tree_with_one_group() -> (PaneTree, NodeId) {
        let mut tree = PaneTree::new(RootKind::Split);
        let tabs = tree.push_tabs_for_test(tree.root().id(), vec![panel(1)]);
        tree.normalize();
        (tree, tabs)
    }

    #[test]
    fn inserting_into_a_tab_group_appends_and_can_activate() {
        let (mut tree, tabs) = tree_with_one_group();
        let result = tree.insert_panel(
            panel(2),
            InsertTarget::Tabs {
                node: tabs,
                ix: None,
                activate: true,
            },
        );

        assert!(result.changed());
        let PaneRef::Tabs { panels, active_ix } = tree.find_node(tabs).unwrap().kind() else {
            panic!()
        };
        assert_eq!(panels, [panel(1), panel(2)]);
        assert_eq!(active_ix, 1, "the inserted panel becomes the displayed one");
    }

    #[test]
    fn a_background_insert_leaves_the_active_panel_alone() {
        let (mut tree, tabs) = tree_with_one_group();
        let result = tree.insert_panel(
            panel(2),
            InsertTarget::Tabs {
                node: tabs,
                ix: None,
                activate: false,
            },
        );

        assert!(result.changed());
        let PaneRef::Tabs { panels, active_ix } = tree.find_node(tabs).unwrap().kind() else {
            panic!()
        };
        assert_eq!(panels, [panel(1), panel(2)]);
        assert_eq!(active_ix, 0, "the displayed panel is left alone");
    }

    #[test]
    fn removing_the_last_panel_collapses_the_group_and_reports_it() {
        let (mut tree, tabs) = tree_with_one_group();
        let result = tree.remove_panel(panel(1));

        assert!(result.changed());
        assert!(!tree.contains_panel(panel(1)), "the panel left the tree");
        assert!(tree.find_node(tabs).is_none(), "its empty group collapsed");
        assert!(
            matches!(tree.root().kind(), PaneRef::Split { children, .. } if children.is_empty())
        );
    }

    #[test]
    fn splitting_creates_a_sibling_group_on_the_requested_side() {
        let (mut tree, tabs) = tree_with_one_group();
        let result = tree.split(tabs, panel(2), Placement::Right, Some(px(240.)));

        assert!(result.changed());
        let PaneRef::Split {
            axis,
            children,
            sizes,
        } = tree.root().kind()
        else {
            panic!()
        };
        assert_eq!(axis, Axis::Horizontal);
        assert_eq!(children.len(), 2);
        assert_eq!(sizes[1], Some(px(240.)));

        let PaneRef::Tabs { panels, .. } = children[0].kind() else {
            panic!()
        };
        assert_eq!(panels, [panel(1)]);
        let PaneRef::Tabs { panels, .. } = children[1].kind() else {
            panic!()
        };
        assert_eq!(panels, [panel(2)]);
    }

    #[test]
    fn splitting_left_puts_the_new_group_first() {
        let (mut tree, tabs) = tree_with_one_group();
        tree.split(tabs, panel(2), Placement::Left, None);

        let PaneRef::Split { children, .. } = tree.root().kind() else {
            panic!()
        };
        let PaneRef::Tabs { panels, .. } = children[0].kind() else {
            panic!()
        };
        assert_eq!(panels, [panel(2)]);
    }

    #[test]
    fn splitting_across_the_parent_axis_nests_a_new_split() {
        let (mut tree, tabs) = tree_with_one_group();
        tree.push_tabs_for_test(tree.root().id(), vec![panel(9)]);
        tree.normalize();

        tree.split(tabs, panel(2), Placement::Bottom, None);

        let PaneRef::Split { axis, children, .. } = tree.root().kind() else {
            panic!()
        };
        assert_eq!(axis, Axis::Horizontal);
        let PaneRef::Split {
            axis: inner,
            children: inner_children,
            ..
        } = children[0].kind()
        else {
            panic!("the split target is wrapped in a vertical split")
        };
        assert_eq!(inner, Axis::Vertical);
        assert_eq!(inner_children.len(), 2);

        // `Bottom` puts the new group after the original target: the
        // wrapper's first child is still the target, the second is new.
        let PaneRef::Tabs { panels, .. } = inner_children[0].kind() else {
            panic!()
        };
        assert_eq!(panels, [panel(1)], "the original target stays first");
        let PaneRef::Tabs { panels, .. } = inner_children[1].kind() else {
            panic!()
        };
        assert_eq!(panels, [panel(2)], "the new group lands second, below");
    }

    #[test]
    fn splitting_top_across_the_parent_axis_puts_the_new_group_first() {
        let (mut tree, tabs) = tree_with_one_group();
        tree.push_tabs_for_test(tree.root().id(), vec![panel(9)]);
        tree.normalize();

        tree.split(tabs, panel(2), Placement::Top, None);

        let PaneRef::Split { children, .. } = tree.root().kind() else {
            panic!()
        };
        let PaneRef::Split {
            axis: inner,
            children: inner_children,
            ..
        } = children[0].kind()
        else {
            panic!("the split target is wrapped in a vertical split")
        };
        assert_eq!(inner, Axis::Vertical);
        assert_eq!(inner_children.len(), 2);

        // `Top` is the mirror of `Bottom`: the new group lands first, above
        // the original target.
        let PaneRef::Tabs { panels, .. } = inner_children[0].kind() else {
            panic!()
        };
        assert_eq!(panels, [panel(2)], "the new group lands first, above");
        let PaneRef::Tabs { panels, .. } = inner_children[1].kind() else {
            panic!()
        };
        assert_eq!(panels, [panel(1)], "the original target moves second");
    }

    #[test]
    fn the_split_target_keeps_its_node_id_so_its_entity_survives() {
        let (mut tree, tabs) = tree_with_one_group();
        tree.split(tabs, panel(2), Placement::Right, None);

        assert!(
            tree.find_node(tabs).is_some(),
            "the target group is reused, not rebuilt"
        );
    }

    #[test]
    fn moving_a_panel_between_groups_preserves_its_identity() {
        let (mut tree, tabs) = tree_with_one_group();
        assert!(tree.split(tabs, panel(2), Placement::Right, None).changed());
        let other = tree
            .find_panel_node(panel(2))
            .expect("the split put panel 2 in a group of its own");

        let result = tree.move_panel(
            panel(1),
            InsertTarget::Tabs {
                node: other,
                ix: None,
                activate: true,
            },
        );

        assert!(result.changed());
        assert_eq!(
            tree.panels().collect::<Vec<_>>(),
            vec![panel(2), panel(1)],
            "a move is not a removal; both panels are still in the tree"
        );
        assert!(
            tree.find_node(tabs).is_none(),
            "the emptied group collapses"
        );
    }

    #[test]
    fn a_no_op_edit_reports_no_change() {
        let (mut tree, tabs) = tree_with_one_group();
        let result = tree.set_active(tabs, 0);
        assert!(!result.changed());
    }

    #[test]
    fn set_sizes_replaces_a_matching_length_vector() {
        let (mut tree, tabs) = tree_with_one_group();
        tree.split(tabs, panel(2), Placement::Right, None);
        let root = tree.root().id();

        let result = tree.set_sizes(root, vec![Some(px(100.)), Some(px(200.))]);

        assert!(result.changed());
        let PaneRef::Split { sizes, .. } = tree.root().kind() else {
            panic!()
        };
        assert_eq!(sizes, &[Some(px(100.)), Some(px(200.))]);
    }

    #[test]
    fn set_sizes_ignores_a_mismatched_length_vector() {
        let (mut tree, tabs) = tree_with_one_group();
        tree.split(tabs, panel(2), Placement::Right, None);
        let root = tree.root().id();
        let PaneRef::Split {
            sizes: before_sizes,
            ..
        } = tree.root().kind()
        else {
            panic!()
        };
        let before_sizes = before_sizes.to_vec();

        // The split has 2 children; hand it 3 sizes.
        let result = tree.set_sizes(root, vec![Some(px(10.)), Some(px(20.)), Some(px(30.))]);

        assert!(
            !result.changed(),
            "a mismatched vector must not report a change"
        );
        let PaneRef::Split { sizes, .. } = tree.root().kind() else {
            panic!()
        };
        assert_eq!(
            sizes,
            before_sizes.as_slice(),
            "the mismatched vector is rejected"
        );
    }

    #[test]
    fn every_edit_leaves_the_tree_normalized() {
        let (mut tree, tabs) = tree_with_one_group();
        tree.split(tabs, panel(2), Placement::Bottom, None);
        tree.insert_panel(
            panel(3),
            InsertTarget::Tabs {
                node: tabs,
                ix: None,
                activate: false,
            },
        );
        tree.remove_panel(panel(2));
        tree.remove_panel(panel(3));

        assert!(tree.is_normalized());
    }
}
