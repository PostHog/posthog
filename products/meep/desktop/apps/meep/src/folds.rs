use super::*;
use meep_ui::gpui_kit::base::MotionReveal;
use meep_ui::gpui_kit::component::ActiveTheme;
use std::{cell::Cell, collections::HashMap, time::Instant};

#[derive(Default)]
pub struct Folds(HashMap<SharedString, Fold>);

struct Fold {
    open: bool,
    from: f32,
    at: Cell<Option<Instant>>,
}

impl Folds {
    pub fn toggled(&mut self, key: impl Into<SharedString>, open: bool, cx: &App) {
        let key = key.into();
        let from = self.progress(&key, !open, cx);
        self.0.insert(
            key,
            Fold {
                open,
                from,
                at: Cell::new(None),
            },
        );
    }

    pub fn progress(&self, key: &str, open: bool, cx: &App) -> f32 {
        let to = if open { 1. } else { 0. };
        let Some(fold) = self.0.get(key).filter(|f| f.open == open) else {
            return to;
        };
        let tokens = cx.theme().motion_tokens();
        let (duration, easing) = if open {
            (tokens.duration_normal, &tokens.easing_enter)
        } else {
            (tokens.duration_fast, &tokens.easing_exit)
        };
        let Some(at) = fold.at.get() else {
            fold.at.set(Some(Instant::now()));
            return if duration.is_zero() { to } else { fold.from };
        };
        if duration.is_zero() {
            return to;
        }
        let t = at.elapsed().as_secs_f32() / duration.as_secs_f32();
        fold.from + (to - fold.from) * easing.sample(t)
    }

    pub fn reveal(
        &self,
        key: &str,
        open: bool,
        cx: &App,
        content: impl FnOnce() -> AnyElement,
    ) -> Option<AnyElement> {
        self.reveal_as(key, key, open, cx, content)
    }

    pub fn reveal_as(
        &self,
        key: &str,
        part: &str,
        open: bool,
        cx: &App,
        content: impl FnOnce() -> AnyElement,
    ) -> Option<AnyElement> {
        let progress = self.progress(key, open, cx);
        if progress <= 0. && !open {
            return None;
        }
        let content = content();
        Some(if progress >= 1. {
            content
        } else {
            MotionReveal::new(
                ElementId::Name(SharedString::from(format!("fold:{part}"))),
                progress,
                content,
            )
            .into_any_element()
        })
    }

    pub fn moving(&mut self, cx: &App) -> bool {
        let tokens = cx.theme().motion_tokens();
        let longest = tokens.duration_normal.max(tokens.duration_fast);
        self.0
            .retain(|_, f| f.at.get().is_none_or(|at| at.elapsed() < longest));
        !self.0.is_empty()
    }
}
