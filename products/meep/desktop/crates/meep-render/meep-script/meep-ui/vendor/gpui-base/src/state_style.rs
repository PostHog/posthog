use gpui::{Refineable as _, StyleRefinement, Styled, prelude::FluentBuilder};

/// A semantic-state style builder.
///
/// Visual modifiers come from GPUI's [`Styled`] trait. Unlike a bare
/// [`StyleRefinement`], this wrapper also supports [`FluentBuilder`] helpers
/// such as `when`, `when_some`, and `when_none`.
#[derive(Default)]
pub struct StateStyle {
    refinement: StyleRefinement,
}

impl StateStyle {
    pub(crate) fn into_refinement(self) -> StyleRefinement {
        self.refinement
    }
}

impl Styled for StateStyle {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.refinement
    }
}

impl FluentBuilder for StateStyle {}

/// Resolves the final style of a control from its instance style and the
/// semantic-state styles that are currently active.
///
/// The layering order is fixed for every Base control:
///
/// 1. the instance style supplied through GPUI's [`Styled`] builder chain,
/// 2. value states such as `checked`, `pressed`, `selected`, or `focused`,
/// 3. `disabled`, which is always resolved last.
///
/// Semantic states therefore override the builder chain, matching how GPUI
/// layers `hover`, `active`, and `focus_visible` on top of an element's base
/// style. Callers pass their active states in the order above; inactive states
/// are simply omitted from the iterator.
///
/// Every control routes through this function so the ordering cannot drift
/// apart between controls again.
pub(crate) fn resolve_style<'a>(
    instance: &StyleRefinement,
    active_states: impl IntoIterator<Item = &'a StyleRefinement>,
) -> StyleRefinement {
    let mut style = StyleRefinement::default();
    style.refine(instance);
    for state in active_states {
        style.refine(state);
    }
    style
}

#[cfg(test)]
mod tests {
    use super::*;

    fn state(build: impl FnOnce(StateStyle) -> StateStyle) -> StyleRefinement {
        build(StateStyle::default()).into_refinement()
    }

    #[test]
    fn instance_style_is_the_baseline_when_no_state_is_active() {
        let instance = state(|style| style.opacity(0.9));

        let resolved = resolve_style(&instance, []);

        assert_eq!(resolved.opacity, Some(0.9));
    }

    #[test]
    fn an_active_state_overrides_the_instance_style() {
        let instance = state(|style| style.opacity(0.9));
        let checked = state(|style| style.opacity(0.8));

        let resolved = resolve_style(&instance, [&checked]);

        assert_eq!(resolved.opacity, Some(0.8));
    }

    #[test]
    fn later_states_override_earlier_states() {
        let instance = state(|style| style.opacity(0.9));
        let checked = state(|style| style.opacity(0.8));
        let disabled = state(|style| style.opacity(0.5));

        let resolved = resolve_style(&instance, [&checked, &disabled]);

        assert_eq!(resolved.opacity, Some(0.5));
    }

    #[test]
    fn states_only_override_the_fields_they_set() {
        let instance = state(|style| style.opacity(0.9).border_1());
        let disabled = state(|style| style.opacity(0.5));

        let resolved = resolve_style(&instance, [&disabled]);

        assert_eq!(resolved.opacity, Some(0.5));
        assert_eq!(instance.border_widths, resolved.border_widths);
    }
}
