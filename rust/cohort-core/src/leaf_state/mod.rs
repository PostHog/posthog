//! Leaf-state addressing: a leaf's persisted-state [`key`], the [`variant`] (which state
//! representation it uses), and [`select`]ing both — plus an eviction window — from a leaf's config.

pub mod key;
pub mod select;
pub mod variant;

pub use key::LeafStateKey;
pub use select::EvictionWindow;
pub use variant::StateVariant;
