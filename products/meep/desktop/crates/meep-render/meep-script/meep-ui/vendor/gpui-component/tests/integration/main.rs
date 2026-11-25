//! The component crate's integration tests, in one binary.
//!
//! Each file under `tests/` is a binary of its own, linked with GPUI and
//! every component, so these are modules of one.

mod base_compat;
mod controlled_change_callbacks;
mod legacy_button_compat;
mod legacy_controls_compat;
mod legacy_language_config_compat;
mod table_dump_range;
mod table_fit_column;
mod theme_compat;
