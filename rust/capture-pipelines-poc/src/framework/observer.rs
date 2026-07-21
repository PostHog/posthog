//! Observers: read-only hooks over pipeline verdicts, composed as tuples — no
//! `Vec<Box<dyn Observer>>`.
//!
//! An [`Observer`] watches every verdict without cooperating with steps (step timing
//! metrics, dry-run verdict comparison, heavy-hitter aggregation). The framework's own
//! result metrics would be implemented as one such observer.
//!
//! Composition is by tuple: `(A, B, C)` is itself an `Observer` that fans out to each
//! member. [`impl_observer_tuple!`] generates the impls for arities 0–3. Because the
//! composed observer is a concrete tuple type, dispatch stays static — the runner is
//! generic over `O: Observer`, monomorphized per pipeline.

use crate::framework::result::VerdictKind;

/// A read-only hook invoked once per event with the deciding step's name and verdict.
pub trait Observer {
    /// Called after a step produces a verdict for one event.
    fn on_verdict(&self, step: &'static str, verdict: VerdictKind);
}

// References are observers too, so a tuple of borrowed observers — `(&a, &b)` — still
// satisfies the tuple impls without moving ownership into the tuple.
impl<T: Observer + ?Sized> Observer for &T {
    fn on_verdict(&self, step: &'static str, verdict: VerdictKind) {
        (**self).on_verdict(step, verdict);
    }
}

/// Generate [`Observer`] impls for tuples, fanning out to each member. Emits the
/// empty-tuple no-op impl and the 1..=N member impls.
#[macro_export]
macro_rules! impl_observer_tuple {
    () => {
        impl $crate::framework::observer::Observer for () {
            fn on_verdict(
                &self,
                _step: &'static str,
                _verdict: $crate::framework::result::VerdictKind,
            ) {
            }
        }
    };
    ($($t:ident),+) => {
        impl<$($t: $crate::framework::observer::Observer),+>
            $crate::framework::observer::Observer for ($($t,)+)
        {
            fn on_verdict(&self, step: &'static str, verdict: $crate::framework::result::VerdictKind) {
                #[allow(non_snake_case)]
                let ($($t,)+) = self;
                $( $t.on_verdict(step, verdict); )+
            }
        }
    };
}

impl_observer_tuple!();
impl_observer_tuple!(A);
impl_observer_tuple!(A, B);
impl_observer_tuple!(A, B, C);

/// A test/diagnostic observer that tallies verdicts by kind, using interior
/// mutability so `on_verdict(&self, …)` needs no `&mut`.
#[derive(Default)]
pub struct CountingObserver {
    counts: std::sync::Mutex<[u64; 4]>,
}

impl CountingObserver {
    /// A fresh observer with all counts at zero.
    pub fn new() -> Self {
        Self::default()
    }

    /// The number of verdicts of the given kind seen so far.
    pub fn count(&self, kind: VerdictKind) -> u64 {
        self.counts.lock().unwrap()[Self::index(kind)]
    }

    /// Total verdicts observed.
    pub fn total(&self) -> u64 {
        self.counts.lock().unwrap().iter().sum()
    }

    fn index(kind: VerdictKind) -> usize {
        match kind {
            VerdictKind::Continue => 0,
            VerdictKind::Drop => 1,
            VerdictKind::Dlq => 2,
            VerdictKind::Redirect => 3,
        }
    }
}

impl Observer for CountingObserver {
    fn on_verdict(&self, _step: &'static str, verdict: VerdictKind) {
        self.counts.lock().unwrap()[Self::index(verdict)] += 1;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tuple_observer_fans_out_to_every_member() {
        let a = CountingObserver::new();
        let b = CountingObserver::new();
        let observers = (&a, &b);

        observers.on_verdict("validate", VerdictKind::Continue);
        observers.on_verdict("restrict", VerdictKind::Redirect);

        assert_eq!(a.total(), 2);
        assert_eq!(b.total(), 2);
        assert_eq!(a.count(VerdictKind::Redirect), 1);
        assert_eq!(b.count(VerdictKind::Continue), 1);
    }

    #[test]
    fn empty_tuple_is_a_valid_noop_observer() {
        let observers = ();
        observers.on_verdict("x", VerdictKind::Drop); // compiles, does nothing
    }
}
