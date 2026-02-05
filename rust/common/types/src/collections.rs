use std::collections::HashMap;
use std::hash::Hash;

/// Extension trait for HashMap that provides efficient iteration methods.
pub trait HashMapExt<K, V> {
    /// Returns an iterator that yields owned key-value pairs by cloning.
    ///
    /// This is useful when you need to extend another HashMap from a reference
    /// without cloning the entire HashMap upfront.
    ///
    /// # Example
    /// ```
    /// use std::collections::HashMap;
    /// use common_types::collections::HashMapExt;
    ///
    /// let source: HashMap<String, i32> = [("a".to_string(), 1)].into_iter().collect();
    /// let mut target: HashMap<String, i32> = HashMap::new();
    ///
    /// // Instead of: target.extend(source.clone());
    /// // Use: target.extend(source.iter_owned());
    /// target.extend(source.iter_owned());
    /// ```
    fn iter_owned(&self) -> impl Iterator<Item = (K, V)>
    where
        K: Clone,
        V: Clone;
}

impl<K, V> HashMapExt<K, V> for HashMap<K, V>
where
    K: Eq + Hash,
{
    fn iter_owned(&self) -> impl Iterator<Item = (K, V)>
    where
        K: Clone,
        V: Clone,
    {
        self.iter().map(|(k, v)| (k.clone(), v.clone()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_iter_owned_extends_hashmap() {
        let source: HashMap<String, i32> = [("a".to_string(), 1), ("b".to_string(), 2)]
            .into_iter()
            .collect();
        let mut target: HashMap<String, i32> = [("c".to_string(), 3)].into_iter().collect();

        target.extend(source.iter_owned());

        assert_eq!(target.len(), 3);
        assert_eq!(target.get("a"), Some(&1));
        assert_eq!(target.get("b"), Some(&2));
        assert_eq!(target.get("c"), Some(&3));
    }

    #[test]
    fn test_iter_owned_overwrites_existing_keys() {
        let source: HashMap<String, i32> = [("a".to_string(), 100)].into_iter().collect();
        let mut target: HashMap<String, i32> = [("a".to_string(), 1)].into_iter().collect();

        target.extend(source.iter_owned());

        assert_eq!(target.get("a"), Some(&100));
    }

    #[test]
    fn test_iter_owned_empty_source() {
        let source: HashMap<String, i32> = HashMap::new();
        let mut target: HashMap<String, i32> = [("a".to_string(), 1)].into_iter().collect();

        target.extend(source.iter_owned());

        assert_eq!(target.len(), 1);
        assert_eq!(target.get("a"), Some(&1));
    }
}
