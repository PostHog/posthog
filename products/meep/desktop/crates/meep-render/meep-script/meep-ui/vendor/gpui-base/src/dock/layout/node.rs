use gpui::{Axis, EntityId, Pixels};

/// Stable container identity. Survives structural edits and normalization so
/// the `DockArea` view cache does not tear down and rebuild entities.
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug, PartialOrd, Ord)]
pub struct NodeId(u64);

impl NodeId {
    pub(crate) fn from_u64(raw: u64) -> Self {
        Self(raw)
    }

    pub fn as_u64(self) -> u64 {
        self.0
    }
}

/// Stable panel identity. Wraps the `EntityId` of the panel entity so the
/// layout algebra can be exercised without an `App`.
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug, PartialOrd, Ord)]
pub struct PanelId(u64);

impl PanelId {
    pub fn from_u64(raw: u64) -> Self {
        Self(raw)
    }

    pub fn as_u64(self) -> u64 {
        self.0
    }
}

impl From<EntityId> for PanelId {
    fn from(id: EntityId) -> Self {
        Self(id.as_u64())
    }
}

/// The shape of one container. Private: every mutation goes through
/// [`PaneTree`] so normalization always runs.
///
/// [`PaneTree`]: super::PaneTree
#[derive(Clone, PartialEq, Debug)]
pub(crate) enum NodeKind {
    Split {
        axis: Axis,
        children: Vec<PaneNode>,
        sizes: Vec<Option<Pixels>>,
    },
    Tabs {
        panels: Vec<PanelId>,
        active_ix: usize,
    },
}

/// Borrowed read-only projection of a node.
pub enum PaneRef<'a> {
    Split {
        axis: Axis,
        children: &'a [PaneNode],
        sizes: &'a [Option<Pixels>],
    },
    Tabs {
        panels: &'a [PanelId],
        active_ix: usize,
    },
}

#[derive(Clone, PartialEq, Debug)]
pub struct PaneNode {
    id: NodeId,
    kind: NodeKind,
}

impl PaneNode {
    pub(crate) fn new(id: NodeId, kind: NodeKind) -> Self {
        Self { id, kind }
    }

    pub fn id(&self) -> NodeId {
        self.id
    }

    pub fn kind(&self) -> PaneRef<'_> {
        match &self.kind {
            NodeKind::Split {
                axis,
                children,
                sizes,
            } => PaneRef::Split {
                axis: *axis,
                children,
                sizes,
            },
            NodeKind::Tabs { panels, active_ix } => PaneRef::Tabs {
                panels,
                active_ix: *active_ix,
            },
        }
    }

    pub(crate) fn kind_mut(&mut self) -> &mut NodeKind {
        &mut self.kind
    }

    pub(crate) fn kind_ref(&self) -> &NodeKind {
        &self.kind
    }

    /// Depth-first pre-order walk over this node and its descendants.
    pub fn walk(&self, f: &mut impl FnMut(&PaneNode)) {
        f(self);
        if let NodeKind::Split { children, .. } = &self.kind {
            for child in children {
                child.walk(f);
            }
        }
    }
}
