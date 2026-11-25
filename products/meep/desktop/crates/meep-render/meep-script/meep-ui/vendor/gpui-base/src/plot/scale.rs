mod band;
mod linear;
mod ordinal;
mod point;
mod sealed;

pub use band::ScaleBand;
pub use linear::ScaleLinear;
pub use ordinal::ScaleOrdinal;
pub use point::ScalePoint;

use num_traits::{Num, ToPrimitive};

/// A number a [`ScaleLinear`] and the charts built on it can place: `f32`,
/// `f64`, and `rust_decimal::Decimal` with the `decimal` feature.
///
/// Sealed: integer types are left out on purpose, because a linear scale
/// divides values and integer division would truncate every position.
pub trait PlotValue: sealed::Sealed + Copy + PartialOrd + Num + ToPrimitive + 'static {}

impl PlotValue for f32 {}
impl PlotValue for f64 {}
#[cfg(feature = "decimal")]
impl PlotValue for rust_decimal::Decimal {}

pub trait Scale<T> {
    /// Get the tick of the scale.
    fn tick(&self, value: &T) -> Option<f32>;

    /// The index of the domain value whose position is nearest `tick`; `0` for
    /// an empty domain or a scale without discrete positions.
    fn nearest_index(&self, _tick: f32) -> usize {
        0
    }
}
