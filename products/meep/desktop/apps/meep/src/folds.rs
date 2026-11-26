use super::*;
use meep_ui::gpui_kit::component::ActiveTheme;
use std::{cell::Cell, collections::HashMap, time::Instant};

#[derive(Default)]
pub struct Folds(HashMap<SharedString, Fold>);

struct Fold {
    open: bool,
    from: f32,
    at: Cell<Option<Instant>>,
    toggled: Instant,
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
                toggled: Instant::now(),
            },
        );
    }

    pub fn progress(&self, key: &str, open: bool, cx: &App) -> f32 {
        let to = if open { 1. } else { 0. };
        let Some(fold) = self.0.get(key).filter(|f| f.open == open) else {
            return to;
        };
        let tokens = cx.theme().motion_tokens();
        let (duration, easing) = (tokens.duration_slow, ui::motion::ease_layout());
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
        Some(ui::motion::fold(
            ElementId::Name(SharedString::from(format!("fold:{part}"))),
            progress,
            content(),
        ))
    }

    pub fn moving(&mut self, cx: &App) -> bool {
        let tokens = cx.theme().motion_tokens();
        let longest = tokens.duration_slow;
        self.0.retain(|_, f| {
            f.at.get().map_or(f.toggled.elapsed() < longest * 2, |at| {
                at.elapsed() < longest
            })
        });
        !self.0.is_empty()
    }
}
