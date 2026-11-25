//! Plotting for GPUI Component's charts.
//!
//! The unstyled primitives — scales, shapes, axes, grids, labels, [`Plot`] and
//! [`PlotElement`] — live in [`gpui_base::plot`] and are re-exported here.
//! This module adds the styled [`tooltip`] overlay and the `IntoPlot` derive.
pub use gpui_base::plot::*;
pub use gpui_component_macros::IntoPlot;

pub mod tooltip;
