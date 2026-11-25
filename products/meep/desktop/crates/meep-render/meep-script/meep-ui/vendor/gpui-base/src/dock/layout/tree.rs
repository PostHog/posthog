use std::sync::atomic::{AtomicU64, Ordering};

use smallvec::SmallVec;

use super::node::{NodeId, NodeKind, PaneNode, PaneRef, PanelId};

/// Whether the root of this tree is pinned to a split.
///
/// The center of a `DockArea` must serialize as a `StackPanel` even when
/// empty, which `RootKind::Split` guarantees. A dock's root is unconstrained.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum RootKind {
    Split,
    Any,
}

/// Path from the root as a sequence of child indices.
pub(crate) type NodePath = SmallVec<[usize; 8]>;

/// Source of every [`NodeId`], shared by every tree in the process.
///
/// A per-tree counter would restart at the same value in each tree, and a
/// `DockArea` owns four of them (the center plus one per dock). Its entity
/// cache is keyed by `NodeId` alone, so two trees minting the same id would
/// hand two different containers the same cache slot. Allocating globally is
/// what makes `NodeId` the stable *container* identity its documentation
/// claims, rather than an identity that is only unique within one tree.
static NEXT_NODE_ID: AtomicU64 = AtomicU64::new(0);

fn next_node_id() -> NodeId {
    NodeId::from_u64(NEXT_NODE_ID.fetch_add(1, Ordering::Relaxed))
}

/// One region's layout, as pure data.
///
/// A `DockArea` owns one of these per region — the center plus each dock it
/// has. Containers are addressed by [`NodeId`] and panels by [`PanelId`];
/// no entity handle lives in here, so a tree can be built, edited, compared
/// and serialized with no `App` in sight.
///
/// Every edit method normalizes before returning and reports what it did as
/// an [`EditResult`](super::EditResult), so there is no window in which a
/// caller can observe a tree with an empty container, a one-child split, or an
/// out-of-range active index.
#[derive(Clone, PartialEq, Debug)]
pub struct PaneTree {
    root: PaneNode,
    root_kind: RootKind,
}

impl PaneTree {
    pub fn new(root_kind: RootKind) -> Self {
        let root = PaneNode::new(
            next_node_id(),
            NodeKind::Split {
                axis: gpui::Axis::Horizontal,
                children: Vec::new(),
                sizes: Vec::new(),
            },
        );
        Self { root, root_kind }
    }

    pub fn root(&self) -> &PaneNode {
        &self.root
    }

    /// Mutable access to the root, for normalization's post-order pass.
    pub(crate) fn root_mut(&mut self) -> &mut PaneNode {
        &mut self.root
    }

    pub fn root_kind(&self) -> RootKind {
        self.root_kind
    }

    pub(crate) fn allocate_node_id(&mut self) -> NodeId {
        next_node_id()
    }

    /// Every container id in the tree, in pre-order.
    pub fn node_ids(&self) -> Vec<NodeId> {
        let mut ids = Vec::new();
        self.root.walk(&mut |node| ids.push(node.id()));
        ids
    }

    /// Every panel in the tree, in pre-order.
    pub fn panels(&self) -> impl Iterator<Item = PanelId> {
        let mut found = Vec::new();
        self.root.walk(&mut |node| match node.kind() {
            PaneRef::Tabs { panels, .. } => found.extend_from_slice(panels),
            PaneRef::Split { .. } => {}
        });
        found.into_iter()
    }

    pub fn find_node(&self, id: NodeId) -> Option<&PaneNode> {
        self.path_of_node(id).map(|path| self.node_at(&path))
    }

    /// The tab node holding `panel`.
    pub fn find_panel_node(&self, panel: PanelId) -> Option<NodeId> {
        let mut found = None;
        self.root.walk(&mut |node| {
            let holds = match node.kind() {
                PaneRef::Tabs { panels, .. } => panels.contains(&panel),
                PaneRef::Split { .. } => false,
            };
            if holds {
                found = Some(node.id());
            }
        });
        found
    }

    pub(crate) fn path_of_node(&self, id: NodeId) -> Option<NodePath> {
        fn search(node: &PaneNode, id: NodeId, path: &mut NodePath) -> bool {
            if node.id() == id {
                return true;
            }
            if let NodeKind::Split { children, .. } = node.kind_ref() {
                for (ix, child) in children.iter().enumerate() {
                    path.push(ix);
                    if search(child, id, path) {
                        return true;
                    }
                    path.pop();
                }
            }
            false
        }

        let mut path = NodePath::new();
        search(&self.root, id, &mut path).then_some(path)
    }

    pub(crate) fn node_at(&self, path: &NodePath) -> &PaneNode {
        let mut node = &self.root;
        for ix in path {
            let NodeKind::Split { children, .. } = node.kind_ref() else {
                unreachable!("path traverses a non-split node");
            };
            node = &children[*ix];
        }
        node
    }

    pub(crate) fn node_at_mut(&mut self, path: &NodePath) -> &mut PaneNode {
        let mut node = &mut self.root;
        for ix in path {
            let NodeKind::Split { children, .. } = node.kind_mut() else {
                unreachable!("path traverses a non-split node");
            };
            node = &mut children[*ix];
        }
        node
    }

    /// Replace the whole tree with `node`, keeping `node`'s own id and
    /// `root_kind` unchanged. Used by normalization's root-collapse rule.
    pub(crate) fn replace_root(&mut self, node: PaneNode) {
        self.root = node;
    }
}

#[cfg(test)]
use gpui::{Axis, Pixels};

#[cfg(test)]
impl PaneTree {
    pub(crate) fn push_tabs_for_test(&mut self, parent: NodeId, panels: Vec<PanelId>) -> NodeId {
        let id = self.allocate_node_id();
        let path = self.path_of_node(parent).expect("parent must exist");
        let NodeKind::Split {
            children, sizes, ..
        } = self.node_at_mut(&path).kind_mut()
        else {
            panic!("parent must be a split");
        };
        children.push(PaneNode::new(
            id,
            NodeKind::Tabs {
                panels,
                active_ix: 0,
            },
        ));
        sizes.push(None);
        id
    }

    /// Like [`Self::push_tabs_for_test`], but with a concrete slot size
    /// instead of always pushing `None`. Needed to exercise the scaling
    /// arithmetic in `normalize`'s same-axis splice rule, which only runs
    /// when every sibling size is known.
    pub(crate) fn push_sized_tabs_for_test(
        &mut self,
        parent: NodeId,
        panels: Vec<PanelId>,
        size: Option<Pixels>,
    ) -> NodeId {
        let id = self.allocate_node_id();
        let path = self.path_of_node(parent).expect("parent must exist");
        let NodeKind::Split {
            children, sizes, ..
        } = self.node_at_mut(&path).kind_mut()
        else {
            panic!("parent must be a split");
        };
        children.push(PaneNode::new(
            id,
            NodeKind::Tabs {
                panels,
                active_ix: 0,
            },
        ));
        sizes.push(size);
        id
    }

    pub(crate) fn set_root_split_for_test(&mut self, axis: Axis) -> NodeId {
        let id = self.allocate_node_id();
        self.root = PaneNode::new(
            id,
            NodeKind::Split {
                axis,
                children: Vec::new(),
                sizes: Vec::new(),
            },
        );
        id
    }

    pub(crate) fn set_root_axis_for_test(&mut self, new_axis: Axis) {
        if let NodeKind::Split { axis, .. } = self.root.kind_mut() {
            *axis = new_axis;
        }
    }

    pub(crate) fn set_root_tabs_for_test(
        &mut self,
        panels: Vec<PanelId>,
        active_ix: usize,
    ) -> NodeId {
        let id = self.allocate_node_id();
        self.root = PaneNode::new(id, NodeKind::Tabs { panels, active_ix });
        id
    }

    pub(crate) fn push_split_for_test(
        &mut self,
        parent: NodeId,
        axis: Axis,
        size: Option<Pixels>,
    ) -> NodeId {
        let id = self.allocate_node_id();
        let path = self.path_of_node(parent).expect("parent must exist");
        let NodeKind::Split {
            children, sizes, ..
        } = self.node_at_mut(&path).kind_mut()
        else {
            panic!("parent must be a split");
        };
        children.push(PaneNode::new(
            id,
            NodeKind::Split {
                axis,
                children: Vec::new(),
                sizes: Vec::new(),
            },
        ));
        sizes.push(size);
        id
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn panel_id(n: u64) -> PanelId {
        PanelId::from_u64(n)
    }

    #[test]
    fn a_fresh_split_root_tree_has_no_panels() {
        let tree = PaneTree::new(RootKind::Split);
        assert!(
            matches!(tree.root().kind(), PaneRef::Split { children, .. } if children.is_empty())
        );
        assert_eq!(tree.panels().count(), 0);
    }

    #[test]
    fn node_ids_are_unique_and_resolvable() {
        let mut tree = PaneTree::new(RootKind::Split);
        let root = tree.root().id();
        let tabs = tree.push_tabs_for_test(root, vec![panel_id(1)]);
        assert_ne!(tabs, tree.root().id());
        assert!(tree.find_node(tabs).is_some());
        assert_eq!(tree.find_panel_node(panel_id(1)), Some(tabs));
    }
}
