mod builder;
mod edit;
mod node;
mod normalize;
mod tree;

pub use builder::DockLayout;
pub use edit::{EditResult, InsertTarget};

// `NodeKind` stays crate-private: `dock_area` reads through it to resolve slot
// sizes before a dump, but nothing outside this crate may build a node without
// going through `PaneTree`, which is what guarantees normalization always
// runs.
pub(crate) use node::NodeKind;
pub use node::{NodeId, PaneNode, PaneRef, PanelId};
pub use tree::{PaneTree, RootKind};
