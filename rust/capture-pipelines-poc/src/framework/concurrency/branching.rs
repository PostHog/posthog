//! `Branching`: a classifier routes each event to one of several sub-pipelines that
//! produce a common output — exhaustiveness enforced by `match`.
//!
//! Node enforces "every branch supplied" with a type-level `Exclude<TRemaining, B>`
//! trick that makes `build()` uncompilable until `TRemaining = never`. The Rust answer
//! is simpler and stronger: the router is a `match` over a user enum. Adding a variant
//! turns every router `match` into a non-exhaustive-match **compile error** until each
//! site handles it — the same guarantee, delivered by the compiler's exhaustiveness
//! check instead of a builder-state trick.

use crate::framework::result::{Outputs, StepResult};
use crate::framework::step::Step;
use std::marker::PhantomData;

/// A branching step. `classify` maps an event to a user branch enum `K`; `route`
/// dispatches on `K` (an exhaustive `match`) to a sub-pipeline, all branches producing
/// the same `Out`/`Outputs`.
pub struct Branching<K, C, R> {
    classify: C,
    route: R,
    _k: PhantomData<fn() -> K>,
}

impl<K, C, R> Branching<K, C, R> {
    /// Build a branching step from a classifier and an (exhaustive) router.
    pub fn new(classify: C, route: R) -> Self {
        Branching {
            classify,
            route,
            _k: PhantomData,
        }
    }
}

impl<In, Fx, K, C, R, Out, O> Step<In, Fx> for Branching<K, C, R>
where
    C: Fn(&In) -> K,
    R: Fn(K, In, &mut Fx) -> StepResult<Out, O>,
    O: Outputs,
{
    type Out = Out;
    type Outputs = O;

    fn apply(&self, event: In, fx: &mut Fx) -> StepResult<Out, O> {
        let branch = (self.classify)(&event);
        (self.route)(branch, event, fx)
    }

    fn name(&self) -> &'static str {
        "branching"
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::framework::result::NoOutputs;

    // A user branch enum. Adding `Route::Archive` here would make the `match` in
    // `route` below fail to compile until it is handled — the exhaustiveness guarantee.
    #[derive(Clone, Copy)]
    enum Route {
        Even,
        Odd,
    }

    // Two sub-steps producing a common Out (i64).
    struct Doubled;
    impl<Fx> Step<i64, Fx> for Doubled {
        type Out = i64;
        type Outputs = NoOutputs;
        fn apply(&self, event: i64, _fx: &mut Fx) -> StepResult<i64, NoOutputs> {
            StepResult::Continue(event * 2)
        }
        fn name(&self) -> &'static str {
            "doubled"
        }
    }
    struct Negated;
    impl<Fx> Step<i64, Fx> for Negated {
        type Out = i64;
        type Outputs = NoOutputs;
        fn apply(&self, event: i64, _fx: &mut Fx) -> StepResult<i64, NoOutputs> {
            StepResult::Continue(-event)
        }
        fn name(&self) -> &'static str {
            "negated"
        }
    }

    #[test]
    fn routes_each_event_to_its_branch() {
        let even = Doubled;
        let odd = Negated;
        let branching = Branching::new(
            |e: &i64| {
                if e % 2 == 0 {
                    Route::Even
                } else {
                    Route::Odd
                }
            },
            move |route, event, fx: &mut ()| match route {
                Route::Even => even.apply(event, fx),
                Route::Odd => odd.apply(event, fx),
            },
        );

        let mut fx = ();
        // 4 is even -> doubled = 8
        assert!(matches!(
            branching.apply(4, &mut fx),
            StepResult::Continue(8)
        ));
        // 3 is odd -> negated = -3
        assert!(matches!(
            branching.apply(3, &mut fx),
            StepResult::Continue(-3)
        ));
    }
}
