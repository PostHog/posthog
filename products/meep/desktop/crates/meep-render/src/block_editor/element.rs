//! The element that draws a block editor's document. It lays out to the
//! document's height, paints only the blocks in view, and handles the
//! pointer: caret placement, word and block selection, dragging a
//! selection, the checkbox, and the gutter's + and drag handle.
use super::layout::{self, BlockLayout};
use super::model::*;
use super::*;

pub struct DocumentElement {
    editor: Entity<BlockEditor>,
}

impl DocumentElement {
    pub fn new(editor: Entity<BlockEditor>) -> Self {
        Self { editor }
    }
}

impl IntoElement for DocumentElement {
    type Element = Self;
    fn into_element(self) -> Self::Element {
        self
    }
}

/// Space below the last block: clicking there continues the document.
const BOTTOM: f32 = 48.;

impl Element for DocumentElement {
    type RequestLayoutState = ();
    type PrepaintState = Hitbox;

    fn id(&self) -> Option<ElementId> {
        None
    }
    fn source_location(&self) -> Option<&'static std::panic::Location<'static>> {
        None
    }

    fn request_layout(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        window: &mut Window,
        _: &mut App,
    ) -> (LayoutId, ()) {
        let mut style = gpui_kit::Style::default();
        style.size.width = relative(1.).into();
        let editor = self.editor.clone();
        let id = window.request_measured_layout(style, move |known, available, window, cx| {
            let width = known.width.unwrap_or(match available.width {
                AvailableSpace::Definite(w) => w,
                _ => px(720.),
            });
            let height = editor.update(cx, |e, _| {
                e.ensure_layout(width, window);
                e.geo.total
            });
            size(width, height + px(BOTTOM))
        });
        (id, ())
    }

    fn prepaint(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        bounds: Bounds<Pixels>,
        _: &mut (),
        window: &mut Window,
        cx: &mut App,
    ) -> Hitbox {
        self.editor.update(cx, |e, cx| {
            e.bounds = bounds;
            e.sync_focus(window, cx);
            e.ensure_layout(bounds.size.width, window);
        });
        window.insert_hitbox(bounds, HitboxBehavior::Normal)
    }

    fn paint(
        &mut self,
        _: Option<&GlobalElementId>,
        _: Option<&InspectorElementId>,
        bounds: Bounds<Pixels>,
        _: &mut (),
        hitbox: &mut Hitbox,
        window: &mut Window,
        cx: &mut App,
    ) {
        let focus = self.editor.read(cx).focus.clone();
        window.handle_input(
            &focus,
            ElementInputHandler::new(bounds, self.editor.clone()),
            cx,
        );
        listen(&self.editor, bounds, hitbox, window, cx);
        let editor = self.editor.clone();
        editor.update(cx, |e, cx| e.paint(bounds, hitbox, window, cx));
    }
}

/// The parts of a block row the pointer can be over.
enum Spot {
    Plus(usize),
    Handle(usize),
    Checkbox(usize),
    Text(Pos, bool),
}

impl BlockEditor {
    /// Gutter controls' rectangles for block `i`, from the element's
    /// top-left: (+, handle).
    pub fn gutter_rects(&self, i: usize) -> (Bounds<Pixels>, Bounds<Pixels>) {
        let l = &self.geo.layouts[i];
        let left = self.block_left(i);
        let center = if l.kind == Kind::Divider {
            self.geo.tops[i] + l.height / 2.
        } else {
            self.geo.tops[i] + l.text_y + l.line_height / 2.
        };
        let handle = Bounds::new(
            point(left - px(22.), center - px(12.)),
            size(px(18.), px(24.)),
        );
        let plus = Bounds::new(
            point(left - px(46.), center - px(12.)),
            size(px(24.), px(24.)),
        );
        (plus, handle)
    }

    pub fn checkbox_rect(&self, i: usize) -> Bounds<Pixels> {
        let l = &self.geo.layouts[i];
        let left = self.block_left(i);
        let cy = self.geo.tops[i] + l.text_y + l.line_height / 2.;
        let cx = left + px(layout::MARKER / 2.);
        Bounds::new(point(cx - px(8.), cy - px(8.)), size(px(16.), px(16.)))
    }

    fn spot(&self, p: Point<Pixels>) -> Spot {
        let i = self.block_at_y(p.y.min(self.geo.total - px(1.)).max(px(0.)));
        if !self.read_only && self.gutter && i < self.geo.layouts.len() {
            let (plus, handle) = self.gutter_rects(i);
            if plus.contains(&p) {
                return Spot::Plus(i);
            }
            if handle.contains(&p) {
                return Spot::Handle(i);
            }
        }
        if i < self.doc.len()
            && self.doc.block(i).kind == Kind::Todo
            && self.checkbox_rect(i).dilate(px(3.)).contains(&p)
        {
            return Spot::Checkbox(i);
        }
        let (pos, upstream) = self.pos_at(p);
        Spot::Text(pos, upstream)
    }

    fn mouse_down(
        &mut self,
        event: &MouseDownEvent,
        bounds: Bounds<Pixels>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let p = event.position - bounds.origin;
        self.menu = None;
        self.typing = false;
        if !self.focus.is_focused(window) {
            self.focus.focus(window, cx);
        }
        // Below the last block: continue the document there.
        if p.y > self.geo.total && !self.read_only {
            let last = self.doc.len() - 1;
            let b = self.doc.block(last);
            if !(b.kind == Kind::Paragraph && b.is_empty()) {
                self.insert_block_after(last, Kind::Paragraph, window, cx);
                self.goal_x = None;
                return;
            }
        }
        match self.spot(p) {
            Spot::Plus(i) => {
                // Option-click adds above.
                let at = if event.modifiers.alt {
                    let mut at = i;
                    self.transact(EditKind::Other, window, cx, |e, _, _| {
                        let mut b = Block::new(Kind::Paragraph, "");
                        b.indent = e.doc.block(i).indent;
                        e.doc.blocks.insert(i, Rc::new(b));
                        e.sel = Selection::caret(Pos::new(i, 0));
                        at = i;
                    });
                    at
                } else {
                    let b = self.doc.block(i);
                    if b.kind == Kind::Paragraph && b.is_empty() {
                        self.set_selection(Selection::caret(Pos::new(i, 0)), window, cx);
                        i
                    } else {
                        self.insert_block_after(i, Kind::Paragraph, window, cx)
                    }
                };
                // As if "/" was typed: the menu opens on the new block.
                self.insert_text("/", true, window, cx);
                if !matches!(self.menu, Some(Menu::Slash { .. })) {
                    self.menu = Some(Menu::Slash {
                        block: at,
                        offset: 0,
                        selected: 0,
                    });
                }
            }
            Spot::Handle(i) => {
                let span = if self.sel.blocks && self.sel.block_span().contains(&i) {
                    self.sel.block_span()
                } else {
                    self.doc.subtree(i)
                };
                self.gesture = Some(Gesture::Handle {
                    block: i,
                    start: event.position,
                    moving: false,
                    span,
                    target: i,
                    pointer: event.position,
                    indicator: None,
                });
                cx.notify();
            }
            Spot::Checkbox(i) => self.toggle_checked(i, window, cx),
            Spot::Text(pos, upstream) => {
                if event.modifiers.platform
                    && let Some((_, url)) = self.doc.block(pos.block).link_at(pos.offset)
                {
                    if crate::links::web_url(&url).is_ok() {
                        cx.open_url(&url);
                    }
                    return;
                }
                let block = self.doc.block(pos.block);
                if block.kind == Kind::Divider {
                    self.set_selection(Selection::block_range(pos.block, pos.block), window, cx);
                    return;
                }
                let unit = event.click_count.clamp(1, 3) as u8;
                let sel = match unit {
                    2 => {
                        let w = word_at(&block.text, pos.offset);
                        Selection::range(Pos::new(pos.block, w.start), Pos::new(pos.block, w.end))
                    }
                    3 => Selection::range(Pos::new(pos.block, 0), Pos::new(pos.block, block.len())),
                    _ if event.modifiers.shift && !self.sel.blocks => {
                        Selection::range(self.sel.anchor, pos)
                    }
                    _ => Selection::caret(pos),
                };
                self.set_selection(sel, window, cx);
                self.upstream = upstream && sel.is_caret();
                self.goal_x = None;
                self.gesture = Some(Gesture::Select { unit, origin: sel });
            }
        }
    }

    fn mouse_move(
        &mut self,
        event: &MouseMoveEvent,
        bounds: Bounds<Pixels>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let p = event.position - bounds.origin;
        match &mut self.gesture {
            Some(Gesture::Select { unit, origin })
                if event.pressed_button == Some(MouseButton::Left) =>
            {
                let (unit, origin) = (*unit, *origin);
                let (pos, _) = self.pos_at(p);
                let sel = match unit {
                    2 => {
                        let text = &self.doc.block(pos.block).text;
                        let w = word_at(text, pos.offset);
                        if pos < origin.start() {
                            Selection::range(origin.end(), Pos::new(pos.block, w.start))
                        } else {
                            Selection::range(origin.start(), Pos::new(pos.block, w.end))
                        }
                    }
                    3 => {
                        let len = self.doc.block(pos.block).len();
                        if pos.block < origin.start().block {
                            Selection::range(origin.end(), Pos::new(pos.block, 0))
                        } else {
                            Selection::range(origin.start(), Pos::new(pos.block, len))
                        }
                    }
                    _ => Selection::range(origin.anchor, pos),
                };
                if sel != self.sel {
                    self.sel = sel;
                    self.upstream = false;
                    self.pending = None;
                    window.notify_text_selection_changed(&self.focus);
                    cx.notify();
                }
                self.drag_autoscroll(event.position, window);
            }
            Some(Gesture::Handle {
                start,
                moving,
                span,
                target,
                pointer,
                ..
            }) => {
                if !*moving && (event.position - *start).magnitude() > 4. {
                    *moving = true;
                    self.menu = None;
                }
                if *moving {
                    *pointer = event.position;
                    // The gap nearest the pointer, outside the dragged blocks.
                    let n = self.doc.len();
                    let y = p.y;
                    let mut best = 0;
                    let mut best_d = f32::MAX;
                    for g in 0..=n {
                        if g > span.start && g < span.end {
                            continue;
                        }
                        let gy = gap_y(&self.geo, g);
                        let d = (f32::from(gy) - f32::from(y)).abs();
                        if d < best_d {
                            best_d = d;
                            best = g;
                        }
                        if gy > y + px(200.) {
                            break;
                        }
                    }
                    *target = best;
                    self.drag_autoscroll(event.position, window);
                    cx.notify();
                }
            }
            _ => {
                if !bounds.contains(&event.position) || event.pressed_button.is_some() {
                    if self.hover.is_some() && event.pressed_button.is_none() {
                        self.hover = None;
                        cx.notify();
                    }
                    return;
                }
                self.typing = false;
                if self.geo.layouts.is_empty() {
                    return;
                }
                let i = self.block_at_y(p.y.min(self.geo.total - px(1.)).max(px(0.)));
                let part = match self.spot(p) {
                    Spot::Plus(_) => GutterPart::Plus,
                    Spot::Handle(_) => GutterPart::Handle,
                    _ => GutterPart::None,
                };
                let checkbox = matches!(self.spot(p), Spot::Checkbox(_));
                let same = self
                    .hover
                    .is_some_and(|h| h.block == i && h.part == part && h.checkbox == checkbox);
                if !same {
                    let since = match self.hover {
                        Some(h) if h.block == i => h.since,
                        _ => Instant::now(),
                    };
                    self.hover = Some(Hover {
                        block: i,
                        part,
                        since,
                        checkbox,
                    });
                    cx.notify();
                }
            }
        }
    }

    fn mouse_up(&mut self, _event: &MouseUpEvent, window: &mut Window, cx: &mut Context<Self>) {
        match self.gesture.take() {
            Some(Gesture::Handle {
                block,
                moving: false,
                ..
            }) => {
                // A click on the handle selects the block and opens its menu.
                let span = if self.sel.blocks && self.sel.block_span().contains(&block) {
                    self.sel
                } else {
                    Selection::block_range(block, block)
                };
                self.set_selection(span, window, cx);
                self.menu = Some(Menu::Block { block, selected: 0 });
                cx.notify();
            }
            Some(Gesture::Handle {
                moving: true,
                span,
                target,
                ..
            }) => {
                if self.sel.blocks && self.sel.block_span() == span {
                } else {
                    self.sel = Selection::block_range(span.start, span.end - 1);
                }
                self.move_span(span, target, window, cx);
                cx.notify();
            }
            Some(Gesture::Select { .. }) => cx.notify(),
            None => {}
        }
    }

    /// While dragging near the editor's top or bottom edge, scroll it.
    fn drag_autoscroll(&mut self, pointer: Point<Pixels>, window: &mut Window) {
        let view = self.scroll.bounds();
        if view.size.height <= px(0.) {
            return;
        }
        let edge = px(24.);
        let offset = self.scroll.offset();
        let delta = if pointer.y < view.top() + edge {
            (view.top() + edge - pointer.y).min(px(40.))
        } else if pointer.y > view.bottom() - edge {
            -(pointer.y - (view.bottom() - edge)).min(px(40.))
        } else {
            return;
        };
        let max = self.scroll.max_offset().y;
        let y = (offset.y + delta * 0.5).clamp(-max, px(0.));
        if y != offset.y {
            self.scroll.set_offset(point(offset.x, y));
            window.refresh();
        }
    }

    // ---- Painting -------------------------------------------------------------

    fn paint(
        &mut self,
        bounds: Bounds<Pixels>,
        hitbox: &Hitbox,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let colors = self.colors;
        let origin = bounds.origin;
        let mask = window.content_mask().bounds;
        let view = bounds.intersect(&mask);
        let range = self.visible(view.top() - origin.y, view.bottom() - origin.y);
        // Cursor: an I-beam over text, an arrow in the gutter.
        let pointer = window.mouse_position() - origin;
        let cursor = if hitbox.is_hovered(window) {
            match self.hover {
                Some(h) if h.part == GutterPart::Handle => CursorStyle::OpenHand,
                Some(h) if h.part == GutterPart::Plus || h.checkbox => CursorStyle::PointingHand,
                _ if pointer.x < self.gutter_width() => CursorStyle::Arrow,
                _ => CursorStyle::IBeam,
            }
        } else {
            CursorStyle::IBeam
        };
        if matches!(self.gesture, Some(Gesture::Handle { moving: true, .. })) {
            window.set_cursor_style(CursorStyle::ClosedHand, hitbox);
        } else {
            window.set_cursor_style(cursor, hitbox);
        }
        let sel_span = self.sel.block_span();
        let focused = self.focused;
        let show_selection = focused || !self.sel.is_caret();
        let dragging = match &self.gesture {
            Some(Gesture::Handle {
                moving: true, span, ..
            }) => Some(span.clone()),
            _ => None,
        };
        for i in range.clone() {
            let l = self.geo.layouts[i].clone();
            let top = origin.y + self.geo.tops[i];
            let left = origin.x + self.block_left(i);
            let right = origin.x + bounds.size.width;
            let block = self.doc.blocks[i].clone();
            // Whole-block selection.
            let block_selected = (self.sel.blocks && sel_span.contains(&i))
                || (!self.sel.blocks
                    && block.kind == Kind::Divider
                    && sel_span.contains(&i)
                    && !self.sel.is_caret()
                    && i != self.sel.start().block);
            if block_selected && show_selection {
                window.paint_quad(
                    fill(
                        Bounds::from_corners(
                            point(left - px(4.), top - px(1.)),
                            point(right, top + l.height + px(1.)),
                        ),
                        colors.block_selection(),
                    )
                    .corner_radii(px(4.)),
                );
            }
            if dragging.as_ref().is_some_and(|s| s.contains(&i)) {
                window.paint_quad(
                    fill(
                        Bounds::from_corners(
                            point(left - px(4.), top - px(1.)),
                            point(right, top + l.height + px(1.)),
                        ),
                        colors.ink_alpha(0.04),
                    )
                    .corner_radii(px(4.)),
                );
            }
            self.paint_block(i, &block, &l, point(left, top), right, window, cx);
            // Text selection behind the caret, over the text background.
            if !self.sel.blocks
                && !self.sel.is_caret()
                && sel_span.contains(&i)
                && block.kind.has_text()
            {
                let (s, e) = (self.sel.start(), self.sel.end());
                let a = if i == s.block { s.offset } else { 0 };
                let z = if i == e.block { e.offset } else { block.len() };
                let text_origin = point(left + l.text_x, top + l.text_y);
                let color = if focused {
                    colors.selection()
                } else {
                    colors.ink_alpha(0.1)
                };
                for r in l.range_rects(a..z, i < e.block) {
                    window.paint_quad(fill(r + text_origin, color));
                }
            }
        }
        // Text over the selection.
        for i in range.clone() {
            let l = self.geo.layouts[i].clone();
            let top = origin.y + self.geo.tops[i];
            let left = origin.x + self.block_left(i);
            let text_origin = point(left + l.text_x, top + l.text_y);
            for (k, line) in l.lines.iter().enumerate() {
                let y = l
                    .visual
                    .iter()
                    .find(|v| v.line == k)
                    .map(|v| v.y)
                    .unwrap_or_default();
                let _ = line.paint(
                    point(text_origin.x, text_origin.y + y),
                    l.line_height,
                    TextAlign::Left,
                    None,
                    window,
                    cx,
                );
            }
            self.paint_placeholder(i, &l, text_origin, window, cx);
        }
        // Caret.
        if focused
            && self.caret_on
            && self.sel.is_caret()
            && !self.read_only
            && range.contains(&self.sel.head.block)
            && let Some(r) = self.caret_rect(self.sel.head, self.upstream)
        {
            window.paint_quad(fill(r + origin, colors.ink).corner_radii(px(1.)));
        }
        self.paint_gutter(origin, window);
        self.paint_drag(bounds, window, cx);
    }

    #[allow(clippy::too_many_arguments)]
    fn paint_block(
        &self,
        i: usize,
        block: &Block,
        l: &BlockLayout,
        at: Point<Pixels>,
        right: Pixels,
        window: &mut Window,
        cx: &mut App,
    ) {
        let colors = &self.colors;
        let m = &l.metrics;
        let text_origin = point(at.x + l.text_x, at.y + l.text_y);
        let first_center = text_origin.y + l.line_height / 2.;
        match block.kind {
            Kind::Code => {
                window.paint_quad(
                    fill(
                        Bounds::from_corners(at, point(right, at.y + l.height)),
                        colors.code_bg(),
                    )
                    .corner_radii(px(6.)),
                );
            }
            Kind::Quote => {
                window.paint_quad(fill(
                    Bounds::new(
                        point(at.x + px(1.), at.y + px(m.pad_top)),
                        size(px(3.), l.height - px(m.pad_top + m.pad_bottom)),
                    ),
                    colors.ink,
                ));
            }
            Kind::Divider => {
                let y = at.y + l.height / 2.;
                window.paint_quad(fill(
                    Bounds::from_corners(
                        point(at.x + px(2.), y - px(0.5)),
                        point(right, y + px(0.5)),
                    ),
                    colors.ink_alpha(if colors.dark { 0.2 } else { 0.13 }),
                ));
            }
            Kind::Bullet => {
                let c = point(at.x + px(layout::MARKER / 2.), first_center);
                match block.indent % 3 {
                    0 => {
                        let r = px(3.);
                        window.paint_quad(
                            fill(
                                Bounds::new(c - point(r, r), size(r * 2., r * 2.)),
                                colors.ink,
                            )
                            .corner_radii(r),
                        );
                    }
                    1 => {
                        let r = px(3.);
                        window.paint_quad(
                            outline(
                                Bounds::new(c - point(r, r), size(r * 2., r * 2.)),
                                colors.ink,
                                BorderStyle::Solid,
                            )
                            .corner_radii(r)
                            .border_widths(px(1.2)),
                        );
                    }
                    _ => {
                        let r = px(2.6);
                        window.paint_quad(fill(
                            Bounds::new(c - point(r, r), size(r * 2., r * 2.)),
                            colors.ink,
                        ));
                    }
                }
            }
            Kind::Numbered => {
                let label = numbered_label(self.geo.numbers[i], block.indent);
                let line =
                    layout::shape_line(&label, m.font_size, colors.ink, FontWeight::NORMAL, window);
                let marker = self.geo.markers[i];
                // Centered in the marker column, like Notion.
                let x = at.x + ((marker - line.width()) / 2.).max(px(0.));
                let _ = line.paint(
                    point(x, text_origin.y),
                    l.line_height,
                    TextAlign::Left,
                    None,
                    window,
                    cx,
                );
            }
            Kind::Todo => {
                let r = self.checkbox_rect(i) + (at - point(self.block_left(i), self.geo.tops[i]));
                let hovered = self.hover.is_some_and(|h| h.block == i && h.checkbox);
                if block.checked {
                    window.paint_quad(fill(r, colors.accent).corner_radii(px(3.)));
                    let mut path = PathBuilder::stroke(px(1.8));
                    path.move_to(r.origin + point(px(3.8), px(8.3)));
                    path.line_to(r.origin + point(px(6.7), px(11.)));
                    path.line_to(r.origin + point(px(12.3), px(5.)));
                    if let Ok(path) = path.build() {
                        window.paint_path(path, colors.accent_fg);
                    }
                } else {
                    if hovered {
                        window.paint_quad(fill(r, colors.hover()).corner_radii(px(3.)));
                    }
                    window.paint_quad(
                        outline(r, colors.ink_alpha(0.85), BorderStyle::Solid)
                            .corner_radii(px(3.))
                            .border_widths(px(1.5)),
                    );
                }
            }
            _ => {}
        }
        // Inline code backgrounds, under the text.
        if block.kind != Kind::Code && block.marks.iter().any(|m| m.style == Style::Code) {
            for (k, line) in l.lines.iter().enumerate() {
                let y = l
                    .visual
                    .iter()
                    .find(|v| v.line == k)
                    .map(|v| v.y)
                    .unwrap_or_default();
                let _ = line.paint_background(
                    point(text_origin.x, text_origin.y + y),
                    l.line_height,
                    TextAlign::Left,
                    None,
                    window,
                    cx,
                );
            }
        }
    }

    fn placeholder_for(&self, i: usize) -> Option<SharedString> {
        let block = self.doc.block(i);
        if !block.is_empty() || block.kind == Kind::Divider {
            return None;
        }
        let editing_here = self.focused
            && self.sel.is_caret()
            && self.sel.head.block == i
            && self.marked.is_none();
        let heading = match block.kind {
            Kind::H1 => Some("Heading 1"),
            Kind::H2 => Some("Heading 2"),
            Kind::H3 => Some("Heading 3"),
            _ => None,
        };
        if let Some(h) = heading {
            return Some(h.into());
        }
        if self.doc.len() == 1 && !editing_here {
            return self.placeholder.clone();
        }
        if !editing_here || self.read_only {
            return None;
        }
        Some(match block.kind {
            Kind::Bullet | Kind::Numbered => "List".into(),
            Kind::Todo => "To-do".into(),
            Kind::Quote => "Empty quote".into(),
            Kind::Code => return None,
            _ => self
                .placeholder
                .clone()
                .filter(|_| self.doc.len() == 1)
                .unwrap_or_else(|| "Type '/' for commands".into()),
        })
    }

    fn paint_placeholder(
        &self,
        i: usize,
        l: &BlockLayout,
        at: Point<Pixels>,
        window: &mut Window,
        cx: &mut App,
    ) {
        let Some(text) = self.placeholder_for(i) else {
            return;
        };
        let line = layout::shape_line(
            &text,
            l.metrics.font_size,
            self.colors.ink_alpha(0.35),
            l.metrics.weight,
            window,
        );
        let _ = line.paint(at, l.line_height, TextAlign::Left, None, window, cx);
    }

    fn paint_gutter(&mut self, origin: Point<Pixels>, window: &mut Window) {
        let Some(hover) = self.hover else { return };
        if self.read_only
            || !self.gutter
            || self.typing
            || hover.block >= self.doc.len()
            || self.gesture.is_some()
        {
            return;
        }
        // Fade in over 120 ms.
        let t = (hover.since.elapsed().as_secs_f32() / 0.12).min(1.);
        if t < 1. {
            window.request_animation_frame();
        }
        let colors = self.colors;
        let (plus, handle) = self.gutter_rects(hover.block);
        let base = colors.ink_alpha(0.32 * t);
        let strong = colors.ink_alpha(0.5 * t);
        for (rect, part) in [(plus, GutterPart::Plus), (handle, GutterPart::Handle)] {
            let r = rect + origin;
            let active = hover.part == part;
            if active {
                let mut bg = colors.hover();
                bg.a *= t;
                window.paint_quad(fill(r, bg).corner_radii(px(4.)));
            }
            let ink = if active { strong } else { base };
            let c = r.center();
            match part {
                GutterPart::Plus => {
                    let len = px(13.);
                    let w = px(1.5);
                    window.paint_quad(
                        fill(
                            Bounds::new(point(c.x - len / 2., c.y - w / 2.), size(len, w)),
                            ink,
                        )
                        .corner_radii(w / 2.),
                    );
                    window.paint_quad(
                        fill(
                            Bounds::new(point(c.x - w / 2., c.y - len / 2.), size(w, len)),
                            ink,
                        )
                        .corner_radii(w / 2.),
                    );
                }
                GutterPart::Handle => {
                    let d = px(3.);
                    for col in [-1., 1.] {
                        for row in [-1., 0., 1.] {
                            let p = point(c.x + px(2.6 * col), c.y + px(5. * row));
                            window.paint_quad(
                                fill(Bounds::new(p - point(d / 2., d / 2.), size(d, d)), ink)
                                    .corner_radii(d / 2.),
                            );
                        }
                    }
                }
                GutterPart::None => {}
            }
        }
    }

    fn paint_drag(&mut self, bounds: Bounds<Pixels>, window: &mut Window, cx: &mut App) {
        let reduce = cx.reduce_motion();
        let gutter = self.gutter_width();
        let Some(Gesture::Handle {
            moving: true,
            target,
            pointer,
            indicator,
            span,
            ..
        }) = &mut self.gesture
        else {
            return;
        };
        let goal = gap_y(&self.geo, *target);
        // The drop line glides to its gap.
        let y = match indicator {
            Some(y) if !reduce => {
                let next = *y + (goal - *y) * 0.35;
                if (next - goal).abs() > px(0.5) {
                    window.request_animation_frame();
                    next
                } else {
                    goal
                }
            }
            _ => goal,
        };
        *indicator = Some(y);
        let left = bounds.origin.x + gutter;
        let mut color = self.colors.accent;
        color.a = 0.55;
        window.paint_quad(
            fill(
                Bounds::from_corners(
                    point(left, bounds.origin.y + y - px(2.)),
                    point(bounds.right(), bounds.origin.y + y + px(2.)),
                ),
                color,
            )
            .corner_radii(px(2.)),
        );
        // A faint copy of the first dragged block follows the pointer.
        let first = span.start;
        if let Some(l) = self.geo.layouts.get(first).cloned() {
            let text: String = self
                .doc
                .block(first)
                .text
                .lines()
                .next()
                .unwrap_or("")
                .chars()
                .take(80)
                .collect();
            let label = if text.is_empty() {
                " ".to_string()
            } else {
                text
            };
            let line = layout::shape_line(
                &label,
                l.metrics.font_size.min(18.),
                self.colors.ink_alpha(0.45),
                l.metrics.weight,
                window,
            );
            let w = line.width().min(px(420.)) + px(16.);
            let r = Bounds::new(*pointer + point(px(14.), px(6.)), size(w, px(28.)));
            window.paint_quad(fill(r, self.colors.block_selection()).corner_radii(px(4.)));
            let _ = line.paint(
                r.origin + point(px(8.), px(2.)),
                px(24.),
                TextAlign::Left,
                None,
                window,
                cx,
            );
        }
    }
}

/// The y of the gap before block `g` (or after the last), from the top.
fn gap_y(geo: &Geometry, g: usize) -> Pixels {
    let n = geo.tops.len();
    if n == 0 {
        return px(0.);
    }
    if g == 0 {
        return geo.tops[0];
    }
    if g >= n {
        return geo.tops[n - 1] + geo.layouts[n - 1].height + px(1.);
    }
    let prev_bottom = geo.tops[g - 1] + geo.layouts[g - 1].height;
    (prev_bottom + geo.tops[g]) / 2.
}

/// Pointer listeners for this frame.
fn listen(
    editor: &Entity<BlockEditor>,
    bounds: Bounds<Pixels>,
    hitbox: &Hitbox,
    window: &mut Window,
    _: &mut App,
) {
    let down = editor.clone();
    let hit = hitbox.clone();
    window.on_mouse_event(move |e: &MouseDownEvent, phase, window, cx| {
        if phase != DispatchPhase::Bubble
            || e.button != MouseButton::Left
            || !hit.is_hovered(window)
        {
            return;
        }
        down.update(cx, |ed, cx| ed.mouse_down(e, bounds, window, cx));
        cx.stop_propagation();
    });
    let moved = editor.clone();
    window.on_mouse_event(move |e: &MouseMoveEvent, phase, window, cx| {
        if phase != DispatchPhase::Bubble {
            return;
        }
        moved.update(cx, |ed, cx| ed.mouse_move(e, bounds, window, cx));
    });
    let up = editor.clone();
    window.on_mouse_event(move |e: &MouseUpEvent, phase, window, cx| {
        if phase != DispatchPhase::Bubble || e.button != MouseButton::Left {
            return;
        }
        up.update(cx, |ed, cx| {
            if ed.gesture.is_some() {
                ed.mouse_up(e, window, cx);
            }
        });
    });
}
