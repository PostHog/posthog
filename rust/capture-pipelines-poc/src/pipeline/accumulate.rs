//! A minimal *accumulating* pipeline shape: fold items into per-key state, flush on a
//! threshold. This is the replay/session-buffer pattern (buffer a session's events,
//! emit when it's big enough or the batch ends), shown here just to prove the shape
//! fits the static-dispatch framework.

use std::collections::HashMap;
use std::hash::Hash;

/// Buffers items per key and emits a `(key, batch)` when a key's buffer reaches the
/// flush threshold. Leftovers are released with [`drain`](Self::drain) at batch end.
pub struct Accumulating<K, T> {
    threshold: usize,
    buffers: HashMap<K, Vec<T>>,
}

impl<K: Eq + Hash + Clone, T> Accumulating<K, T> {
    /// A new accumulator that flushes a key once it holds `threshold` items.
    pub fn new(threshold: usize) -> Self {
        assert!(threshold >= 1, "threshold must be positive");
        Accumulating {
            threshold,
            buffers: HashMap::new(),
        }
    }

    /// Fold one item into its key's buffer. Returns `Some((key, batch))` when that push
    /// reaches the threshold (the buffer is emitted and reset), else `None`.
    pub fn accumulate(&mut self, key: K, item: T) -> Option<(K, Vec<T>)> {
        let buffer = self.buffers.entry(key.clone()).or_default();
        buffer.push(item);
        if buffer.len() >= self.threshold {
            let flushed = self.buffers.remove(&key).expect("just inserted");
            Some((key, flushed))
        } else {
            None
        }
    }

    /// Flush every remaining buffer (end-of-batch drain).
    pub fn drain(&mut self) -> Vec<(K, Vec<T>)> {
        self.buffers.drain().collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn flushes_on_threshold_and_drains_the_rest() {
        let mut acc: Accumulating<&str, i32> = Accumulating::new(3);

        assert!(acc.accumulate("a", 1).is_none());
        assert!(acc.accumulate("b", 10).is_none());
        assert!(acc.accumulate("a", 2).is_none());
        // Third "a" hits the threshold and flushes that key's buffer, in order.
        assert_eq!(acc.accumulate("a", 3), Some(("a", vec![1, 2, 3])));

        // "a" starts fresh after a flush; "b" still holds its single item.
        assert!(acc.accumulate("a", 4).is_none());

        let mut leftovers = acc.drain();
        leftovers.sort_by_key(|(k, _)| *k);
        assert_eq!(leftovers, vec![("a", vec![4]), ("b", vec![10])]);
    }
}
