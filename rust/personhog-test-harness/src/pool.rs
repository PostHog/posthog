use std::sync::RwLock;

use rand::Rng;

/// The live traffic targets. The merge lane removes a source after the
/// merge ack, not before the call. The source keeps taking writes during
/// the merge, so the writes race the fence and the fold. That race is
/// the point of merging under load.
pub struct TargetPool {
    ids: RwLock<Vec<i64>>,
}

impl TargetPool {
    pub fn new(ids: Vec<i64>) -> Self {
        Self {
            ids: RwLock::new(ids),
        }
    }

    pub fn len(&self) -> usize {
        self.ids.read().unwrap().len()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    pub fn pick_random(&self, rng: &mut impl Rng) -> Option<i64> {
        let ids = self.ids.read().unwrap();
        if ids.is_empty() {
            return None;
        }
        Some(ids[rng.gen_range(0..ids.len())])
    }

    /// The person at `n` modulo the live count. None when the pool is
    /// empty.
    pub fn pick_nth(&self, n: usize) -> Option<i64> {
        let ids = self.ids.read().unwrap();
        if ids.is_empty() {
            return None;
        }
        Some(ids[n % ids.len()])
    }

    pub fn remove(&self, person_id: i64) -> bool {
        let mut ids = self.ids.write().unwrap();
        match ids.iter().position(|&id| id == person_id) {
            Some(index) => {
                ids.swap_remove(index);
                true
            }
            None => false,
        }
    }

    pub fn snapshot(&self) -> Vec<i64> {
        self.ids.read().unwrap().clone()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn picks_only_live_persons_and_empties_cleanly() {
        let pool = TargetPool::new(vec![1, 2, 3]);
        let mut rng = rand::thread_rng();
        assert!(pool.remove(2));
        assert!(!pool.remove(2));
        for _ in 0..100 {
            let picked = pool.pick_random(&mut rng).unwrap();
            assert!(picked == 1 || picked == 3);
        }
        assert_eq!(pool.pick_nth(1), Some(pool.snapshot()[1]));
        assert!(pool.remove(1));
        assert!(pool.remove(3));
        assert!(pool.is_empty());
        assert_eq!(pool.pick_random(&mut rng), None);
        assert_eq!(pool.pick_nth(7), None);
    }
}
