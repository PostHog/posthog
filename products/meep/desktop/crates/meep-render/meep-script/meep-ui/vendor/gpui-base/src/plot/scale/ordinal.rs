// @reference: https://d3js.org/d3-scale/ordinal

#[derive(Clone)]
pub struct ScaleOrdinal<D, R> {
    domain: Vec<D>,
    range: Vec<R>,
    unknown: Option<R>,
}

impl<D, R> Default for ScaleOrdinal<D, R> {
    fn default() -> Self {
        Self {
            domain: Vec::new(),
            range: Vec::new(),
            unknown: None,
        }
    }
}

impl<D, R> ScaleOrdinal<D, R> {
    pub fn new(domain: Vec<D>, range: Vec<R>) -> Self {
        Self {
            domain,
            range,
            unknown: None,
        }
    }

    /// Set the domain to the specified array of values.
    pub fn domain(mut self, domain: Vec<D>) -> Self {
        self.domain = domain;
        self
    }

    /// Set the range of the ordinal scale to the specified array of values.
    pub fn range(mut self, range: Vec<R>) -> Self {
        self.range = range;
        self
    }

    /// Set the output value of the scale for unknown input values and returns this scale.
    pub fn unknown(mut self, unknown: R) -> Self {
        self.unknown = Some(unknown);
        self
    }
}

impl<D, R> ScaleOrdinal<D, R>
where
    D: PartialEq,
    R: Clone,
{
    /// Given a value in the input domain, returns the corresponding value in the output range.
    pub fn map(&self, value: &D) -> Option<R> {
        if let Some(index) = self.domain.iter().position(|v| v == value) {
            if self.range.is_empty() {
                None
            } else {
                Some(self.range[index % self.range.len()].clone())
            }
        } else {
            self.unknown.clone()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_scale_ordinal() {
        let scale = ScaleOrdinal::new(vec!["a", "b", "c", "d", "e"], vec![10, 20, 30]);

        assert_eq!(scale.map(&"a"), Some(10));
        assert_eq!(scale.map(&"b"), Some(20));
        assert_eq!(scale.map(&"c"), Some(30));
        assert_eq!(scale.map(&"d"), Some(10));
        assert_eq!(scale.map(&"e"), Some(20));
        assert_eq!(scale.map(&"f"), None);
    }

    #[test]
    fn test_scale_ordinal_unknown() {
        let scale = ScaleOrdinal::new(vec!["a", "b", "c"], vec![10, 20, 30]).unknown(0);

        assert_eq!(scale.map(&"a"), Some(10));
        assert_eq!(scale.map(&"f"), Some(0));
    }

    #[test]
    fn test_scale_ordinal_colors() {
        let keys = vec!["a", "b", "c", "d"];
        let colors = vec!["#1f77b4", "#ff7f0e", "#2ca02c"];

        let scale = ScaleOrdinal::new(keys, colors);

        assert_eq!(scale.map(&"a"), Some("#1f77b4"));
        assert_eq!(scale.map(&"b"), Some("#ff7f0e"));
        assert_eq!(scale.map(&"c"), Some("#2ca02c"));
        // Should cycle back to the first color
        assert_eq!(scale.map(&"d"), Some("#1f77b4"));
    }
}
