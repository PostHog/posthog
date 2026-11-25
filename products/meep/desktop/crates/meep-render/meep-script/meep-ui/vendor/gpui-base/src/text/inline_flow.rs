use std::{
    cell::RefCell,
    ops::Range,
    rc::Rc,
    sync::{Arc, Mutex},
};
use unicode_segmentation::UnicodeSegmentation as _;

use gpui::{
    AbsoluteLength, AnyElement, App, AvailableSpace, Bounds, DefiniteLength, Element, ElementId,
    GlobalElementId, Hsla, ImageSource, InspectorElementId, InteractiveElement as _, IntoElement,
    LayoutId, LineFragment as WrapLineFragment, ObjectFit, Pixels, Refineable as _, ShapedLine,
    SharedString, Size, StatefulInteractiveElement as _, StyleRefinement, Styled, StyledImage as _,
    TextRun, TextStyle, WhiteSpace, Window, img, point, prelude::FluentBuilder as _, px, relative,
    size,
};

use crate::text::text_view::{LinkClickHandlerFn, handle_link_click};

use super::{
    inline::{Inline, InlineHighlight, InlineState, code_insets, text_runs, text_size_ranges},
    inline_object::{InlineObject, MeasuredInlineObject},
    node::LinkMark,
    range_highlight::RevealAt,
};

const IMAGE_LEN: usize = 1;
pub(super) const INLINE_CODE_PADDING: f32 = 4.;

pub(super) struct InlineFlow {
    id: ElementId,
    items: Vec<InlineFlowItem>,
    link_click_handler: Option<Arc<LinkClickHandlerFn>>,
    /// The block editor leaf this flow renders (design D3): its fragments
    /// and atoms are reported to the editor sink as pieces.
    editor_key: Option<u64>,
}

/// Bytes an image or custom inline node occupies in an editor leaf (one
/// U+FFFC).
const EDITOR_ATOM_LEN: usize = '\u{FFFC}'.len_utf8();

pub(super) type InlineRenderer = dyn Fn(&super::InlineRenderContext, &mut Window, &mut App) -> Option<super::InlineElement>
    + Send
    + Sync;

pub(super) enum InlineFlowItem {
    Object {
        text: SharedString,
        id: usize,
        renderer: Arc<InlineRenderer>,
        accessibility_label: SharedString,
        selected: Arc<Mutex<bool>>,
        style: gpui::HighlightStyle,
        link: Option<LinkMark>,
    },
    Text {
        state: Arc<Mutex<InlineState>>,
        text: SharedString,
        links: Vec<(Range<usize>, LinkMark)>,
        highlights: Vec<(Range<usize>, InlineHighlight)>,
        /// Range highlight backgrounds, in this item's byte space. They are
        /// only painted, so unlike `highlights` they take no part in layout.
        backgrounds: Vec<(Range<usize>, Hsla)>,
        /// The start of a pending reveal, when it is in this item.
        reveal: Option<RevealAt>,
    },
    Image {
        source: ImageSource,
        link: Option<LinkMark>,
        title: String,
        width: Option<DefiniteLength>,
        height: Option<DefiniteLength>,
    },
}

pub(crate) struct InlineFlowLayoutState {
    typography: InlineFlowTypography,
    frame_state: Rc<RefCell<InlineFlowFrameState>>,
    /// The layout this element's last measurement returned, which is the
    /// one to paint. Per element, not per state: two flows under the same
    /// id (the same document shown twice) share the state's layouts but
    /// paint their own.
    current: Rc<RefCell<Option<Rc<InlineFlowLayout>>>>,
}

/// What a flow keeps from one frame to the next, as GPUI element state under
/// the flow's id.
#[derive(Default)]
struct InlineFlowFrameState {
    /// One state per text fragment, by text-fragment index. A fragment's `Inline`
    /// retains its shaped text under its state (see `RetainedLayout`), so
    /// the state has to be the same one next frame for the text to be
    /// found; a fresh state per frame shaped every fragment again and left
    /// an entry in the table that nobody would take.
    fragment_states: Vec<Arc<Mutex<InlineState>>>,
    /// What `layouts` were laid out from. A frame whose items or typography
    /// differ starts over.
    key: Option<FlowLayoutKey>,
    /// The layouts of `key`, one per wrap width the flow was measured at:
    /// taffy probes a flow at more than one width in a frame (unconstrained,
    /// then the column's). A frame that changes nothing finds every width
    /// here and wraps and shapes nothing.
    layouts: Vec<Rc<InlineFlowLayout>>,
}

/// How many wrap widths a flow keeps a layout for.
const LAYOUTS_PER_FLOW: usize = 3;

impl InlineFlowFrameState {
    fn fragment_state(&mut self, fragment_ix: usize) -> Arc<Mutex<InlineState>> {
        if self.fragment_states.len() <= fragment_ix {
            self.fragment_states
                .resize_with(fragment_ix + 1, Default::default);
        }
        self.fragment_states[fragment_ix].clone()
    }

    /// Makes `key` the current one, dropping the layouts of another key.
    fn set_key(&mut self, key: FlowLayoutKey) {
        if !self
            .key
            .as_ref()
            .is_some_and(|current| current.matches(&key))
        {
            self.layouts.clear();
        }
        self.key = Some(key);
    }

    /// The layout at `wrap_width`, if the key was laid out there already.
    fn layout_at(&self, wrap_width: Option<Pixels>) -> Option<Rc<InlineFlowLayout>> {
        self.layouts
            .iter()
            .find(|layout| layout.wrap_width == wrap_width)
            .cloned()
    }

    /// Keeps `layout`, in place of the oldest one when the flow has been
    /// measured at more widths than it keeps.
    fn push_layout(&mut self, layout: Rc<InlineFlowLayout>) {
        if self.layouts.len() >= LAYOUTS_PER_FLOW {
            self.layouts.remove(0);
        }
        self.layouts.push(layout);
    }
}

/// Everything but the wrap width that a flow's layout depends on.
struct FlowLayoutKey {
    items: Vec<MeasureItem>,
    image_sizes: Vec<Option<Size<Pixels>>>,
    typography: InlineFlowTypography,
}

impl FlowLayoutKey {
    fn matches(&self, other: &Self) -> bool {
        self.items.len() == other.items.len()
            && self
                .items
                .iter()
                .zip(&other.items)
                .all(|(item, other)| item.same_layout_input(other))
            && self.image_sizes == other.image_sizes
            && self.typography == other.typography
    }
}

/// Resolved before `request_measured_layout`, while the parent's text-style
/// and rem stacks are still active.
#[derive(Clone, PartialEq)]
struct InlineFlowTypography {
    text_style: TextStyle,
    rem_size: Pixels,
    line_height: Pixels,
}

#[derive(Default)]
struct InlineFlowLayout {
    fragments: Vec<PositionedFragment>,
    empty_lines: Vec<(usize, Bounds<Pixels>)>,
    size: Size<Pixels>,
    wrap_width: Option<Pixels>,
}

enum PositionedFragment {
    Object {
        item_ix: usize,
        origin: gpui::Point<Pixels>,
        object: Box<MeasuredInlineObject>,
        selection_bounds: Bounds<Pixels>,
    },
    Text {
        item_ix: usize,
        origin: gpui::Point<Pixels>,
        size: Size<Pixels>,
        source_range: Range<usize>,
        font_size: Pixels,
        text: SharedString,
        links: Vec<(Range<usize>, LinkMark)>,
        highlights: Vec<(Range<usize>, InlineHighlight)>,
        selection_bounds: Bounds<Pixels>,
        /// The rounded box behind a code span, relative to the flow.
        code_background: Option<CodeBox>,
    },
    Image {
        item_ix: usize,
        origin: gpui::Point<Pixels>,
        size: Size<Pixels>,
    },
}

enum MeasureItem {
    Object {
        text: SharedString,
        id: usize,
        renderer: Arc<InlineRenderer>,
        style: gpui::HighlightStyle,
    },
    Text {
        text: SharedString,
        links: Vec<(Range<usize>, LinkMark)>,
        highlights: Vec<(Range<usize>, InlineHighlight)>,
    },
    Image {
        source: ImageSource,
        width: Option<DefiniteLength>,
        height: Option<DefiniteLength>,
    },
}

struct LineFragmentLayout {
    item_ix: usize,
    kind: LineFragmentKind,
    size: Size<Pixels>,
    source_range: Range<usize>,
    baseline: Pixels,
}

enum LineFragmentKind {
    Object(Box<MeasuredInlineObject>),
    Text {
        font_size: Pixels,
        text: SharedString,
        links: Vec<(Range<usize>, LinkMark)>,
        highlights: Vec<(Range<usize>, InlineHighlight)>,
        /// The code span's box, relative to the fragment.
        code_background: Option<CodeBox>,
    },
    Image,
}

/// The rounded box behind an inline code span, with its optional ring.
#[derive(Clone, Debug)]
struct CodeBox {
    bounds: Bounds<Pixels>,
    style: Arc<StyleRefinement>,
}

impl CodeBox {
    fn offset(self, by: gpui::Point<Pixels>) -> Self {
        Self {
            bounds: Bounds::new(by + self.bounds.origin, self.bounds.size),
            ..self
        }
    }
}

/// Atom decorations are overlays so they remain visible over opaque content.
pub(super) struct FlowPaintItem {
    element: AnyElement,
    background: Option<CodeBox>,
    overlays: Vec<(Bounds<Pixels>, Hsla)>,
}

impl InlineFlow {
    pub(super) fn new(
        id: impl Into<ElementId>,
        items: Vec<InlineFlowItem>,
        link_click_handler: Option<Arc<LinkClickHandlerFn>>,
    ) -> Self {
        Self {
            id: id.into(),
            items,
            link_click_handler,
            editor_key: None,
        }
    }

    pub(super) fn editor_key(mut self, key: Option<u64>) -> Self {
        if let Some(key) = key {
            self.id = ("editor-leaf", key).into();
        }
        self.editor_key = key;
        self
    }

    fn image_element(
        ix: usize,
        source: &ImageSource,
        link: &Option<LinkMark>,
        _title: &str,
        size: Size<Pixels>,
        link_click_handler: Option<Arc<LinkClickHandlerFn>>,
    ) -> AnyElement {
        img(source.clone())
            .id(ix)
            .object_fit(ObjectFit::Contain)
            .max_w(relative(1.))
            .w(size.width)
            .h(size.height)
            .when_some(link.clone(), |this, link| {
                let aux_link = link.clone();
                let aux_link_click_handler = link_click_handler.clone();
                this.cursor_pointer()
                    .on_click(move |event, window, cx| {
                        crate::TextSelection::end(window, cx);
                        cx.stop_propagation();
                        handle_link_click(
                            &link_click_handler,
                            link.url.clone(),
                            event.clone(),
                            window,
                            cx,
                        );
                    })
                    .on_aux_click(move |event, window, cx| {
                        crate::TextSelection::end(window, cx);
                        cx.stop_propagation();
                        handle_link_click(
                            &aux_link_click_handler,
                            aux_link.url.clone(),
                            event.clone(),
                            window,
                            cx,
                        );
                    })
            })
            .into_any_element()
    }
}

impl IntoElement for InlineFlow {
    type Element = Self;

    fn into_element(self) -> Self::Element {
        self
    }
}

impl Element for InlineFlow {
    type RequestLayoutState = InlineFlowLayoutState;
    type PrepaintState = Vec<FlowPaintItem>;

    fn id(&self) -> Option<ElementId> {
        Some(self.id.clone())
    }

    fn source_location(&self) -> Option<&'static core::panic::Location<'static>> {
        None
    }

    fn request_layout(
        &mut self,
        id: Option<&GlobalElementId>,
        _inspector_id: Option<&InspectorElementId>,
        window: &mut Window,
        cx: &mut App,
    ) -> (LayoutId, Self::RequestLayoutState) {
        let frame_state = window.with_optional_element_state(id, |state, _| {
            let state: Rc<RefCell<InlineFlowFrameState>> = state.flatten().unwrap_or_default();
            (state.clone(), Some(state))
        });
        let measure_items = self.items.iter().map(MeasureItem::from).collect::<Vec<_>>();
        // A measured-layout callback runs after the parent's text-style stack
        // is gone. Capture every resolved typography input while this element
        // is still requested under its Markdown block (notably headings).
        let typography = InlineFlowTypography {
            text_style: window.text_style(),
            rem_size: window.rem_size(),
            line_height: window.line_height(),
        };
        let image_sizes = measure_items
            .iter()
            .enumerate()
            .map(|(ix, item)| match item {
                MeasureItem::Image {
                    source,
                    width,
                    height,
                } => Some(measure_image_size(
                    ix,
                    source,
                    *width,
                    *height,
                    typography.line_height,
                    typography.rem_size,
                    window,
                    cx,
                )),
                MeasureItem::Text { .. } | MeasureItem::Object { .. } => None,
            })
            .collect::<Vec<_>>();
        let objects = prepare_objects(&measure_items, &typography.text_style, window, cx);
        frame_state.borrow_mut().set_key(FlowLayoutKey {
            items: measure_items,
            image_sizes,
            typography: typography.clone(),
        });
        let layout_state = InlineFlowLayoutState {
            typography: typography.clone(),
            frame_state: frame_state.clone(),
            current: Rc::default(),
        };
        let current = layout_state.current.clone();

        let layout_id = window.request_measured_layout(Default::default(), {
            move |known_dimensions, available_space, window, cx| {
                let wrap_width = if typography.text_style.white_space == WhiteSpace::Normal {
                    known_dimensions.width.or(match available_space.width {
                        AvailableSpace::Definite(width) => Some(width),
                        _ => None,
                    })
                } else {
                    None
                };
                let mut state = frame_state.borrow_mut();
                if let Some(layout) = state.layout_at(wrap_width) {
                    let size = layout.size;
                    *current.borrow_mut() = Some(layout);
                    return size;
                }
                let state = &mut *state;
                let key = state.key.as_ref().expect("set by request_layout");
                let layout = window.with_rem_size(Some(typography.rem_size), |window| {
                    window.with_text_style(
                        Some(typography.text_style.subtract(&Default::default())),
                        |window| {
                            layout_measured_flow(
                                &key.items,
                                &key.image_sizes,
                                &objects,
                                &typography.text_style,
                                wrap_width,
                                window,
                                cx,
                            )
                        },
                    )
                });
                let size = layout.size;
                let layout = Rc::new(layout);
                *current.borrow_mut() = Some(layout.clone());
                state.push_layout(layout);
                size
            }
        });

        (layout_id, layout_state)
    }

    fn prepaint(
        &mut self,
        _id: Option<&GlobalElementId>,
        _inspector_id: Option<&InspectorElementId>,
        bounds: Bounds<Pixels>,
        request_layout: &mut Self::RequestLayoutState,
        window: &mut Window,
        cx: &mut App,
    ) -> Self::PrepaintState {
        let frame_state = request_layout.frame_state.clone();
        let Some(layout) = request_layout.current.borrow().clone() else {
            return Vec::new();
        };
        let typography = request_layout.typography.clone();
        let text_style = &typography.text_style;
        let mut elements = Vec::with_capacity(layout.fragments.len());

        // A reveal goes to the fragment it starts in. A line break lays out
        // no fragment, so a reveal starting on one, or on an empty line, goes
        // to the next fragment of its text, or to the last when none follows.
        let reveal_fragment = layout
            .fragments
            .iter()
            .enumerate()
            .filter_map(|(ix, fragment)| {
                let PositionedFragment::Text {
                    item_ix,
                    source_range,
                    ..
                } = fragment
                else {
                    return None;
                };
                let InlineFlowItem::Text {
                    reveal: Some(reveal),
                    ..
                } = &self.items[*item_ix]
                else {
                    return None;
                };
                Some((ix, source_range.end > reveal.offset()))
            })
            .reduce(|found, next| if found.1 { found } else { next })
            .map(|(ix, _)| ix);

        // Editor leaf byte offset where each item starts: text items count
        // their bytes, images and custom nodes one U+FFFC.
        let editor = self.editor_key.zip(super::editor_seam::current());
        // Ordinary TextViews do not allocate editor bookkeeping.
        let item_starts: Vec<usize> = if let Some((key, sink)) = &editor {
            sink.begin_pieces(*key);
            let mut at = 0;
            self.items
                .iter()
                .map(|item| {
                    let start = at;
                    at += match item {
                        InlineFlowItem::Text { text, .. } => text.len(),
                        _ => EDITOR_ATOM_LEN,
                    };
                    start
                })
                .collect()
        } else {
            Vec::new()
        };
        if let Some((key, sink)) = &editor {
            for (start, line_bounds) in &layout.empty_lines {
                // Flow layout uses a one-byte object placeholder; the public
                // leaf coordinate space uses the three-byte U+FFFC instead.
                let mut flow_start = 0;
                let mut leaf_start = 0;
                for item in &self.items {
                    let len = match item {
                        InlineFlowItem::Text { text, .. } => text.len(),
                        _ => IMAGE_LEN,
                    };
                    if flow_start + len > *start {
                        break;
                    }
                    flow_start += len;
                    leaf_start += match item {
                        InlineFlowItem::Text { text, .. } => text.len(),
                        _ => EDITOR_ATOM_LEN,
                    };
                }
                sink.report_empty_piece(
                    *key,
                    leaf_start + start - flow_start,
                    Bounds::new(bounds.origin + line_bounds.origin, line_bounds.size),
                );
            }
        }
        let decorations = editor.as_ref().map(|(key, sink)| sink.backgrounds(*key));
        let report_box = |item_ix: usize, bounds: Bounds<Pixels>| {
            let mut overlays = Vec::new();
            if let Some((key, sink)) = &editor {
                let start = item_starts[item_ix];
                let end = start + EDITOR_ATOM_LEN;
                sink.report_box_piece(*key, start..end, bounds);
                for (range, color) in decorations.as_deref().unwrap_or_default() {
                    if range.start < range.end && range.start < end && range.end > start {
                        overlays.push((bounds, *color));
                    }
                }
            }
            overlays
        };

        let mut text_fragment_count = 0;
        for (fragment_ix, fragment) in layout.fragments.iter().enumerate() {
            match fragment {
                PositionedFragment::Object {
                    item_ix,
                    origin,
                    object,
                    selection_bounds,
                } => {
                    let InlineFlowItem::Object {
                        text,
                        id,
                        accessibility_label,
                        selected,
                        link,
                        ..
                    } = &self.items[*item_ix]
                    else {
                        continue;
                    };
                    let object_size = object.metrics.size;
                    let overlays =
                        report_box(*item_ix, Bounds::new(bounds.origin + *origin, object_size));
                    let mut element = InlineObject::new(
                        ("inline-object", *id),
                        text.clone(),
                        accessibility_label.clone(),
                        (**object).clone(),
                        selected.clone(),
                        Bounds::new(
                            bounds.origin + selection_bounds.origin,
                            selection_bounds.size,
                        ),
                        Bounds::new(
                            point(bounds.left(), bounds.top() + selection_bounds.top()),
                            size(bounds.size.width, selection_bounds.size.height),
                        ),
                    )
                    .link(link.clone(), self.link_click_handler.clone())
                    .into_any_element();
                    element.prepaint_as_root(
                        bounds.origin + *origin,
                        size(
                            AvailableSpace::Definite(object_size.width),
                            AvailableSpace::Definite(object_size.height),
                        ),
                        window,
                        cx,
                    );
                    elements.push(FlowPaintItem {
                        element,
                        background: None,
                        overlays,
                    });
                }
                PositionedFragment::Text {
                    item_ix,
                    origin,
                    size: fragment_size,
                    source_range,
                    font_size,
                    text,
                    links,
                    highlights,
                    selection_bounds,
                    code_background,
                } => {
                    let InlineFlowItem::Text {
                        state: source_state,
                        backgrounds,
                        reveal,
                        ..
                    } = &self.items[*item_ix]
                    else {
                        continue;
                    };
                    let (origin, fragment_size, font_size) = (*origin, *fragment_size, *font_size);
                    let state = frame_state.borrow_mut().fragment_state(text_fragment_count);
                    text_fragment_count += 1;
                    if let Ok(mut state) = state.lock() {
                        state.set_text(text.clone());
                    }

                    let insets = code_insets(highlights, font_size, window.rem_size());
                    let background = code_background
                        .as_ref()
                        .map(|code| code.clone().offset(bounds.origin));
                    // The fragment's typography: the flow's style at the
                    // fragment's size, on one line. Fragments are already
                    // wrapped, so this leaf must not wrap independently.
                    let mut fragment_style = text_style.clone();
                    fragment_style.font_size = font_size.into();
                    fragment_style.line_height =
                        (fragment_size.height - insets.top - insets.bottom).into();
                    fragment_style.white_space = WhiteSpace::Nowrap;
                    let element = Inline::new(
                        state,
                        links.clone(),
                        highlights.clone(),
                        self.link_click_handler.clone(),
                    )
                    .selection_source(source_state.clone(), source_range.clone())
                    .range_backgrounds(slice_ranges(
                        backgrounds,
                        source_range.start,
                        source_range.end,
                        |range, color| (range, *color),
                    ))
                    .reveal(
                        reveal
                            .as_ref()
                            .filter(|_| reveal_fragment == Some(fragment_ix))
                            .map(|reveal| reveal.clamp(source_range.start, source_range.end)),
                    )
                    .text_style(fragment_style.clone());
                    let element = element.editor_piece(
                        editor
                            .as_ref()
                            .map(|(key, _)| (*key, item_starts[*item_ix] + source_range.start)),
                    );
                    let mut element = element
                        .selection_bounds(Bounds::new(
                            point(bounds.left(), bounds.top() + selection_bounds.top()),
                            size(bounds.size.width, selection_bounds.size.height),
                        ))
                        .selection_padding(insets.left, insets.right)
                        .paint_origin(bounds.origin + origin + point(insets.left, insets.top))
                        .into_any_element();
                    // The `Inline` is its own layout root, with no box around
                    // it: its text measures with the window's text style, so
                    // the fragment's style is pushed for the layout.
                    window.with_rem_size(Some(typography.rem_size), |window| {
                        window.with_text_style(
                            Some(fragment_style.subtract(&Default::default())),
                            |window| {
                                element.prepaint_as_root(
                                    bounds.origin + origin + point(insets.left, insets.top),
                                    size(
                                        AvailableSpace::Definite(
                                            fragment_size.width - insets.left - insets.right,
                                        ),
                                        AvailableSpace::Definite(
                                            fragment_size.height - insets.top - insets.bottom,
                                        ),
                                    ),
                                    window,
                                    cx,
                                );
                            },
                        );
                    });
                    elements.push(FlowPaintItem {
                        element,
                        background,
                        overlays: Vec::new(),
                    });
                }
                PositionedFragment::Image {
                    item_ix,
                    origin,
                    size: fragment_size,
                } => {
                    let InlineFlowItem::Image {
                        source,
                        link,
                        title,
                        ..
                    } = &self.items[*item_ix]
                    else {
                        continue;
                    };
                    let (origin, fragment_size) = (*origin, *fragment_size);
                    let overlays =
                        report_box(*item_ix, Bounds::new(bounds.origin + origin, fragment_size));
                    let mut element = Self::image_element(
                        elements.len(),
                        source,
                        link,
                        title.as_str(),
                        fragment_size,
                        self.link_click_handler.clone(),
                    );
                    element.prepaint_as_root(
                        bounds.origin + origin,
                        size(
                            AvailableSpace::Definite(fragment_size.width),
                            AvailableSpace::Definite(fragment_size.height),
                        ),
                        window,
                        cx,
                    );
                    elements.push(FlowPaintItem {
                        element,
                        background: None,
                        overlays,
                    });
                }
            }
        }

        frame_state
            .borrow_mut()
            .fragment_states
            .truncate(text_fragment_count);

        elements
    }

    fn paint(
        &mut self,
        _id: Option<&GlobalElementId>,
        _inspector_id: Option<&InspectorElementId>,
        _bounds: Bounds<Pixels>,
        _request_layout: &mut Self::RequestLayoutState,
        prepaint: &mut Self::PrepaintState,
        window: &mut Window,
        cx: &mut App,
    ) {
        let preserve_selection = crate::GlobalState::global(cx)
            .text_view_state()
            .is_some_and(|view| view.read(cx).preserve_inline_selection);
        for item in &self.items {
            if !preserve_selection
                && let InlineFlowItem::Text { state, .. } = item
                && let Ok(mut state) = state.lock()
            {
                state.selection = None;
            }
        }
        let radius = crate::Theme::global(cx).tokens.radius.sm;
        for FlowPaintItem {
            element,
            background,
            overlays,
        } in prepaint
        {
            if let Some(code) = background {
                let mut style = gpui::Style::default();
                style.corner_radii = gpui::Corners {
                    top_left: radius.into(),
                    top_right: radius.into(),
                    bottom_left: radius.into(),
                    bottom_right: radius.into(),
                };
                style.refine(&code.style);
                style.paint(code.bounds, window, cx, |_, _| {});
            }
            element.paint(window, cx);
            for (bounds, color) in overlays {
                window.paint_quad(gpui::fill(*bounds, *color));
            }
        }
    }
}

impl From<&InlineFlowItem> for MeasureItem {
    fn from(item: &InlineFlowItem) -> Self {
        match item {
            InlineFlowItem::Object {
                text,
                id,
                renderer,
                style,
                ..
            } => Self::Object {
                text: text.clone(),
                id: *id,
                renderer: renderer.clone(),
                style: *style,
            },
            InlineFlowItem::Text {
                state: _,
                text,
                links,
                highlights,
                ..
            } => MeasureItem::Text {
                text: text.clone(),
                links: links.clone(),
                highlights: highlights.clone(),
            },
            InlineFlowItem::Image {
                source,
                width,
                height,
                ..
            } => MeasureItem::Image {
                source: source.clone(),
                width: *width,
                height: *height,
            },
        }
    }
}

impl MeasureItem {
    fn len(&self) -> usize {
        match self {
            MeasureItem::Text { text, .. } => text.len(),
            MeasureItem::Image { .. } | MeasureItem::Object { .. } => IMAGE_LEN,
        }
    }

    /// Whether `other` lays out the same as this item. An object is
    /// rendered anew every frame, so a flow with one is never reused.
    fn same_layout_input(&self, other: &Self) -> bool {
        match (self, other) {
            (
                MeasureItem::Text {
                    text,
                    links,
                    highlights,
                },
                MeasureItem::Text {
                    text: other_text,
                    links: other_links,
                    highlights: other_highlights,
                },
            ) => text == other_text && links == other_links && highlights == other_highlights,
            (
                MeasureItem::Image { width, height, .. },
                MeasureItem::Image {
                    width: other_width,
                    height: other_height,
                    ..
                },
            ) => width == other_width && height == other_height,
            _ => false,
        }
    }
}

/// Intrinsic width for table sizing, using the same objects and wrapping inputs as painting.
pub(super) fn intrinsic_width(
    items: &[InlineFlowItem],
    window: &mut Window,
    cx: &mut App,
) -> Pixels {
    let items = items.iter().map(MeasureItem::from).collect::<Vec<_>>();
    let line_height = window.line_height();
    let rem_size = window.rem_size();
    let images = items
        .iter()
        .enumerate()
        .map(|(ix, item)| match item {
            MeasureItem::Image {
                source,
                width,
                height,
            } => Some(measure_image_size(
                ix,
                source,
                *width,
                *height,
                line_height,
                rem_size,
                window,
                cx,
            )),
            _ => None,
        })
        .collect::<Vec<_>>();
    layout_flow(&items, &images, &window.text_style(), None, window, cx)
        .size
        .width
}

fn prepare_objects(
    items: &[MeasureItem],
    text_style: &TextStyle,
    window: &mut Window,
    cx: &mut App,
) -> Vec<Option<MeasuredInlineObject>> {
    items
        .iter()
        .map(|item| match item {
            MeasureItem::Object {
                text,
                id,
                renderer,
                style,
            } => {
                let style = text_style.clone().highlight(*style);
                let context = super::InlineRenderContext::new(
                    style.clone(),
                    style.font_size.to_pixels(window.rem_size()),
                    style.line_height_in_pixels(window.rem_size()),
                    window.rem_size(),
                );
                // Must be the id `InlineObject` paints under: GPUI asserts a
                // stateful child (a plugin's HoverCard) sees the same id path
                // in request_layout as in prepaint, and the element is laid
                // out here but painted inside `InlineObject`.
                Some(window.with_id(("inline-object", *id), |window| {
                    let element = window
                        .with_text_style(Some(style.subtract(&Default::default())), |window| {
                            renderer(&context, window, cx)
                        });
                    MeasuredInlineObject::measure(text, element, &style, window, cx)
                }))
            }
            _ => None,
        })
        .collect()
}

fn layout_flow(
    items: &[MeasureItem],
    image_sizes: &[Option<Size<Pixels>>],
    text_style: &TextStyle,
    wrap_width: Option<Pixels>,
    window: &mut Window,
    cx: &mut App,
) -> InlineFlowLayout {
    let objects = prepare_objects(items, text_style, window, cx);
    layout_measured_flow(
        items,
        image_sizes,
        &objects,
        text_style,
        wrap_width,
        window,
        cx,
    )
}

#[cfg(test)]
thread_local! {
    /// How many flows were laid out (wrapped and shaped) on this thread.
    pub(super) static FLOW_LAYOUTS: std::cell::Cell<usize> = const { std::cell::Cell::new(0) };
}

fn layout_measured_flow(
    items: &[MeasureItem],
    image_sizes: &[Option<Size<Pixels>>],
    prepared_objects: &[Option<MeasuredInlineObject>],
    text_style: &TextStyle,
    wrap_width: Option<Pixels>,
    window: &mut Window,
    _cx: &mut App,
) -> InlineFlowLayout {
    #[cfg(test)]
    FLOW_LAYOUTS.with(|layouts| layouts.set(layouts.get() + 1));
    let rem_size = window.rem_size();
    let line_height = plain_line_height(text_style, rem_size, window);
    let total_len = items.iter().map(MeasureItem::len).sum::<usize>();
    if total_len == 0 {
        return InlineFlowLayout::default();
    }

    let objects = prepared_objects
        .iter()
        .map(|object| object.clone().map(|object| object.fit_text(wrap_width)))
        .collect::<Vec<_>>();
    let line_ranges = line_ranges(items, image_sizes, &objects, text_style, wrap_width, window);
    let font_size = text_style.font_size.to_pixels(rem_size);
    let mut fragments = Vec::new();
    let mut empty_lines = Vec::new();
    let mut max_width = Pixels::ZERO;
    let mut y = Pixels::ZERO;

    for line_range in line_ranges {
        let mut line_fragments = Vec::new();
        let mut line_width = Pixels::ZERO;
        // `LineLayout` is the metric source used by the text paint path. Its
        // descent is normalized positive by native backends, whereas
        // `FontMetrics::descent` remains signed. Start with the same shaped
        // body metrics used below for every text fragment rather than mixing
        // those two conventions through `TextSystem::baseline_offset`.
        let body_runs = text_runs(1, text_style, &[]);
        let body_line = shape_line(" ".into(), font_size, &body_runs, window);
        let body_baseline = centered_baseline(&body_line, line_height);
        // Like a plain text line, the body line box is the line height even
        // when the font's glyphs are taller; runs may overflow it as far as
        // body glyphs do.
        let body_overflow_above = (body_line.ascent - body_baseline).max(Pixels::ZERO);
        let body_overflow_below =
            (body_line.descent - (line_height - body_baseline)).max(Pixels::ZERO);
        let mut line_ascent = body_baseline;
        let mut line_descent = line_height - body_baseline;
        let mut item_start = 0;

        for (item_ix, item) in items.iter().enumerate() {
            let item_end = item_start + item.len();
            if item_end <= line_range.start {
                item_start = item_end;
                continue;
            }
            if item_start >= line_range.end {
                break;
            }

            match item {
                MeasureItem::Text {
                    text,
                    links,
                    highlights,
                } => {
                    let local_start = line_range.start.max(item_start) - item_start;
                    let local_end = line_range.end.min(item_end) - item_start;
                    for (segment, scale) in
                        text_size_ranges(text.len(), highlights, font_size, window.rem_size())
                    {
                        let start = local_start.max(segment.start);
                        let end = local_end.min(segment.end);
                        if start >= end {
                            continue;
                        }
                        let subtext = SharedString::from(text[start..end].to_string());
                        let mut highlights =
                            slice_ranges(highlights, start, end, |range, style| {
                                (range, style.clone())
                            });
                        let links =
                            slice_ranges(links, start, end, |range, link| (range, link.clone()));
                        let runs = text_runs(subtext.len(), text_style, &highlights);
                        let segment_font_size = font_size * scale;
                        let shaped_line =
                            shape_line(subtext.clone(), segment_font_size, &runs, window);
                        let is_code = highlights.iter().any(|(_, h)| h.font_size_scale.is_some());
                        let insets = code_insets(&highlights, segment_font_size, window.rem_size());
                        let width = shaped_line.width() + insets.left + insets.right;
                        // Measure the run by its glyph box. The body strut already
                        // carries the line's leading, so a run only has to fit its
                        // glyphs: leading of its own would make a smaller or
                        // differently proportioned run, such as inline code, push
                        // its line taller than a plain one. Positioning grows the
                        // box back to the line. The compact code background is
                        // painted independently.
                        let glyph_size = size(
                            width,
                            shaped_line.ascent + shaped_line.descent + insets.top + insets.bottom,
                        );
                        let baseline = shaped_line.ascent + insets.top;
                        let code_background = is_code
                            .then(|| {
                                code_background(
                                    &shaped_line,
                                    &runs,
                                    segment_font_size,
                                    &mut highlights,
                                    glyph_size,
                                    baseline,
                                    window,
                                )
                            })
                            .flatten();
                        line_ascent = line_ascent.max(baseline - body_overflow_above);
                        line_descent =
                            line_descent.max(glyph_size.height - baseline - body_overflow_below);
                        line_width += width;
                        line_fragments.push(LineFragmentLayout {
                            item_ix,
                            kind: LineFragmentKind::Text {
                                font_size: segment_font_size,
                                text: subtext,
                                links,
                                highlights,
                                code_background,
                            },
                            size: glyph_size,
                            source_range: start..end,
                            baseline: baseline,
                        });
                    }
                }
                MeasureItem::Object { .. } => {
                    let object = objects[item_ix].as_ref().unwrap().clone();
                    let metrics = object.metrics;
                    line_ascent = line_ascent.max(metrics.baseline);
                    line_descent = line_descent.max(metrics.size.height - metrics.baseline);
                    line_width += metrics.size.width;
                    line_fragments.push(LineFragmentLayout {
                        item_ix,
                        kind: LineFragmentKind::Object(Box::new(object)),
                        size: metrics.size,
                        source_range: 0..IMAGE_LEN,
                        baseline: metrics.baseline,
                    });
                }
                MeasureItem::Image { .. } => {
                    if line_range.start <= item_start && item_end <= line_range.end {
                        let size = image_sizes[item_ix]
                            .expect("image size should be measured before layout");
                        line_width += size.width;
                        let baseline = (size.height / 2. + body_baseline - line_height / 2.)
                            .max(Pixels::ZERO)
                            .min(size.height);
                        line_ascent = line_ascent.max(baseline);
                        line_descent = line_descent.max(size.height - baseline);
                        line_fragments.push(LineFragmentLayout {
                            item_ix,
                            kind: LineFragmentKind::Image,
                            size,
                            source_range: 0..IMAGE_LEN,
                            baseline: baseline,
                        });
                    }
                }
            }

            item_start = item_end;
        }

        if line_range.is_empty() {
            empty_lines.push((
                line_range.start,
                Bounds::new(
                    point(Pixels::ZERO, y),
                    size(Pixels::ZERO, line_ascent + line_descent),
                ),
            ));
        }
        let mut x = Pixels::ZERO;
        for mut fragment in line_fragments {
            // Give a text run's glyph box equal leading on both sides, as
            // much as the line allows: its glyphs are painted centered in the
            // box, so this keeps them on the line's baseline, and a body run
            // gets exactly the line box. The leading is negative where the
            // glyphs overflow the line, as a plain text line's do.
            let leading = match fragment.kind {
                LineFragmentKind::Text { .. } => (line_ascent - fragment.baseline)
                    .min(line_descent - (fragment.size.height - fragment.baseline))
                    .max(-fragment.size.height / 2.),
                _ => Pixels::ZERO,
            };
            fragment.size.height += leading * 2.;
            fragment.baseline += leading;
            let origin = point(x, y + line_ascent - fragment.baseline);
            let selection_bounds = Bounds::new(
                point(x, y),
                size(fragment.size.width, line_ascent + line_descent),
            );
            let positioned = match fragment.kind {
                LineFragmentKind::Object(object) => PositionedFragment::Object {
                    item_ix: fragment.item_ix,
                    origin,
                    object,
                    selection_bounds,
                },
                LineFragmentKind::Text {
                    font_size,
                    text,
                    links,
                    highlights,
                    code_background,
                } => PositionedFragment::Text {
                    item_ix: fragment.item_ix,
                    origin,
                    size: fragment.size,
                    source_range: fragment.source_range,
                    selection_bounds,
                    font_size,
                    text,
                    links,
                    highlights,
                    code_background: code_background
                        .map(|code| code.offset(origin + point(Pixels::ZERO, leading))),
                },
                LineFragmentKind::Image => PositionedFragment::Image {
                    item_ix: fragment.item_ix,
                    origin,
                    size: fragment.size,
                },
            };
            x += fragment.size.width;
            fragments.push(positioned);
        }

        max_width = max_width.max(line_width);
        y += line_ascent + line_descent;
    }

    InlineFlowLayout {
        fragments,
        empty_lines,
        size: size(max_width, y),
        wrap_width,
    }
}

/// The rounded box behind a code span, relative to the fragment: centered on
/// the capital-height body of the text, with the descender room shared
/// between both sides instead of added only below. Takes the background
/// color out of `highlights`, so the text does not paint it a second time
/// at the full line height.
fn code_background(
    shaped_line: &ShapedLine,
    runs: &[TextRun],
    font_size: Pixels,
    highlights: &mut [(Range<usize>, InlineHighlight)],
    fragment_size: Size<Pixels>,
    baseline: Pixels,
    window: &Window,
) -> Option<CodeBox> {
    let cap_height = runs
        .iter()
        .map(|run| {
            let font = window.text_system().resolve_font(&run.font);
            window.text_system().cap_height(font, font_size)
        })
        .fold(Pixels::ZERO, Pixels::max);
    let vertical_padding = font_size * 0.125 + shaped_line.descent / 2.;
    let color = highlights
        .iter()
        .find_map(|(_, h)| h.style.background_color);
    let mut style = highlights
        .iter()
        .find_map(|(_, h)| h.code_style.clone())
        .unwrap_or_default();
    if style.background.is_none() {
        style.background = color.map(Into::into);
    }
    for (_, highlight) in highlights.iter_mut() {
        highlight.style.background_color = None;
    }
    let insets = code_insets(highlights, font_size, window.rem_size());
    let top = if style.padding.top.is_some() {
        shaped_line.ascent - cap_height + insets.top
    } else {
        vertical_padding
            + style
                .border_widths
                .top
                .map(|width| width.to_pixels(window.rem_size()))
                .unwrap_or_default()
    };
    let bottom = if style.padding.bottom.is_some() {
        shaped_line.descent + insets.bottom
    } else {
        vertical_padding
            + style
                .border_widths
                .bottom
                .map(|width| width.to_pixels(window.rem_size()))
                .unwrap_or_default()
    };
    Some(CodeBox {
        bounds: Bounds::new(
            point(Pixels::ZERO, baseline - cap_height - top),
            size(fragment_size.width, cap_height + top + bottom),
        ),
        style: Arc::new(style),
    })
}

fn line_ranges(
    items: &[MeasureItem],
    image_sizes: &[Option<Size<Pixels>>],
    objects: &[Option<MeasuredInlineObject>],
    text_style: &TextStyle,
    wrap_width: Option<Pixels>,
    window: &mut Window,
) -> Vec<Range<usize>> {
    let total_len = items.iter().map(MeasureItem::len).sum::<usize>();
    let mut hard_lines = Vec::new();
    let mut line_start = 0;
    let mut item_start = 0;

    for item in items {
        if let MeasureItem::Text { text, .. } = item {
            for (newline, _) in text.match_indices('\n') {
                let newline = item_start + newline;
                hard_lines.push(line_start..newline);
                line_start = newline + 1;
            }
        }
        item_start += item.len();
    }
    hard_lines.push(line_start..total_len);

    let Some(wrap_width) = wrap_width else {
        return hard_lines;
    };
    let rem_size = window.rem_size();
    let font_size = text_style.font_size.to_pixels(rem_size);
    let mut wrapper = window
        .text_system()
        .line_wrapper(text_style.font(), font_size);
    let mut ranges = Vec::new();

    for hard_line in hard_lines {
        if hard_line.is_empty() {
            ranges.push(hard_line);
            continue;
        }
        let mut item_start = 0;
        let mut wrap_fragments = Vec::new();
        for (ix, item) in items.iter().enumerate() {
            let item_end = item_start + item.len();
            if item_end > hard_line.start && item_start < hard_line.end {
                match item {
                    MeasureItem::Text {
                        text, highlights, ..
                    } => {
                        let start = hard_line.start.max(item_start) - item_start;
                        let end = hard_line.end.min(item_end) - item_start;
                        if start < end {
                            push_text_wrap_fragments(
                                &mut wrap_fragments,
                                text,
                                highlights,
                                start..end,
                                text_style,
                                wrap_width,
                                window,
                            );
                        }
                    }
                    MeasureItem::Object { .. } => {
                        wrap_fragments.push(WrapLineFragment::element(
                            objects[ix].as_ref().unwrap().metrics.size.width,
                            IMAGE_LEN,
                        ));
                    }
                    MeasureItem::Image { .. } => {
                        if hard_line.start <= item_start && item_end <= hard_line.end {
                            wrap_fragments.push(WrapLineFragment::element(
                                image_sizes[ix]
                                    .expect("image size should be measured before wrapping")
                                    .width,
                                IMAGE_LEN,
                            ));
                        }
                    }
                }
            }
            item_start = item_end;
        }

        // The wrapper sums per-character widths, which can be narrower than the
        // shaped run (CoreText sets an isolated full-width `，` at half width).
        // Check each line against the shaped spans and re-wrap it tighter when
        // it overflows, so the painted line never exceeds `wrap_width`.
        let spans = shaped_spans(items, image_sizes, objects, text_style, &hard_line, window);
        let mut start = hard_line.start;
        while start < hard_line.end {
            let rest = fragments_from(&wrap_fragments, start - hard_line.start);
            let mut budget = wrap_width;
            let mut end = next_wrap(&mut wrapper, &rest, budget, start, hard_line.end);
            let mut overflow = spans_width(&spans, start..end) - wrap_width;
            // Shrink the wrapper's budget by the overflow until it breaks earlier,
            // doubling the step while the break stays put. A single glyph wider
            // than the line keeps its line and overflows as before.
            let mut step = overflow;
            while overflow > Pixels::ZERO {
                budget -= step.max(px(0.5));
                if budget <= Pixels::ZERO {
                    break;
                }
                let tighter = next_wrap(&mut wrapper, &rest, budget, start, hard_line.end);
                if tighter < end {
                    end = tighter;
                    overflow = spans_width(&spans, start..end) - wrap_width;
                    step = overflow;
                } else {
                    step = step * 2.;
                }
            }
            // The wrapper can also break a rest that fits: kerning makes a
            // shaped run narrower than its summed characters. A table column
            // sized to its measured text would drop its last character.
            if end < hard_line.end && spans_width(&spans, start..hard_line.end) <= wrap_width {
                end = hard_line.end;
            }
            ranges.push(start..end);
            start = end;
        }

        if hard_line.is_empty() {
            ranges.push(hard_line.clone());
        }
    }

    ranges
}

/// Where the first line of `fragments` (which start at byte `start`) wraps at
/// `wrap_width`; `end` when it all fits.
fn next_wrap(
    wrapper: &mut gpui::LineWrapperHandle,
    fragments: &[WrapLineFragment],
    wrap_width: Pixels,
    start: usize,
    end: usize,
) -> usize {
    wrapper
        .wrap_line(fragments, wrap_width, gpui::IndentAdjustment::SameIndent)
        .next()
        .map_or(end, |boundary| (start + boundary.ix).min(end))
}

/// `fragments` with their first `skip` bytes dropped. Wrap boundaries fall on
/// character or element starts, so a text fragment is split on a char boundary.
fn fragments_from<'a>(
    fragments: &[WrapLineFragment<'a>],
    skip: usize,
) -> Vec<WrapLineFragment<'a>> {
    let mut offset = 0;
    let mut out = Vec::with_capacity(fragments.len());
    for fragment in fragments {
        let len = match fragment {
            WrapLineFragment::Text { text } => text.len(),
            WrapLineFragment::Element { len_utf8, .. } => *len_utf8,
        };
        if offset + len <= skip {
            offset += len;
            continue;
        }
        out.push(match fragment {
            WrapLineFragment::Text { text } => {
                WrapLineFragment::text(&text[skip.saturating_sub(offset)..])
            }
            WrapLineFragment::Element { width, len_utf8 } => {
                WrapLineFragment::element(*width, *len_utf8)
            }
        });
        offset += len;
    }
    out
}

/// One run of a hard line as the renderer lays it out: text shaped once in
/// context, or an object / image of fixed width. Ranges are hard-line offsets.
enum ShapedSpan {
    Text {
        range: Range<usize>,
        line: Box<ShapedLine>,
        padding: Pixels,
    },
    Fixed {
        range: Range<usize>,
        width: Pixels,
    },
}

fn shaped_spans(
    items: &[MeasureItem],
    image_sizes: &[Option<Size<Pixels>>],
    objects: &[Option<MeasuredInlineObject>],
    text_style: &TextStyle,
    hard_line: &Range<usize>,
    window: &mut Window,
) -> Vec<ShapedSpan> {
    let font_size = text_style.font_size.to_pixels(window.rem_size());
    let mut spans = Vec::new();
    let mut item_start = 0;
    for (ix, item) in items.iter().enumerate() {
        let item_end = item_start + item.len();
        if item_end > hard_line.start && item_start < hard_line.end {
            match item {
                MeasureItem::Text {
                    text, highlights, ..
                } => {
                    let local_start = hard_line.start.max(item_start) - item_start;
                    let local_end = hard_line.end.min(item_end) - item_start;
                    for (segment, scale) in
                        text_size_ranges(text.len(), highlights, font_size, window.rem_size())
                    {
                        let start = local_start.max(segment.start);
                        let end = local_end.min(segment.end);
                        if start >= end {
                            continue;
                        }
                        let highlights = slice_ranges(highlights, start, end, |range, style| {
                            (range, style.clone())
                        });
                        let runs = text_runs(end - start, text_style, &highlights);
                        let line = Box::new(shape_line(
                            SharedString::from(text[start..end].to_string()),
                            font_size * scale,
                            &runs,
                            window,
                        ));
                        let insets = code_insets(&highlights, font_size * scale, window.rem_size());
                        let padding = insets.left + insets.right;
                        spans.push(ShapedSpan::Text {
                            range: item_start + start..item_start + end,
                            line,
                            padding,
                        });
                    }
                }
                MeasureItem::Object { .. } => spans.push(ShapedSpan::Fixed {
                    range: item_start..item_end,
                    width: objects[ix].as_ref().unwrap().metrics.size.width,
                }),
                MeasureItem::Image { .. } => {
                    if let Some(size) = image_sizes[ix] {
                        spans.push(ShapedSpan::Fixed {
                            range: item_start..item_end,
                            width: size.width,
                        });
                    }
                }
            }
        }
        item_start = item_end;
    }
    spans
}

/// Painted width of `range`: in-context glyph advances of the shaped spans it
/// covers, plus the fixed spans that lie inside it.
fn spans_width(spans: &[ShapedSpan], range: Range<usize>) -> Pixels {
    spans
        .iter()
        .map(|span| match span {
            ShapedSpan::Text {
                range: span_range,
                line,
                padding,
            } => {
                let start = range.start.max(span_range.start);
                let end = range.end.min(span_range.end);
                if start >= end {
                    return Pixels::ZERO;
                }
                line.x_for_index(end - span_range.start)
                    - line.x_for_index(start - span_range.start)
                    + *padding
            }
            ShapedSpan::Fixed {
                range: span_range,
                width,
            } => {
                if range.start <= span_range.start && span_range.end <= range.end {
                    *width
                } else {
                    Pixels::ZERO
                }
            }
        })
        .sum()
}

/// Appends the wrap fragments for `range` of `text`. The line wrapper
/// measures text fragments in the body font, so a span whose highlight sets
/// another family is shaped with the same run the renderer uses and enters
/// the wrapper as measured elements. Oversized spans retain word boundaries;
/// oversized words can break at grapheme boundaries without splitting Unicode.
fn push_text_wrap_fragments<'a>(
    fragments: &mut Vec<WrapLineFragment<'a>>,
    text: &'a str,
    highlights: &[(Range<usize>, InlineHighlight)],
    range: Range<usize>,
    text_style: &TextStyle,
    wrap_width: Pixels,
    window: &mut Window,
) {
    let font_size = text_style.font_size.to_pixels(window.rem_size());
    let mut cursor = range.start;
    for (highlight_range, highlight) in highlights {
        if highlight.font_family.is_none() {
            continue;
        }
        let start = highlight_range.start.max(cursor);
        let end = highlight_range.end.min(range.end);
        if start >= end {
            continue;
        }
        if cursor < start {
            fragments.push(WrapLineFragment::text(&text[cursor..start]));
        }
        let span = &text[start..end];
        let rem_size = window.rem_size();
        let measured_font_size = highlight.font_size(font_size, rem_size);
        let measure = |text: &str| {
            let runs = text_runs(
                text.len(),
                text_style,
                &[(0..text.len(), highlight.clone())],
            );
            window
                .text_system()
                .layout_line(text, measured_font_size, &runs, None)
                .width
        };
        let insets = highlight.code_insets(measured_font_size, rem_size);
        let padding = insets.left + insets.right;
        let width = measure(span) + padding;
        if width <= wrap_width {
            fragments.push(WrapLineFragment::element(width, span.len()));
        } else {
            for word in span.split_word_bounds() {
                let width = measure(word) + padding;
                if width <= wrap_width {
                    fragments.push(WrapLineFragment::element(width, word.len()));
                } else {
                    for grapheme in word.graphemes(true) {
                        fragments.push(WrapLineFragment::element(
                            measure(grapheme) + padding,
                            grapheme.len(),
                        ));
                    }
                }
            }
        }
        cursor = end;
    }
    if cursor < range.end {
        fragments.push(WrapLineFragment::text(&text[cursor..range.end]));
    }
}

#[allow(clippy::too_many_arguments)]
fn measure_image_size(
    ix: usize,
    source: &ImageSource,
    width: Option<DefiniteLength>,
    height: Option<DefiniteLength>,
    line_height: Pixels,
    rem_size: Pixels,
    window: &mut Window,
    cx: &mut App,
) -> Size<Pixels> {
    let intrinsic_size = if width.is_some() && height.is_some() {
        None
    } else {
        intrinsic_image_size(ix, source, width, height, window, cx)
    };
    image_size(width, height, intrinsic_size, line_height, rem_size)
}

fn intrinsic_image_size(
    ix: usize,
    source: &ImageSource,
    width: Option<DefiniteLength>,
    height: Option<DefiniteLength>,
    window: &mut Window,
    cx: &mut App,
) -> Option<Size<Pixels>> {
    let mut element = img(source.clone())
        .id(ix)
        .object_fit(ObjectFit::Contain)
        .max_w(relative(1.))
        .when_some(width, |this, width| this.w(width))
        .when_some(height, |this, height| this.h(height))
        .into_any_element();
    let measured_size = element.layout_as_root(AvailableSpace::min_size(), window, cx);

    if measured_size.width <= Pixels::ZERO || measured_size.height <= Pixels::ZERO {
        None
    } else {
        Some(measured_size)
    }
}

fn image_size(
    width: Option<DefiniteLength>,
    height: Option<DefiniteLength>,
    intrinsic_size: Option<Size<Pixels>>,
    line_height: Pixels,
    rem_size: Pixels,
) -> Size<Pixels> {
    let base_size = AbsoluteLength::Pixels(line_height);
    match (width, height) {
        (Some(width), Some(height)) => size(
            width.to_pixels(base_size, rem_size),
            height.to_pixels(base_size, rem_size),
        ),
        (Some(width), None) => {
            let width = width.to_pixels(base_size, rem_size);
            let height = intrinsic_size
                .and_then(|intrinsic_size| {
                    (intrinsic_size.width > Pixels::ZERO && intrinsic_size.height > Pixels::ZERO)
                        .then(|| width * (intrinsic_size.height / intrinsic_size.width))
                })
                .unwrap_or(line_height);
            size(width, height)
        }
        (None, Some(height)) => {
            let height = height.to_pixels(base_size, rem_size);
            let width = intrinsic_size
                .and_then(|intrinsic_size| {
                    (intrinsic_size.width > Pixels::ZERO && intrinsic_size.height > Pixels::ZERO)
                        .then(|| height * (intrinsic_size.width / intrinsic_size.height))
                })
                .unwrap_or(height);
            size(width, height)
        }
        (None, None) => inline_image_size_for_line(intrinsic_size, line_height),
    }
}

fn inline_image_size_for_line(
    intrinsic_size: Option<Size<Pixels>>,
    line_height: Pixels,
) -> Size<Pixels> {
    let height = line_height * 0.75;
    let aspect_ratio = intrinsic_size
        .and_then(|intrinsic_size| {
            (intrinsic_size.width > Pixels::ZERO && intrinsic_size.height > Pixels::ZERO)
                .then(|| intrinsic_size.width / intrinsic_size.height)
        })
        .unwrap_or(1.);

    size((height * aspect_ratio).max(px(1.)), height.max(px(1.)))
}

fn shape_line(
    text: SharedString,
    font_size: Pixels,
    runs: &[TextRun],
    window: &mut Window,
) -> ShapedLine {
    window.text_system().shape_line(text, font_size, runs, None)
}

/// The line height GPUI's text layout gives a plain line in `text_style`.
/// Unlike `Window::line_height`, it is not first rounded to a whole logical
/// pixel, which would make a flow line taller than a plain one.
fn plain_line_height(text_style: &TextStyle, rem_size: Pixels, window: &Window) -> Pixels {
    window.pixel_snap(
        text_style
            .line_height
            .to_pixels(text_style.font_size, rem_size),
    )
}

/// Returns where GPUI text painting puts the baseline of `shaped_line` in a
/// box `line_height` tall: centered, even when the glyphs overflow the box.
/// `ShapedLine::descent` is positive; do not substitute the signed
/// `FontMetrics::descent` exposed by `TextSystem::baseline_offset` here.
fn centered_baseline(shaped_line: &ShapedLine, line_height: Pixels) -> Pixels {
    (line_height - shaped_line.ascent - shaped_line.descent) / 2. + shaped_line.ascent
}

pub(super) fn slice_ranges<T, U>(
    ranges: &[(Range<usize>, T)],
    start: usize,
    end: usize,
    map: impl Fn(Range<usize>, &T) -> U,
) -> Vec<U> {
    ranges
        .iter()
        .filter_map(|(range, value)| {
            let clipped_start = range.start.max(start);
            let clipped_end = range.end.min(end);
            (clipped_start < clipped_end)
                .then(|| map((clipped_start - start)..(clipped_end - start), value))
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use gpui::SharedUri;

    mod frames {
        use super::super::FLOW_LAYOUTS;
        use crate::text::{TextView, TextViewState};
        use gpui::{
            AppContext as _, Context, Entity, IntoElement, ParentElement as _, Pixels, Render,
            Styled as _, TestAppContext, VisualTestContext, Window, div, px,
        };

        struct Answer {
            state: Entity<TextViewState>,
            width: Pixels,
        }

        impl Render for Answer {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                div().w(self.width).child(TextView::new(&self.state))
            }
        }

        fn draw(cx: &mut VisualTestContext) {
            cx.update(|window, cx| window.draw(cx).clear(cx));
        }

        fn layouts() -> usize {
            FLOW_LAYOUTS.with(|layouts| layouts.get())
        }

        /// Scrolling redraws every visible paragraph each frame; a flow whose
        /// text, style and width are unchanged has nothing to wrap or shape.
        #[gpui::test]
        fn an_unchanged_flow_is_not_laid_out_again(cx: &mut TestAppContext) {
            cx.update(crate::init);
            let (_, cx) = cx.add_window_view(|_, cx| Answer {
                state: cx.new(|cx| TextViewState::markdown("Call `foo` now.", cx)),
                width: px(300.),
            });
            cx.run_until_parked();
            draw(cx);
            let after_first_frame = layouts();
            assert!(after_first_frame >= 1, "the first frame lays the flow out");

            for _ in 0..3 {
                draw(cx);
            }

            assert_eq!(layouts(), after_first_frame, "a frame that changes nothing");
        }

        #[gpui::test]
        fn a_flow_is_laid_out_again_at_another_width(cx: &mut TestAppContext) {
            cx.update(crate::init);
            let (answer, cx) = cx.add_window_view(|_, cx| Answer {
                state: cx.new(|cx| TextViewState::markdown("Call `foo` now.", cx)),
                width: px(300.),
            });
            cx.run_until_parked();
            draw(cx);
            let before = layouts();

            answer.update(cx, |answer, cx| {
                answer.width = px(120.);
                cx.notify();
            });
            draw(cx);

            assert!(layouts() > before, "a narrower flow wraps differently");
        }

        #[gpui::test]
        fn a_flow_is_laid_out_again_when_its_text_changes(cx: &mut TestAppContext) {
            cx.update(crate::init);
            let (answer, cx) = cx.add_window_view(|_, cx| Answer {
                state: cx.new(|cx| TextViewState::markdown("Call `foo` now.", cx)),
                width: px(300.),
            });
            cx.run_until_parked();
            draw(cx);
            let before = layouts();

            answer.update(cx, |answer, cx| {
                answer.state.update(cx, |state, cx| {
                    state.set_text("Call `foo` and `bar` now.", cx);
                })
            });
            cx.run_until_parked();
            draw(cx);

            assert!(layouts() > before, "a new text has a new layout");
        }
    }

    #[test]
    fn atomic_objects_wrap_and_share_a_baseline_at_multiple_font_sizes() {
        use super::super::inline::test_draw::in_prepaint;
        use super::super::inline::test_fonts::{BODY, WideMonoTextSystem};
        use gpui::TestApp;
        let mut app = TestApp::with_text_system(Arc::new(WideMonoTextSystem));
        in_prepaint(&mut app, |window, cx| {
            for scale in [1., 1.5, 2.] {
                let style = TextStyle {
                    font_family: BODY.into(),
                    font_size: px(16. * scale).into(),
                    ..Default::default()
                };
                let items = vec![
                    MeasureItem::Text {
                        text: "中文 ".into(),
                        links: vec![],
                        highlights: vec![],
                    },
                    MeasureItem::Object {
                        text: "x²".into(),
                        id: 0,
                        renderer: Arc::new(|_, _, _| None),
                        style: Default::default(),
                    },
                    MeasureItem::Object {
                        text: "y²".into(),
                        id: 1,
                        renderer: Arc::new(|_, _, _| None),
                        style: Default::default(),
                    },
                    MeasureItem::Text {
                        text: " English".into(),
                        links: vec![],
                        highlights: vec![],
                    },
                ];
                for width in [1., 30., 80., 500.] {
                    let layout = layout_flow(
                        &items,
                        &[None, None, None, None],
                        &style,
                        Some(px(width)),
                        window,
                        cx,
                    );
                    let objects: Vec<_> = layout
                        .fragments
                        .iter()
                        .filter_map(|fragment| match fragment {
                            PositionedFragment::Object { origin, object, .. } => {
                                Some((origin, object))
                            }
                            _ => None,
                        })
                        .collect();
                    assert_eq!(objects.len(), 2);
                    for (origin, object) in &objects {
                        assert!(object.metrics.size.width <= px(width));
                        assert!(origin.y >= px(0.));
                        assert!(origin.y + object.metrics.size.height <= layout.size.height);
                    }
                    if width == 500. {
                        assert_eq!(
                            objects[0].0.y + objects[0].1.metrics.baseline,
                            objects[1].0.y + objects[1].1.metrics.baseline
                        );
                    }
                }
            }
        });
    }

    #[test]
    fn inline_image_without_explicit_size_scales_intrinsic_ratio_to_line_height() {
        let line_height = px(20.);
        let intrinsic_size = size(px(160.), px(40.));

        let measured = inline_image_size_for_line(Some(intrinsic_size), line_height);

        assert_eq!(measured, size(px(60.), px(15.)));
    }

    #[test]
    fn inline_image_without_intrinsic_size_uses_compact_square_fallback() {
        let measured = inline_image_size_for_line(None, px(20.));

        assert_eq!(measured, size(px(15.), px(15.)));
    }

    /// Line breaking must see the width of an inline code span in its own
    /// family. With a body-font-only wrapper the span below is measured at
    /// half its shaped width, the line is kept whole, and the flow reports a
    /// width past `wrap_width`.
    #[test]
    fn inline_code_near_the_wrap_width_does_not_overflow_the_flow() {
        use super::super::inline::test_fonts::{BODY, MONO, WideMonoTextSystem};
        use gpui::{AbsoluteLength, Empty, HighlightStyle, TestApp};

        let mut app = TestApp::with_text_system(Arc::new(WideMonoTextSystem));
        let mut window = app.open_window(|_, _| Empty);

        let font_size = px(10.);
        let text_style = TextStyle {
            font_family: SharedString::from(BODY),
            font_size: AbsoluteLength::Pixels(font_size),
            ..Default::default()
        };
        let lead = SharedString::from("See ");
        let tail_text = " with code_span_here end";
        let code = tail_text.find("code_span_here").unwrap();
        let code_range = code..code + "code_span_here".len();
        let code_highlight = InlineHighlight {
            style: HighlightStyle::default(),
            font_family: Some(SharedString::from(MONO)),
            font_size_scale: None,
            code_style: None,
        };
        let items = vec![
            MeasureItem::Text {
                text: lead.clone(),
                links: vec![],
                highlights: vec![],
            },
            MeasureItem::Image {
                source: SharedUri::from("https://example.com/badge.png").into(),
                width: None,
                height: None,
            },
            MeasureItem::Text {
                text: SharedString::from(tail_text),
                links: vec![],
                highlights: vec![(code_range.clone(), code_highlight)],
            },
        ];
        let image_size = size(px(10.), px(10.));
        let image_sizes = vec![None, Some(image_size), None];
        // Body text, the image and the mono span fill the wrap width exactly;
        // the trailing "end" only fits if the span is under-measured.
        let wrap_width = WideMonoTextSystem::width_of("See  with  ", BODY, font_size)
            + image_size.width
            + WideMonoTextSystem::width_of("code_span_here", MONO, font_size);

        let layout = window.update(|_, window, cx| {
            layout_flow(
                &items,
                &image_sizes,
                &text_style,
                Some(wrap_width),
                window,
                cx,
            )
        });

        assert!(
            layout.size.width <= wrap_width,
            "flow width {:?} exceeds wrap width {:?}",
            layout.size.width,
            wrap_width
        );
        let mono_fragment_width = layout
            .fragments
            .iter()
            .find_map(|fragment| match fragment {
                PositionedFragment::Text { text, size, .. } if text.contains("code_span_here") => {
                    Some(size.width)
                }
                _ => None,
            })
            .expect("the code span is laid out as a text fragment");
        assert!(
            mono_fragment_width >= WideMonoTextSystem::width_of("code_span_here", MONO, font_size),
            "the code span fragment is shaped in the mono family"
        );
        // The image sits vertically centred in its line, so line membership is
        // read off the text fragments only.
        let text_lines = layout
            .fragments
            .iter()
            .filter_map(|fragment| match fragment {
                PositionedFragment::Text { text, origin, .. } => Some((text.trim(), origin.y)),
                PositionedFragment::Image { .. } | PositionedFragment::Object { .. } => None,
            })
            .collect::<Vec<_>>();
        let first_y = text_lines[0].1;
        assert!(
            text_lines
                .iter()
                .any(|(text, y)| text.contains("code_span_here") && *y == first_y),
            "the span stays on the first line: {text_lines:?}"
        );
        assert!(
            text_lines
                .iter()
                .any(|(text, y)| *text == "end" && *y > first_y),
            "the trailing word wraps to a second line: {text_lines:?}"
        );
    }
    #[test]
    fn long_inline_code_wraps_in_mixed_flow() {
        use super::super::inline::test_fonts::{BODY, MONO, WideMonoTextSystem};
        use gpui::{Empty, TestApp};
        let mut app = TestApp::with_text_system(Arc::new(WideMonoTextSystem));
        let mut window = app.open_window(|_, _| Empty);
        let style = TextStyle {
            font_family: BODY.into(),
            font_size: AbsoluteLength::Pixels(px(10.)),
            ..Default::default()
        };
        for text in [
            "one two three four five six",
            "very_long_unbroken_identifier",
            "你好世界你好世界你好世界",
            "e\u{301}e\u{301}e\u{301}e\u{301}e\u{301}e\u{301}",
        ] {
            let items = vec![
                MeasureItem::Image {
                    source: SharedUri::from("https://example.com/icon.png").into(),
                    width: None,
                    height: None,
                },
                MeasureItem::Text {
                    text: text.into(),
                    links: vec![],
                    highlights: vec![(
                        0..text.len(),
                        InlineHighlight {
                            font_family: Some(MONO.into()),
                            ..Default::default()
                        },
                    )],
                },
            ];
            let image_sizes = vec![Some(size(px(10.), px(10.))), None];
            let layout = window.update(|_, window, cx| {
                layout_flow(&items, &image_sizes, &style, Some(px(100.)), window, cx)
            });
            assert!(layout.size.width <= px(100.), "{text:?}: {:?}", layout.size);
            let reconstructed: String = layout
                .fragments
                .iter()
                .filter_map(|fragment| match fragment {
                    PositionedFragment::Text { text, .. } => Some(text.as_ref()),
                    _ => None,
                })
                .collect();
            assert_eq!(reconstructed, text);
        }
    }

    #[test]
    fn inline_code_line_is_as_tall_as_a_plain_line_when_glyphs_overflow_it() {
        use super::super::inline::test_fonts::{BODY, MONO, WideMonoTextSystem};
        use gpui::{Empty, TestApp};

        let mut app = TestApp::with_text_system(Arc::new(WideMonoTextSystem));
        let mut window = app.open_window(|_, _| Empty);
        let style = TextStyle {
            font_family: BODY.into(),
            font_size: AbsoluteLength::Pixels(px(40.)),
            line_height: px(30.).into(),
            ..Default::default()
        };
        let items = vec![MeasureItem::Text {
            text: "a code z".into(),
            links: vec![],
            highlights: vec![(
                2..6,
                InlineHighlight {
                    font_family: Some(MONO.into()),
                    font_size_scale: Some(0.875),
                    ..Default::default()
                },
            )],
        }];
        // The 40px glyphs are taller than the 30px line. A plain text line
        // keeps the line height and lets them overflow, so a line with
        // inline code must not grow to fit them.
        window.update(|_, window, cx| {
            let layout = layout_flow(&items, &[None], &style, None, window, cx);
            assert_eq!(layout.size.height, window.pixel_snap(px(30.)));
        });
    }

    #[test]
    fn inline_code_style_keeps_equal_size_prose_separate_and_measures_its_box() {
        use super::super::inline::test_fonts::{BODY, MONO, WideMonoTextSystem};
        use gpui::{Empty, HighlightStyle, TestApp, rems};
        let mut app = TestApp::with_text_system(Arc::new(WideMonoTextSystem));
        let mut window = app.open_window(|_, _| Empty);
        for rem_size in [px(14.), px(28.)] {
            window.update(|_, window, cx| {
                window.set_rem_size(rem_size);
                let text_style = TextStyle {
                    font_family: BODY.into(),
                    font_size: rem_size.into(),
                    ..Default::default()
                };
                let code_style = StyleRefinement::default()
                    .text_size(rems(1.))
                    .px(rems(0.25))
                    .py(rems(0.125))
                    .bg(gpui::red())
                    .border_1()
                    .border_color(gpui::blue())
                    .rounded(rems(0.25));
                let highlight = InlineHighlight {
                    font_family: Some(MONO.into()),
                    font_size_scale: Some(0.875),
                    code_style: Some(code_style.clone()),
                    style: HighlightStyle {
                        background_color: Some(gpui::green()),
                        ..Default::default()
                    },
                };
                let items = vec![MeasureItem::Text {
                    text: "before code after".into(),
                    links: vec![],
                    highlights: vec![(7..11, highlight)],
                }];
                let layout = layout_flow(&items, &[None], &text_style, None, window, cx);
                assert_eq!(layout.fragments.len(), 3);
                for fragment in &layout.fragments {
                    let PositionedFragment::Text {
                        text,
                        size,
                        font_size,
                        code_background,
                        ..
                    } = fragment
                    else {
                        panic!("expected text");
                    };
                    assert_eq!(*font_size, rem_size);
                    if text.as_ref() == "code" {
                        let code = code_background.as_ref().expect("code box");
                        assert_eq!(code.style.background, code_style.background);
                        assert_eq!(code.style.border_color, Some(gpui::blue()));
                        assert_eq!(code.style.corner_radii, code_style.corner_radii);
                        assert_eq!(code.bounds.size.width, size.width);
                        assert_eq!(
                            size.width,
                            WideMonoTextSystem::width_of("code", MONO, rem_size)
                                + rem_size * 0.5
                                + px(2.)
                        );
                    } else {
                        assert!(code_background.is_none());
                        assert_eq!(
                            size.width,
                            WideMonoTextSystem::width_of(text, BODY, rem_size)
                        );
                    }
                }
                // The same insets must be included by wrapping, not just drawing.
                let wrap_width = WideMonoTextSystem::width_of("before ", BODY, rem_size)
                    + WideMonoTextSystem::width_of("code", MONO, rem_size)
                    + rem_size * 0.5
                    + px(1.);
                let wrapped =
                    layout_flow(&items, &[None], &text_style, Some(wrap_width), window, cx);
                assert!(wrapped.size.height > layout.size.height);
                assert!(wrapped.size.width <= wrap_width);
                let reconstructed = wrapped
                    .fragments
                    .iter()
                    .filter_map(|fragment| match fragment {
                        PositionedFragment::Text { text, .. } => Some(text.as_ref()),
                        _ => None,
                    })
                    .collect::<String>();
                assert_eq!(reconstructed, "before code after");
            });
        }
    }

    #[test]
    fn inline_code_size_is_relative_and_uses_the_native_body_baseline() {
        use super::super::inline::test_fonts::{BODY, MONO, WideMonoTextSystem};
        use gpui::{Empty, TestApp};

        let mut app = TestApp::with_text_system(Arc::new(WideMonoTextSystem));
        let mut window = app.open_window(|_, _| Empty);
        // These are the 16px body size and the example-markdown preview's
        // 1.25x/1.5x inherited text-size zooms.
        for body_size in [16., 20., 24.] {
            let style = TextStyle {
                font_family: BODY.into(),
                font_size: AbsoluteLength::Pixels(px(body_size)),
                ..Default::default()
            };
            let items = vec![MeasureItem::Text {
                text: "a code z".into(),
                links: vec![],
                highlights: vec![(
                    2..6,
                    InlineHighlight {
                        font_family: Some(MONO.into()),
                        font_size_scale: Some(0.875),
                        ..Default::default()
                    },
                )],
            }];
            window.update(|_, window, cx| {
                let layout = layout_flow(&items, &[None], &style, None, window, cx);
                let text_fragments = layout
                    .fragments
                    .iter()
                    .filter_map(|fragment| match fragment {
                        PositionedFragment::Text {
                            text,
                            font_size,
                            origin,
                            size,
                            ..
                        } => Some((text.as_ref(), *font_size, origin.y, *size)),
                        _ => None,
                    })
                    .collect::<Vec<_>>();
                assert_eq!(text_fragments.len(), 3);
                assert_eq!(text_fragments[0].1, px(body_size));
                assert_eq!(text_fragments[1].0, "code");
                assert_eq!(text_fragments[1].1, px(body_size * 0.875));
                // The code run's box stays inside the line, so whatever it
                // paints over its box cannot reach a neighboring line.
                assert!(text_fragments[1].2 >= Pixels::ZERO);
                assert!(text_fragments[1].2 + text_fragments[1].3.height <= layout.size.height);
                assert_eq!(
                    text_fragments[1].3.width,
                    WideMonoTextSystem::width_of("code", MONO, px(body_size * 0.875))
                        + px(INLINE_CODE_PADDING * 2.)
                );

                // GPUI paints shaped lines with positive `LineLayout::descent`.
                // Derive the ordinary body glyph baseline directly from that
                // native-compatible shaped line, rather than `baseline_offset`,
                // whose FontMetrics descent is intentionally signed.
                let body_runs = text_runs(1, &style, &[]);
                let body_line = shape_line("a".into(), px(body_size), &body_runs, window);
                let body_line_height = plain_line_height(&style, window.rem_size(), window);
                let plain_body_baseline = (body_line_height - body_line.ascent - body_line.descent)
                    / 2.
                    + body_line.ascent;
                // The smaller code run fits inside the body line, so the
                // line must be exactly as tall as a plain one.
                assert_eq!(
                    layout.size.height, body_line_height,
                    "{body_size}px line height"
                );
                let mut painted_glyph_baseline =
                    |fragment: &(&str, Pixels, Pixels, Size<Pixels>)| {
                        let runs = if fragment.0 == "code" {
                            text_runs(
                                fragment.0.len(),
                                &style,
                                &[(
                                    0..fragment.0.len(),
                                    InlineHighlight {
                                        font_family: Some(MONO.into()),
                                        font_size_scale: Some(0.875),
                                        ..Default::default()
                                    },
                                )],
                            )
                        } else {
                            text_runs(fragment.0.len(), &style, &[])
                        };
                        let shaped = shape_line(fragment.0.into(), fragment.1, &runs, window);
                        fragment.2
                            + (fragment.3.height - shaped.ascent - shaped.descent) / 2.
                            + shaped.ascent
                    };

                // `origin` is passed unchanged to Inline::paint_origin, so this
                // checks the first body glyph's painted row position, not only
                // the enclosing paragraph height. It must agree with a normal
                // body line and with the adjacent inline-code glyph baseline.
                assert_eq!(
                    text_fragments[0].2,
                    Pixels::ZERO,
                    "{body_size}px body origin"
                );
                assert_eq!(
                    painted_glyph_baseline(&text_fragments[0]),
                    plain_body_baseline,
                    "{body_size}px body glyph baseline"
                );
                assert_eq!(
                    painted_glyph_baseline(&text_fragments[1]),
                    plain_body_baseline,
                    "{body_size}px code glyph baseline"
                );
            });
        }
    }
}
