//! Presentation callbacks and measured geometry. None of this enters document history.
use super::{InlineToken, InlineTokenSpan, InputBaseState, InputModeKind, rope_ext::RopeExt as _};
use gpui::{AnyElement, App, Bounds, ClickEvent, Font, IntoElement, Pixels, Window};
use std::{collections::HashMap, ops::Range, rc::Rc};

/// Read-only context for a single inline renderer. Width is the full available row.
#[derive(Clone)]
pub struct InlineTokenContext {
    span: InlineTokenSpan,
    selected: bool,
    disabled: bool,
    readonly: bool,
    line_height: Pixels,
    available_width: Pixels,
}
impl InlineTokenContext {
    pub fn token(&self) -> &InlineToken {
        self.span.token()
    }
    pub fn range(&self) -> Range<usize> {
        self.span.range()
    }
    pub fn is_selected(&self) -> bool {
        self.selected
    }
    pub fn is_disabled(&self) -> bool {
        self.disabled
    }
    pub fn is_readonly(&self) -> bool {
        self.readonly
    }
    pub fn line_height(&self) -> Pixels {
        self.line_height
    }
    pub fn available_width(&self) -> Pixels {
        self.available_width
    }
}

/// Current token snapshot delivered after releasing the editor's update borrow.
#[derive(Clone)]
pub struct InlineTokenClickEvent {
    span: InlineTokenSpan,
    bounds: Bounds<Pixels>,
    event: ClickEvent,
}
impl InlineTokenClickEvent {
    pub fn token(&self) -> &InlineToken {
        self.span.token()
    }
    pub fn range(&self) -> Range<usize> {
        self.span.range()
    }
    pub fn bounds(&self) -> Bounds<Pixels> {
        self.bounds
    }
    /// The click that opened the token; keyboard activation reports a
    /// keyboard click.
    pub fn click(&self) -> &ClickEvent {
        &self.event
    }
}

/// Hover snapshot for one atomic inline token. Hover never selects or edits;
/// it reports pointer presence so the application can show a tooltip or run
/// custom logic.
#[derive(Clone)]
pub struct InlineTokenHoverEvent {
    span: InlineTokenSpan,
    bounds: Bounds<Pixels>,
    hovered: bool,
    range_utf16: (usize, usize),
}
impl InlineTokenHoverEvent {
    pub fn token(&self) -> &InlineToken {
        self.span.token()
    }
    pub fn range(&self) -> Range<usize> {
        self.span.range()
    }
    pub fn bounds(&self) -> Bounds<Pixels> {
        self.bounds
    }
    /// Whether the pointer entered (`true`) or left (`false`) the token.
    pub fn is_hovered(&self) -> bool {
        self.hovered
    }
    /// The token range in UTF-16 code units, captured when the event was
    /// built. Exits delivered after the text changed report these entry
    /// coordinates, since the byte range can no longer be converted against
    /// the current text.
    pub fn range_utf16(&self) -> (usize, usize) {
        self.range_utf16
    }
}

/// The retained hover presence: the entered span, its placed bounds, and its
/// UTF-16 range as of entry. JavaScript string offsets shift with later edits,
/// so an exit delivered after a change cannot recompute them from the current
/// text and reuses these instead.
#[derive(Clone)]
pub(super) struct HoverSnapshot {
    pub(super) span: InlineTokenSpan,
    pub(super) bounds: Bounds<Pixels>,
    pub(super) range_utf16: (usize, usize),
}

/// A renderer installed by a styled control. Not part of the supported API.
#[doc(hidden)]
pub type InlineTokenRenderer = Rc<dyn Fn(&InlineTokenContext, &mut Window, &mut App) -> AnyElement>;
/// A click listener installed by a styled control. Not part of the supported API.
#[doc(hidden)]
pub type InlineTokenClickListener = Rc<dyn Fn(&InlineTokenClickEvent, &mut Window, &mut App)>;
/// A hover listener installed by a styled control. Not part of the supported API.
#[doc(hidden)]
pub type InlineTokenHoverListener = Rc<dyn Fn(&InlineTokenHoverEvent, &mut Window, &mut App)>;

/// Presentation shared by Base and styled controls. It owns no content.
#[derive(Clone, Default)]
pub(crate) struct InlineTokenPresentation {
    renderer: Option<InlineTokenRenderer>,
    listener: Option<InlineTokenClickListener>,
    hover_listener: Option<InlineTokenHoverListener>,
    secret: bool,
}
impl InlineTokenPresentation {
    pub(crate) fn token<R: IntoElement>(
        mut self,
        render: impl Fn(&InlineTokenContext, &mut Window, &mut App) -> R + 'static,
    ) -> Self {
        self.renderer = Some(Rc::new(move |token, window, cx| {
            render(token, window, cx).into_any_element()
        }));
        self
    }
    pub(crate) fn on_token_click(
        mut self,
        listener: impl Fn(&InlineTokenClickEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.listener = Some(Rc::new(listener));
        self
    }
    pub(crate) fn on_token_hover(
        mut self,
        listener: impl Fn(&InlineTokenHoverEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.hover_listener = Some(Rc::new(listener));
        self
    }
    pub(super) fn has_hover_listener(&self) -> bool {
        self.hover_listener.is_some()
    }
    pub(super) fn has_listener(&self) -> bool {
        self.listener.is_some()
    }
    pub(super) fn render(
        &self,
        token: &InlineTokenContext,
        window: &mut Window,
        cx: &mut App,
    ) -> AnyElement {
        if let Some(render) = &self.renderer {
            render(token, window, cx)
        } else {
            gpui::div()
                .child(token.token().label().clone())
                .into_any_element()
        }
    }
}
use gpui::ParentElement as _;

#[derive(Default)]
pub(super) struct TokenLayoutCache {
    pub(super) key: Option<(Font, Pixels, Pixels, Pixels, bool)>,
    pub(super) revision: u64,
    pub(super) unwrapped_width: Pixels,
    pub(super) metrics: Rc<[(Range<usize>, Pixels)]>,
    pub(super) widths: HashMap<InlineToken, Pixels>,
}

impl<M: InputModeKind> InputBaseState<M> {
    /// Inject presentation from a view without editing or notifying the document.
    pub(crate) fn set_token_presentation(&mut self, presentation: InlineTokenPresentation) {
        self.token_presentation = presentation;
    }
    /// Install a styled control's renderer, click listener and secrecy without
    /// editing or notifying the document. Not part of the supported API.
    #[doc(hidden)]
    pub fn install_token_presentation(
        &mut self,
        renderer: Option<InlineTokenRenderer>,
        listener: Option<InlineTokenClickListener>,
        secret: bool,
    ) {
        self.token_presentation = InlineTokenPresentation {
            renderer,
            listener,
            hover_listener: self.token_presentation.hover_listener.clone(),
            secret,
        };
    }
    /// Install a styled control's token hover listener without editing or
    /// notifying the document. Kept separate so the original installer keeps
    /// compiling for existing consumers. Not part of the supported API.
    #[doc(hidden)]
    pub fn install_token_hover_presentation(
        &mut self,
        hover_listener: Option<InlineTokenHoverListener>,
    ) {
        self.token_presentation.hover_listener = hover_listener;
    }
    pub(super) fn tokens_visible(&self) -> bool {
        !self.masked
            && !self.token_presentation.secret
            && self.mask_pattern.is_none()
            && !self.token_spans().is_empty()
    }
    pub(super) fn token_context(
        &self,
        span: &InlineTokenSpan,
        line_height: Pixels,
        width: Pixels,
    ) -> InlineTokenContext {
        let range = span.range();
        let selection = self.selected_range();
        InlineTokenContext {
            span: span.clone(),
            selected: selection.start < range.end && range.start < selection.end,
            disabled: self.disabled,
            readonly: self.readonly,
            line_height,
            available_width: width,
        }
    }
    /// The token starting at `start`, paired with the listener that opens it.
    pub(super) fn token_activation(
        &self,
        start: usize,
        bounds: Bounds<Pixels>,
        event: ClickEvent,
    ) -> Option<(InlineTokenClickListener, InlineTokenClickEvent)> {
        if self.disabled || !self.tokens_visible() {
            return None;
        }
        let span = self
            .token_spans()
            .iter()
            .find(|span| span.range().start == start)?
            .clone();
        Some((
            self.token_presentation.listener.clone()?,
            InlineTokenClickEvent {
                span,
                bounds,
                event,
            },
        ))
    }
    /// The token starting at `start`, paired with the hover listener.
    /// Disabled tokens never enter; existing hover still receives its exit.
    /// Readonly tokens report hover.
    /// Records and clears the retained hover snapshot used for exit
    /// reconciliation. An exit only clears the snapshot when it belongs to the
    /// exiting token: GPUI dispatches a newly entered token before the exit of
    /// the token the pointer left, so an older exit must not drop the newer
    /// token's snapshot.
    pub(super) fn token_hover(
        &mut self,
        start: usize,
        bounds: Bounds<Pixels>,
        hovered: bool,
        expected_token: Option<&InlineToken>,
    ) -> Option<(InlineTokenHoverListener, InlineTokenHoverEvent)> {
        let listener = self.token_presentation.hover_listener.clone()?;
        let matches = |snapshot: &HoverSnapshot| {
            snapshot.span.range().start == start
                && expected_token.is_none_or(|token| snapshot.span.token() == token)
        };
        let snapshot = if hovered {
            if self.disabled || !self.tokens_visible() {
                return None;
            }
            let span = self
                .token_spans()
                .iter()
                .find(|span| {
                    span.range().start == start
                        && expected_token.is_none_or(|token| span.token() == token)
                })?
                .clone();
            if self
                .hovered_token
                .as_ref()
                .is_some_and(|snapshot| snapshot.span == span)
            {
                return None;
            }
            let range = span.range();
            let snapshot = HoverSnapshot {
                span,
                bounds,
                range_utf16: (
                    self.text.offset_to_offset_utf16(range.start),
                    self.text.offset_to_offset_utf16(range.end),
                ),
            };
            if let Some(previous) = self.hovered_token.replace(snapshot.clone()) {
                self.pending_token_hover_exits.push(previous);
            }
            snapshot
        } else if self.hovered_token.as_ref().is_some_and(matches) {
            self.hovered_token.take()?
        } else {
            let index = self.pending_token_hover_exits.iter().position(matches)?;
            self.pending_token_hover_exits.remove(index)
        };
        Some((
            listener,
            InlineTokenHoverEvent {
                span: snapshot.span,
                bounds: snapshot.bounds,
                hovered,
                range_utf16: snapshot.range_utf16,
            },
        ))
    }
    /// Deliver exits from entry snapshots, even after edits or callback reentry
    /// remove the token. Keep predecessors until their mouse exit is dispatched.
    pub(super) fn reconcile_token_hover(
        &mut self,
    ) -> Option<(InlineTokenHoverListener, InlineTokenHoverEvent)> {
        let is_placed = |snapshot: &HoverSnapshot| {
            !self.disabled
                && self.tokens_visible()
                && self.token_presentation.has_hover_listener()
                && self.token_bounds.contains_key(&snapshot.span.range().start)
                && self.token_spans().contains(&snapshot.span)
        };
        let snapshot = if let Some(index) = self
            .pending_token_hover_exits
            .iter()
            .position(|snapshot| !is_placed(snapshot))
        {
            self.pending_token_hover_exits.remove(index)
        } else if self
            .hovered_token
            .as_ref()
            .is_some_and(|snapshot| !is_placed(snapshot))
        {
            self.hovered_token.take()?
        } else {
            return None;
        };
        Some((
            self.token_presentation.hover_listener.clone()?,
            InlineTokenHoverEvent {
                span: snapshot.span,
                bounds: snapshot.bounds,
                hovered: false,
                range_utf16: snapshot.range_utf16,
            },
        ))
    }
    pub(super) fn token_is_secret(&self) -> bool {
        self.token_presentation.secret
    }
}
