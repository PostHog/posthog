use gpui::{Axis, Pixels};
use serde::{Deserialize, Serialize};

/// Used to serialize and deserialize the DockArea.
///
/// This mirrors a persisted, on-disk schema shipped to end users. Its fields
/// stay `pub` rather than following the seam's builder/reader convention —
/// see "Public Data Types Across the Seam" in `docs/ARCHITECTURE.md`.
#[derive(Debug, Default, Clone, Serialize, Deserialize, PartialEq)]
pub struct DockAreaState {
    /// The version is used to mark this persisted state is compatible with the current version
    /// For example, some times we many totally changed the structure of the Panel,
    /// then we can compare the version to decide whether we can use the state or ignore.
    #[serde(default)]
    pub version: Option<usize>,
    pub center: PanelState,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub left_dock: Option<DockState>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub right_dock: Option<DockState>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub bottom_dock: Option<DockState>,
}

/// Used to serialize and deserialize the Dock.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct DockState {
    panel: PanelState,
    placement: DockPlacement,
    size: Pixels,
    open: bool,
}

impl DockState {
    pub fn new(panel: PanelState, placement: DockPlacement, size: Pixels, open: bool) -> Self {
        Self {
            panel,
            placement,
            size,
            open,
        }
    }

    pub fn panel(&self) -> &PanelState {
        &self.panel
    }

    pub fn placement(&self) -> DockPlacement {
        self.placement
    }

    pub fn size(&self) -> Pixels {
        self.size
    }

    pub fn open(&self) -> bool {
        self.open
    }
}

/// Used to serialize and deserialize the DockerItem.
///
/// This mirrors a persisted, on-disk schema shipped to end users. Its fields
/// stay `pub` rather than following the seam's builder/reader convention —
/// see "Public Data Types Across the Seam" in `docs/ARCHITECTURE.md`.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct PanelState {
    pub panel_name: String,
    pub children: Vec<PanelState>,
    pub info: PanelInfo,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum PanelInfo {
    #[serde(rename = "stack")]
    Stack {
        sizes: Vec<Pixels>,
        axis: usize, // 0 for horizontal, 1 for vertical
    },
    #[serde(rename = "tabs")]
    Tabs { active_index: usize },
    #[serde(rename = "panel")]
    Panel(serde_json::Value),
}

impl PanelInfo {
    pub fn stack(sizes: Vec<Pixels>, axis: Axis) -> Self {
        Self::Stack {
            sizes,
            axis: if axis == Axis::Horizontal { 0 } else { 1 },
        }
    }

    pub fn tabs(active_index: usize) -> Self {
        Self::Tabs { active_index }
    }

    pub fn panel(info: serde_json::Value) -> Self {
        Self::Panel(info)
    }

    pub fn axis(&self) -> Option<Axis> {
        match self {
            Self::Stack { axis, .. } => Some(if *axis == 0 {
                Axis::Horizontal
            } else {
                Axis::Vertical
            }),
            _ => None,
        }
    }

    pub fn sizes(&self) -> Option<&Vec<Pixels>> {
        match self {
            Self::Stack { sizes, .. } => Some(sizes),
            _ => None,
        }
    }

    pub fn active_index(&self) -> Option<usize> {
        match self {
            Self::Tabs { active_index } => Some(*active_index),
            _ => None,
        }
    }
}

impl Default for PanelState {
    fn default() -> Self {
        Self {
            panel_name: "".to_string(),
            children: Vec::new(),
            info: PanelInfo::Panel(serde_json::Value::Null),
        }
    }
}

impl PanelState {
    /// Create a new leaf state for a panel with the given name.
    ///
    /// The base layer has no `Panel` trait yet (`gpui_component::dock::Panel`
    /// is layered above), so this takes the name directly rather than
    /// deriving it from a panel value.
    pub fn new(panel_name: impl Into<String>) -> Self {
        Self {
            panel_name: panel_name.into(),
            ..Default::default()
        }
    }

    pub fn add_child(&mut self, panel: PanelState) {
        self.children.push(panel);
    }
}

/// Placement of a [`Dock`](super::Dock) relative to the center area.
///
/// This mirrors a persisted, on-disk schema shipped to end users: the
/// `#[serde(rename = ...)]` tags below are frozen and must not change.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Hash)]
pub enum DockPlacement {
    #[serde(rename = "center")]
    Center,
    #[serde(rename = "left")]
    Left,
    #[serde(rename = "bottom")]
    Bottom,
    #[serde(rename = "right")]
    Right,
}

impl DockPlacement {
    pub fn axis(&self) -> Axis {
        match self {
            Self::Left | Self::Right | Self::Center => Axis::Horizontal,
            Self::Bottom => Axis::Vertical,
        }
    }

    pub fn is_left(&self) -> bool {
        matches!(self, Self::Left)
    }

    pub fn is_bottom(&self) -> bool {
        matches!(self, Self::Bottom)
    }

    pub fn is_right(&self) -> bool {
        matches!(self, Self::Right)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use gpui::px;

    /// The whole of a real user's file, not just its outline: every dock and
    /// the nesting under each one. Ported from the old
    /// `test_deserialize_item_state`, which checked all three docks and their
    /// children — a fixture test that only reads the center and one dock
    /// would keep passing if a dock's shape stopped deserializing at all.
    #[test]
    fn the_shipped_fixture_still_deserializes() {
        let json = include_str!("fixtures/layout.json");
        let state: DockAreaState = serde_json::from_str(json).unwrap();

        assert_eq!(state.version, None);
        assert_eq!(state.center.panel_name, "StackPanel");
        assert_eq!(state.center.children.len(), 2);
        assert_eq!(state.center.children[0].panel_name, "TabPanel");
        assert_eq!(state.center.children[1].panel_name, "TabPanel");
        assert_eq!(state.center.children[1].children.len(), 1);
        assert_eq!(
            state.center.children[1].children[0].panel_name,
            "StoryContainer"
        );

        let left = state.left_dock.unwrap();
        assert_eq!(left.open(), true);
        assert_eq!(left.size(), px(350.0));
        assert_eq!(left.placement(), DockPlacement::Left);
        assert_eq!(left.panel().panel_name, "TabPanel");
        assert_eq!(left.panel().children.len(), 1);
        assert_eq!(left.panel().children[0].panel_name, "StoryContainer");

        let bottom = state.bottom_dock.unwrap();
        assert_eq!(bottom.open(), true);
        assert_eq!(bottom.size(), px(200.0));
        assert_eq!(bottom.placement(), DockPlacement::Bottom);
        assert_eq!(bottom.panel().panel_name, "TabPanel");
        assert_eq!(bottom.panel().children.len(), 2);
        assert_eq!(bottom.panel().children[0].panel_name, "StoryContainer");

        let right = state.right_dock.unwrap();
        assert_eq!(right.open(), true);
        assert_eq!(right.size(), px(320.0));
        assert_eq!(right.placement(), DockPlacement::Right);
        assert_eq!(right.panel().panel_name, "TabPanel");
        assert_eq!(right.panel().children.len(), 1);
        assert_eq!(right.panel().children[0].panel_name, "StoryContainer");
    }

    #[test]
    fn the_serde_tags_are_frozen() {
        let stack = serde_json::to_value(PanelInfo::stack(vec![px(1.)], Axis::Vertical)).unwrap();
        assert_eq!(
            stack,
            serde_json::json!({"stack": {"sizes": [1.0], "axis": 1}})
        );

        let tabs = serde_json::to_value(PanelInfo::tabs(2)).unwrap();
        assert_eq!(tabs, serde_json::json!({"tabs": {"active_index": 2}}));

        let placement = serde_json::to_value(DockPlacement::Bottom).unwrap();
        assert_eq!(placement, serde_json::json!("bottom"));
    }

    #[test]
    fn optional_docks_are_omitted_not_nulled() {
        let state = DockAreaState::default();
        let json = serde_json::to_value(&state).unwrap();
        assert!(json.get("left_dock").is_none());
        assert!(json.get("right_dock").is_none());
        assert!(json.get("bottom_dock").is_none());
    }
}
