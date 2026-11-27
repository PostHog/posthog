use std::sync::atomic::{AtomicUsize, Ordering};

/// Takes `bytes` from `budget` only when that many remain, and returns whether it did.
// A hand-written `fetch_update`, because `try_update` is unstable on the toolchain this workspace pins, and newer
// toolchains that also build this crate deprecate `fetch_update`.
pub(crate) fn take(budget: &AtomicUsize, bytes: usize) -> bool {
    let mut left = budget.load(Ordering::Relaxed);
    while let Some(after) = left.checked_sub(bytes) {
        match budget.compare_exchange_weak(left, after, Ordering::Relaxed, Ordering::Relaxed) {
            Ok(_) => return true,
            Err(current) => left = current,
        }
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn takes_only_what_remains() {
        for (left, bytes, taken, left_after) in [
            (5, 3, true, 2),
            (5, 5, true, 0),
            (5, 6, false, 5),
            (0, 1, false, 0),
        ] {
            let budget = AtomicUsize::new(left);
            assert_eq!(take(&budget, bytes), taken, "{bytes} of {left}");
            assert_eq!(
                budget.load(Ordering::Relaxed),
                left_after,
                "{bytes} of {left}"
            );
        }
    }
}
