// @reference: https://d3js.org/d3-shape/stack

/// Represents a stacked series data point with lower and upper values
#[derive(Clone, Debug)]
#[non_exhaustive]
pub struct StackPoint<T> {
    /// The lower value (baseline)
    pub y0: f32,
    /// The upper value (topline)
    pub y1: f32,
    /// Reference to the original data
    pub data: T,
}

/// Represents a stacked series
#[derive(Clone, Debug)]
#[non_exhaustive]
pub struct StackSeries<T> {
    /// The key for this series
    pub key: String,
    /// The index of this series
    pub index: usize,
    /// The points in this series
    pub points: Vec<StackPoint<T>>,
}

#[allow(clippy::type_complexity)]
pub struct Stack<T> {
    data: Vec<T>,
    keys: Vec<String>,
    value: Box<dyn Fn(&T, &str) -> Option<f32>>,
}

impl<T: Clone> Default for Stack<T> {
    fn default() -> Self {
        Self {
            data: Vec::new(),
            keys: Vec::new(),
            value: Box::new(|_, _| None),
        }
    }
}

impl<T: Clone> Stack<T> {
    pub fn new() -> Self {
        Self::default()
    }

    /// Set the data to be stacked
    pub fn data<I>(mut self, data: I) -> Self
    where
        I: IntoIterator<Item = T>,
    {
        self.data = data.into_iter().collect();
        self
    }

    /// Set the keys (series) for stacking
    pub fn keys<I, S>(mut self, keys: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        self.keys = keys.into_iter().map(|s| s.into()).collect();
        self
    }

    /// Set the value accessor function
    pub fn value<F>(mut self, value: F) -> Self
    where
        F: Fn(&T, &str) -> Option<f32> + 'static,
    {
        self.value = Box::new(value);
        self
    }

    /// Compute the stacked series
    pub fn series(&self) -> Vec<StackSeries<T>> {
        if self.data.is_empty() || self.keys.is_empty() {
            return Vec::new();
        }

        let n = self.data.len(); // number of data points
        let m = self.keys.len(); // number of series

        // Extract values into a 2D matrix: series x data points
        let mut matrix: Vec<Vec<f32>> = Vec::with_capacity(m);
        for key in &self.keys {
            let mut series_values = Vec::with_capacity(n);
            for datum in &self.data {
                let value = (self.value)(datum, key).unwrap_or(0.0);
                series_values.push(value);
            }
            matrix.push(series_values);
        }

        // Use the natural key order for stacking
        let order: Vec<usize> = (0..m).collect();

        // Initialize stacks with zeros
        let mut stacks: Vec<Vec<(f32, f32)>> = vec![vec![(0.0, 0.0); n]; m];

        // Compute the stacks based on order
        for j in 0..n {
            let mut y0 = 0.0;
            for &i in &order {
                let y1 = y0 + matrix[i][j];
                stacks[i][j] = (y0, y1);
                y0 = y1;
            }
        }

        // Build the result series
        let mut result = Vec::with_capacity(m);
        for (i, key) in self.keys.iter().enumerate() {
            let points = self
                .data
                .iter()
                .enumerate()
                .map(|(j, datum)| StackPoint {
                    y0: stacks[i][j].0,
                    y1: stacks[i][j].1,
                    data: datum.clone(),
                })
                .collect();

            result.push(StackSeries {
                key: key.clone(),
                index: i,
                points,
            });
        }

        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Clone, Debug)]
    struct SalesData {
        #[allow(dead_code)]
        date: String,
        apples: f32,
        bananas: f32,
        cherries: f32,
    }

    #[test]
    fn test_basic_stack() {
        let data = vec![
            SalesData {
                date: "Jan".to_string(),
                apples: 10.0,
                bananas: 20.0,
                cherries: 30.0,
            },
            SalesData {
                date: "Feb".to_string(),
                apples: 15.0,
                bananas: 25.0,
                cherries: 35.0,
            },
        ];

        let stack = Stack::new()
            .data(data)
            .keys(vec!["apples", "bananas", "cherries"])
            .value(|d, key| match key {
                "apples" => Some(d.apples),
                "bananas" => Some(d.bananas),
                "cherries" => Some(d.cherries),
                _ => None,
            });

        let series = stack.series();

        assert_eq!(series.len(), 3);
        assert_eq!(series[0].key, "apples");
        assert_eq!(series[0].points[0].y0, 0.0);
        assert_eq!(series[0].points[0].y1, 10.0);

        assert_eq!(series[1].key, "bananas");
        assert_eq!(series[1].points[0].y0, 10.0);
        assert_eq!(series[1].points[0].y1, 30.0);

        assert_eq!(series[2].key, "cherries");
        assert_eq!(series[2].points[0].y0, 30.0);
        assert_eq!(series[2].points[0].y1, 60.0);
    }
}
