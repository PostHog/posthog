use gpui::App;

pub use gpui_base::GlobalState;

pub(crate) fn init(cx: &mut App) {
    // Preserve the legacy initialization point while `gpui_base::init` remains
    // after Root initialization for focus-trap ordering compatibility.
    GlobalState::init(cx);
}
