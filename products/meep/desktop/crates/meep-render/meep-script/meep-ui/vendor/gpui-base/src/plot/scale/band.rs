// @reference: https://d3js.org/d3-scale/band

use std::{collections::HashMap, hash::Hash};

use num_traits::Zero;

use super::Scale;

#[derive(Clone)]
pub struct ScaleBand<T> {
    /// Each distinct domain value paired with its band index.
    ///
    /// D3 keys its band domain through an `InternMap`, so a repeated value
    /// keeps the index of its first occurrence and the band count follows the
    /// distinct values, not the entry count.
    indices: HashMap<T, usize>,
    /// The bands laid out when more than the domain's; see [`Self::band_count`].
    band_count: usize,
    /// The widest a band may be; see [`Self::max_band_width`].
    max_band_width: Option<f32>,
    range_start: f32,
    range_diff: f32,
    padding_inner: f32,
    padding_outer: f32,
}

impl<T> ScaleBand<T> {
    /// Lay the distinct values of `domain` out as bands across `range`, from
    /// its lower end in domain order.
    pub fn new(domain: impl IntoIterator<Item = T>, range: [f32; 2]) -> Self
    where
        T: Eq + Hash,
    {
        let mut indices = HashMap::new();
        for value in domain {
            let next = indices.len();
            indices.entry(value).or_insert(next);
        }

        Self {
            indices,
            band_count: 0,
            max_band_width: None,
            range_start: range[0].min(range[1]),
            range_diff: (range[1] - range[0]).abs(),
            padding_inner: 0.,
            padding_outer: 0.,
        }
    }

    /// The width of a band: the range divided among the bands, less the inner
    /// padding, and no wider than [`Self::max_band_width`] when set.
    pub fn band_width(&self) -> f32 {
        let width = self.avg_width() * (1. - self.padding_inner);
        self.max_band_width
            .map_or(width, |max_band_width| width.min(max_band_width))
    }

    /// Cap the band width at `width`, so a few bands in a wide range stay
    /// narrow; a band still starts where it would uncapped. Unset by default.
    pub fn max_band_width(mut self, width: f32) -> Self {
        self.max_band_width = Some(width);
        self
    }

    /// The distance between the starts of two adjacent bands: the band width
    /// plus the inner padding. The whole range for a single band.
    pub fn step(&self) -> f32 {
        if self.len() <= 1 {
            self.range_diff
        } else {
            self.display_avg_width() * self.ratio()
        }
    }

    /// Lay the range out for `count` bands, the domain taking the leading ones
    /// in order and the rest staying empty. A `count` below the domain's length
    /// has no effect.
    pub fn band_count(mut self, count: usize) -> Self {
        self.band_count = count;
        self
    }

    /// Set the padding inner of the band.
    pub fn padding_inner(mut self, padding_inner: f32) -> Self {
        self.padding_inner = padding_inner;
        self
    }

    /// Set the padding outer of the band.
    pub fn padding_outer(mut self, padding_outer: f32) -> Self {
        self.padding_outer = padding_outer;
        self
    }

    /// The number of bands: one per distinct domain value, or the
    /// [`Self::band_count`] when larger.
    fn len(&self) -> usize {
        self.indices.len().max(self.band_count)
    }

    /// The range divided evenly among the bands.
    fn avg_width(&self) -> f32 {
        let len = self.len() as f32;
        if len.is_zero() {
            0.
        } else {
            self.range_diff / len
        }
    }

    /// Get the ratio of the band.
    fn ratio(&self) -> f32 {
        1. + self.padding_inner / (self.len() - 1) as f32
    }

    /// Get the average width of the band for display.
    fn display_avg_width(&self) -> f32 {
        let padding_outer_width = self.avg_width() * self.padding_outer;
        (self.range_diff - padding_outer_width * 2.) / self.len() as f32
    }
}

impl<T> Scale<T> for ScaleBand<T>
where
    T: Eq + Hash,
{
    fn tick(&self, value: &T) -> Option<f32> {
        let index = *self.indices.get(value)?;
        let domain_len = self.len();

        // When there's only one element, place it in the center.
        if domain_len == 1 {
            return Some(self.range_start + (self.range_diff - self.band_width()) / 2.);
        }

        let avg_width = self.display_avg_width();
        let padding_outer_width = self.avg_width() * self.padding_outer;
        Some(self.range_start + index as f32 * avg_width * self.ratio() + padding_outer_width)
    }

    fn nearest_index(&self, tick: f32) -> usize {
        let domain_len = self.len();
        if domain_len == 0 {
            return 0;
        }

        // Handle single element case
        if domain_len == 1 {
            return 0;
        }

        let avg_width = self.display_avg_width();
        let padding_outer_width = self.avg_width() * self.padding_outer;
        let adjusted_tick = tick - self.range_start - padding_outer_width;
        let index = (adjusted_tick / (avg_width * self.ratio())).round() as i32;

        (index.max(0) as usize).min(domain_len.saturating_sub(1))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_scale_band() {
        let scale = ScaleBand::new(vec![1, 2, 3], [0., 90.]);
        assert_eq!(scale.tick(&1), Some(0.));
        assert_eq!(scale.tick(&2), Some(30.));
        assert_eq!(scale.tick(&3), Some(60.));
        assert_eq!(scale.band_width(), 30.);
    }

    #[test]
    fn max_band_width_caps_the_width_but_not_the_ticks() {
        let wide = ScaleBand::new(vec![1, 2], [0., 200.]);
        let capped = ScaleBand::new(vec![1, 2], [0., 200.]).max_band_width(30.);
        assert_eq!(wide.band_width(), 100.);
        assert_eq!(capped.band_width(), 30.);
        assert_eq!(capped.tick(&2), wide.tick(&2));
    }

    #[test]
    fn test_scale_band_dedup() {
        // Simulates grouped bar chart: 2 series × 3 categories = 6 entries, 3 unique.
        let scale = ScaleBand::new(vec![1, 2, 3, 1, 2, 3], [0., 90.]);
        assert_eq!(scale.len(), 3);
        assert_eq!(scale.tick(&1), Some(0.));
        assert_eq!(scale.tick(&2), Some(30.));
        assert_eq!(scale.tick(&3), Some(60.));
        assert_eq!(scale.band_width(), 30.);
    }

    #[test]
    fn test_scale_band_step() {
        // Adjacent bands start one step apart, whatever the padding.
        let scale = ScaleBand::new(vec![1, 2, 3], [0., 90.]);
        assert_eq!(
            scale.step(),
            scale.tick(&2).unwrap() - scale.tick(&1).unwrap()
        );

        let padded = ScaleBand::new(vec![1, 2, 3], [0., 90.])
            .padding_inner(0.4)
            .padding_outer(0.2);
        assert!(
            (padded.step() - (padded.tick(&2).unwrap() - padded.tick(&1).unwrap())).abs() < 1e-4
        );

        // A single band spans the range.
        assert_eq!(ScaleBand::new(vec![1], [0., 90.]).step(), 90.);
    }

    #[test]
    fn test_scale_band_count() {
        let scale = |domain: Vec<i32>| {
            ScaleBand::new(domain, [0., 100.])
                .band_count(4)
                .padding_inner(0.4)
                .padding_outer(0.2)
        };

        // The domain takes the leading bands, each placed as if all were full.
        let short = scale(vec![1, 2]);
        let full = scale(vec![1, 2, 3, 4]);
        assert_eq!(short.tick(&2), full.tick(&2));
        assert_eq!(short.band_width(), full.band_width());
        assert_eq!(short.step(), full.step());

        // An empty band resolves past the domain rather than to its last value.
        assert_eq!(short.nearest_index(full.tick(&4).unwrap()), 3);

        // A single value sits in the first band instead of the center.
        assert_eq!(scale(vec![1]).tick(&1), full.tick(&1));

        // A count below the domain's length has no effect.
        let domain = ScaleBand::new(vec![1, 2, 3], [0., 90.]);
        assert_eq!(domain.band_count(2).tick(&3), Some(60.));
    }

    #[test]
    fn test_scale_band_zero() {
        let scale = ScaleBand::new(vec![], [0., 90.]);
        assert_eq!(scale.tick(&1), None);
        assert_eq!(scale.tick(&2), None);
        assert_eq!(scale.tick(&3), None);
        assert_eq!(scale.band_width(), 0.);

        let scale = ScaleBand::new(vec![1, 2, 3], [0., 0.]);
        assert_eq!(scale.tick(&1), Some(0.));
        assert_eq!(scale.tick(&2), Some(0.));
        assert_eq!(scale.tick(&3), Some(0.));
        assert_eq!(scale.band_width(), 0.);
    }

    #[test]
    fn test_scale_band_range_start() {
        let scale = ScaleBand::new([1, 2, 3], [10., 100.]);
        assert_eq!(scale.tick(&1), Some(10.));
        assert_eq!(scale.tick(&2), Some(40.));
        assert_eq!(scale.nearest_index(41.), 1);
        // The lower end leads whichever way the range is written.
        assert_eq!(ScaleBand::new([1, 2, 3], [100., 10.]).tick(&1), Some(10.));
    }
}
