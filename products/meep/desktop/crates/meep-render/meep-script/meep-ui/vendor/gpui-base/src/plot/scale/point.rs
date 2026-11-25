// @reference: https://d3js.org/d3-scale/point

use super::Scale;

/// Point scale maps discrete domain values to continuous range positions.
///
/// Points are evenly distributed across the range, with the first and last points
/// aligned to the range boundaries.
#[derive(Clone)]
pub struct ScalePoint<T> {
    domain: Vec<T>,
    range_start: f32,
    range_tick: f32,
}

impl<T> ScalePoint<T>
where
    T: PartialEq,
{
    /// Place `domain` evenly from `range[0]` to `range[1]`; a single value sits
    /// in the middle of the range.
    ///
    /// # Examples
    ///
    /// ```ignore
    /// let scale = ScalePoint::new([1, 2, 3], [0., 100.]);
    /// assert_eq!(scale.tick(&1), Some(0.));
    /// assert_eq!(scale.tick(&2), Some(50.));
    /// assert_eq!(scale.tick(&3), Some(100.));
    /// ```
    pub fn new(domain: impl IntoIterator<Item = T>, range: [f32; 2]) -> Self {
        let domain: Vec<T> = domain.into_iter().collect();
        let len = domain.len();
        let range_diff = range[1] - range[0];
        let (range_start, range_tick) = match len {
            0 => (0., 0.),
            1 => (range[0], range_diff),
            _ => (range[0], range_diff / (len - 1) as f32),
        };

        Self {
            domain,
            range_start,
            range_tick,
        }
    }

    /// Returns the position of the domain value at `index`.
    ///
    /// Equivalent to [`Scale::tick`] on `domain[index]` for a domain of unique
    /// values, without searching the domain. Charts whose domain is built one
    /// entry per datum use this to project a series in linear time.
    pub fn tick_at(&self, index: usize) -> Option<f32> {
        let len = self.domain.len();
        if index >= len {
            return None;
        }

        if len == 1 {
            Some(self.range_start + self.range_tick / 2.)
        } else {
            Some(self.range_start + index as f32 * self.range_tick)
        }
    }
}

impl<T> Scale<T> for ScalePoint<T>
where
    T: PartialEq,
{
    fn tick(&self, value: &T) -> Option<f32> {
        let index = self.domain.iter().position(|v| v == value)?;
        self.tick_at(index)
    }

    fn nearest_index(&self, tick: f32) -> usize {
        if self.domain.is_empty() {
            return 0;
        }

        if self.range_tick == 0. {
            return 0;
        }

        let normalized_tick = tick - self.range_start;
        let index = (normalized_tick / self.range_tick).round() as usize;
        index.min(self.domain.len() - 1)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_scale_point() {
        let scale = ScalePoint::new(vec![1, 2, 3], [0., 100.]);
        assert_eq!(scale.tick(&1), Some(0.));
        assert_eq!(scale.tick(&2), Some(50.));
        assert_eq!(scale.tick(&3), Some(100.));
    }

    #[test]
    fn test_scale_point_range() {
        let scale = ScalePoint::new(vec![1, 2, 3], [40., 80.]);
        assert_eq!(scale.tick(&1), Some(40.));
        assert_eq!(scale.tick(&2), Some(60.));
        assert_eq!(scale.tick(&3), Some(80.));
    }

    #[test]
    fn test_scale_point_empty() {
        let scale = ScalePoint::new(vec![], [0., 100.]);
        assert_eq!(scale.tick(&1), None);
        assert_eq!(scale.tick(&2), None);
        assert_eq!(scale.tick(&3), None);

        let scale = ScalePoint::new(vec![1, 2, 3], [0., 0.]);
        assert_eq!(scale.tick(&1), Some(0.));
        assert_eq!(scale.tick(&2), Some(0.));
        assert_eq!(scale.tick(&3), Some(0.));
    }

    #[test]
    fn test_scale_point_single() {
        let scale = ScalePoint::new(vec![1], [0., 100.]);
        assert_eq!(scale.tick(&1), Some(50.));
    }

    #[test]
    fn test_tick_at_matches_tick() {
        for domain in [vec![], vec![1], vec![1, 2, 3], vec![1, 2, 3, 4, 5]] {
            let scale = ScalePoint::new(domain.clone(), [40., 80.]);
            for (i, value) in domain.iter().enumerate() {
                assert_eq!(scale.tick_at(i), scale.tick(value));
            }
            assert_eq!(scale.tick_at(domain.len()), None);
        }
    }

    #[test]
    fn test_nearest_index_basic() {
        let scale = ScalePoint::new(vec![1, 2, 3], [0., 100.]);

        // Exact positions
        assert_eq!(scale.nearest_index(0.), 0);
        assert_eq!(scale.nearest_index(50.), 1);
        assert_eq!(scale.nearest_index(100.), 2);

        // Between positions (should round to nearest)
        assert_eq!(scale.nearest_index(24.), 0); // closer to 0
        assert_eq!(scale.nearest_index(25.), 1); // equidistant, rounds to 1
        assert_eq!(scale.nearest_index(26.), 1); // closer to 50
        assert_eq!(scale.nearest_index(74.), 1); // closer to 50
        assert_eq!(scale.nearest_index(75.), 2); // equidistant, rounds to 2
        assert_eq!(scale.nearest_index(76.), 2); // closer to 100

        // Outside range
        assert_eq!(scale.nearest_index(-10.), 0); // below min
        assert_eq!(scale.nearest_index(150.), 2); // above max
    }

    #[test]
    fn test_nearest_index_with_offset() {
        let scale = ScalePoint::new(vec![1, 2, 3], [40., 80.]);

        // Exact positions: 40, 60, 80
        assert_eq!(scale.nearest_index(40.), 0);
        assert_eq!(scale.nearest_index(60.), 1);
        assert_eq!(scale.nearest_index(80.), 2);

        // Between positions
        assert_eq!(scale.nearest_index(49.), 0); // closer to 40
        assert_eq!(scale.nearest_index(50.), 1); // equidistant, rounds to 1
        assert_eq!(scale.nearest_index(51.), 1); // closer to 60
        assert_eq!(scale.nearest_index(69.), 1); // closer to 60
        assert_eq!(scale.nearest_index(70.), 2); // equidistant, rounds to 2
        assert_eq!(scale.nearest_index(71.), 2); // closer to 80

        // Outside range
        assert_eq!(scale.nearest_index(30.), 0); // below min
        assert_eq!(scale.nearest_index(100.), 2); // above max
    }

    #[test]
    fn test_nearest_index_empty() {
        let scale = ScalePoint::new(Vec::<i32>::new(), [0., 100.]);
        assert_eq!(scale.nearest_index(0.), 0);
        assert_eq!(scale.nearest_index(50.), 0);
        assert_eq!(scale.nearest_index(100.), 0);
    }

    #[test]
    fn test_nearest_index_single() {
        let scale = ScalePoint::new(vec![1], [0., 100.]);
        assert_eq!(scale.nearest_index(0.), 0);
        assert_eq!(scale.nearest_index(50.), 0);
        assert_eq!(scale.nearest_index(100.), 0);
    }

    #[test]
    fn test_nearest_index_empty_range() {
        let scale = ScalePoint::new(vec![1, 2, 3], [0., 0.]);
        assert_eq!(scale.nearest_index(0.), 0);
        assert_eq!(scale.nearest_index(50.), 0);
        assert_eq!(scale.nearest_index(100.), 0);
    }

    #[test]
    fn test_reversed_range() {
        let scale = ScalePoint::new([1, 2, 3], [100., 0.]);
        assert_eq!(scale.tick(&1), Some(100.));
        assert_eq!(scale.tick(&3), Some(0.));
        assert_eq!(scale.nearest_index(90.), 0);
        assert_eq!(scale.nearest_index(10.), 2);
    }
}
