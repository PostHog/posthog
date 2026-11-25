mod carousel;
mod scroll_mask;
mod state;

pub use carousel::{
    Carousel, CarouselContent, CarouselItem, CarouselNext, CarouselPagination,
    CarouselPaginationItem, CarouselPrevious,
};
pub use state::{CarouselEvent, CarouselState};

use gpui::{App, KeyBinding};

use crate::actions::{SelectDown, SelectFirst, SelectLast, SelectLeft, SelectRight, SelectUp};

pub(super) const CONTEXT: &str = "Carousel";

pub(crate) fn init(cx: &mut App) {
    cx.bind_keys([
        KeyBinding::new("left", SelectLeft, Some(CONTEXT)),
        KeyBinding::new("right", SelectRight, Some(CONTEXT)),
        KeyBinding::new("up", SelectUp, Some(CONTEXT)),
        KeyBinding::new("down", SelectDown, Some(CONTEXT)),
        KeyBinding::new("home", SelectFirst, Some(CONTEXT)),
        KeyBinding::new("end", SelectLast, Some(CONTEXT)),
    ]);
}
