//! Bounded exact substring widths survive width-only reflows, including wrap-boundary crossings.

use gpui::Pixels;
use std::{
    collections::{HashMap, VecDeque},
    sync::Arc,
};

/// Keep only scalar results; native shaped runs and their GPU resources remain frame-owned.
#[derive(Default)]
pub(super) struct WidthMeasurements {
    /// Content keys also share common prefixes and suffixes between logical source lines.
    widths: HashMap<Arc<str>, Pixels>,
    /// FIFO eviction bounds retained source fragments without rescanning the document.
    order: VecDeque<Arc<str>>,
    /// Payload budget is separate from the entry limit that bounds map/queue overhead.
    text_bytes: usize,
}

impl WidthMeasurements {
    /// Return the exact native width previously measured with the current font configuration.
    pub(super) fn measure(&mut self, text: &str, measure: impl FnOnce() -> Pixels) -> Pixels {
        const MAX_ENTRIES: usize = 32_768;
        const MAX_TEXT_BYTES: usize = 4 * 1024 * 1024;
        if let Some(width) = self.widths.get(text) {
            return *width;
        }
        let width = measure();
        if text.len() > MAX_TEXT_BYTES {
            return width;
        }
        while self.widths.len() >= MAX_ENTRIES || self.text_bytes + text.len() > MAX_TEXT_BYTES {
            let Some(expired) = self.order.pop_front() else {
                break;
            };
            self.text_bytes -= expired.len();
            self.widths.remove(&expired);
        }
        let key: Arc<str> = text.into();
        self.text_bytes += key.len();
        self.order.push_back(key.clone());
        self.widths.insert(key, width);
        width
    }

    /// Text/font/tab-size/indent/inline updates delimit reuse; old measurements cannot survive.
    pub(super) fn clear(&mut self) {
        self.widths.clear();
        self.order.clear();
        self.text_bytes = 0;
    }
}
