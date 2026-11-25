use std::{rc::Rc, time::Duration};

use gpui::{
    AbsoluteLength, AnyElement, App, Axis, Bounds, ClickEvent, ElementId, Hsla, ImageSource,
    InteractiveElement as _, IntoElement, MouseButton, ObjectFit, ParentElement, Path, PathBuilder,
    Pixels, Refineable as _, RenderOnce, ScrollHandle, SharedString,
    StatefulInteractiveElement as _, StyleRefinement, Styled, StyledImage as _, Window, black,
    canvas, div, img, linear_color_stop, linear_gradient, point, prelude::FluentBuilder as _, px,
    relative, rems, white,
};
use gpui_base::{
    is_mobile,
    motion::{Transition, transition},
};
use rust_i18n::t;

use crate::{
    ActiveTheme as _, Icon, IconName, InteractiveElementExt as _, Sizable, Size, StyledExt as _,
    button::{Button, ButtonCustomVariant, ButtonVariants as _},
    h_flex,
    progress::ProgressCircle,
    scroll::ScrollableMask,
    shimmer::{ShimmerStyle, ShimmerText},
    spinner::Spinner,
    tooltip::Tooltip,
    v_flex,
};

/// The lifecycle status of an attachment.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum AttachmentStatus {
    /// The attachment has been selected and is waiting to be uploaded.
    Pending,
    /// The attachment is currently being uploaded.
    Uploading,
    /// The upload has completed and the attachment is being processed.
    Processing,
    /// The attachment failed to upload or process.
    Failed,
    /// The attachment is ready.
    #[default]
    Complete,
}

impl AttachmentStatus {
    /// Returns whether the attachment is waiting to start.
    pub fn is_pending(self) -> bool {
        matches!(self, Self::Pending)
    }

    /// Returns whether the attachment is being uploaded.
    pub fn is_uploading(self) -> bool {
        matches!(self, Self::Uploading)
    }

    /// Returns whether the attachment is being processed.
    pub fn is_processing(self) -> bool {
        matches!(self, Self::Processing)
    }

    /// Returns whether the attachment has failed.
    pub fn is_failed(self) -> bool {
        matches!(self, Self::Failed)
    }

    /// Returns whether the attachment is ready.
    pub fn is_complete(self) -> bool {
        matches!(self, Self::Complete)
    }

    /// Returns whether the attachment is in an in-progress state.
    pub fn is_in_progress(self) -> bool {
        matches!(self, Self::Uploading | Self::Processing)
    }
}

/// A pointer handler for one of the card's built-in controls.
type ControlHandler = Rc<dyn Fn(&ClickEvent, &mut Window, &mut App)>;

/// A built-in control with the identity its element state is keyed on.
type Control = (ElementId, ControlHandler);

/// What the root hands its slots at layout time.
#[derive(Clone)]
struct SlotLayout {
    size: Size,
    status: AttachmentStatus,
    axis: Axis,
    /// Whether the media fills a vertical card flush with its border.
    flush: bool,
    /// The retry control, only while failed and identified.
    retry: Option<Control>,
    /// Upload progress in percent, only while uploading.
    progress: Option<f32>,
    /// The attachment's identity, keying the progress ring's state.
    id: Option<ElementId>,
}

/// How far the remove control rides outside the card's upper trailing corner.
const REMOVE_OVERHANG: Pixels = px(6.);
/// The remove control: a small surface-colored disc with a hairline border.
const REMOVE_BUTTON_SIZE: Pixels = px(20.);
/// The retry control over an image preview.
const RETRY_BUTTON_SIZE: Pixels = px(24.);
/// The hover group the remove control appears for. Siblings may share the
/// name: a group resolves to its nearest ancestor.
const REMOVE_GROUP: &str = "attachment-remove";
/// How much an image preview is darkened while it uploads or processes.
const PROGRESS_SCRIM: f32 = 0.35;
/// How much an image preview is darkened once it has failed.
const FAILED_SCRIM: f32 = 0.55;

/// The geometry a named size resolves to, in rems so it follows the root font size.
struct CardMetrics {
    /// The height of a horizontal card and the side of a square image tile.
    height: AbsoluteLength,
    /// The fixed width of a horizontal card that carries content.
    chip_width: AbsoluteLength,
    /// The side of the square media slot of a horizontal card.
    media: AbsoluteLength,
    /// The glyph size inside the media slot: an icon child without its own size,
    /// and the status glyphs.
    media_glyph: AbsoluteLength,
    /// The padding before the media slot.
    padding_start: AbsoluteLength,
    /// The padding after the content and actions.
    padding_end: AbsoluteLength,
    /// The padding of a vertical card that carries content.
    card_padding: AbsoluteLength,
    gap: AbsoluteLength,
    text: AbsoluteLength,
    description: AbsoluteLength,
}

fn card_metrics(size: Size) -> CardMetrics {
    let r = |value: f32| AbsoluteLength::Rems(rems(value));
    match size {
        Size::XSmall => CardMetrics {
            height: r(2.5),
            chip_width: r(11.),
            media: r(1.75),
            media_glyph: r(0.875),
            padding_start: r(0.25),
            padding_end: r(0.375),
            card_padding: r(0.25),
            gap: r(0.375),
            text: r(0.6875),
            description: r(0.625),
        },
        Size::Small => CardMetrics {
            height: r(3.),
            chip_width: r(12.5),
            media: r(2.),
            media_glyph: r(1.),
            padding_start: r(0.375),
            padding_end: r(0.5),
            card_padding: r(0.375),
            gap: r(0.5),
            text: r(0.75),
            description: r(0.6875),
        },
        Size::Medium => CardMetrics {
            height: r(3.5),
            chip_width: r(14.5),
            media: r(2.375),
            media_glyph: r(1.25),
            padding_start: r(0.5),
            padding_end: r(0.75),
            card_padding: r(0.5),
            gap: r(0.625),
            text: r(0.8125),
            description: r(0.75),
        },
        Size::Large => CardMetrics {
            height: r(4.),
            chip_width: r(17.),
            media: r(2.75),
            media_glyph: r(1.5),
            padding_start: r(0.625),
            padding_end: r(1.),
            card_padding: r(0.75),
            gap: r(0.75),
            text: r(0.875),
            description: r(0.8125),
        },
        // A custom density scales the medium geometry from its base value.
        Size::Size(value) => CardMetrics {
            height: (value * 3.5).into(),
            chip_width: (value * 14.5).into(),
            media: (value * 2.375).into(),
            media_glyph: (value * 1.25).into(),
            padding_start: (value * 0.5).into(),
            padding_end: (value * 0.75).into(),
            card_padding: (value * 0.5).into(),
            gap: (value * 0.625).into(),
            text: (value * 0.8125).into(),
            description: (value * 0.75).into(),
        },
    }
}

/// The card's corner radius for a size.
fn card_radius(size: Size, cx: &App) -> Pixels {
    let tokens = cx.theme().semantic_tokens();
    if size == Size::XSmall {
        tokens.radius.md
    } else {
        tokens.radius.lg
    }
}

/// A file or image attachment composed from media, content, and actions slots.
#[derive(IntoElement)]
pub struct Attachment {
    id: Option<ElementId>,
    style: StyleRefinement,
    status: AttachmentStatus,
    size: Size,
    axis: Axis,
    media: Option<AttachmentMedia>,
    content: Option<AttachmentContent>,
    actions: Option<AttachmentActions>,
    on_click: Option<ControlHandler>,
    on_remove: Option<ControlHandler>,
    on_retry: Option<ControlHandler>,
    progress: Option<f32>,
    tooltip: Option<SharedString>,
}

impl Attachment {
    /// Create an attachment in the [`AttachmentStatus::Complete`] state.
    pub fn new() -> Self {
        Self {
            id: None,
            style: StyleRefinement::default(),
            status: AttachmentStatus::Complete,
            size: Size::Medium,
            axis: Axis::Horizontal,
            media: None,
            content: None,
            actions: None,
            on_click: None,
            on_remove: None,
            on_retry: None,
            progress: None,
            tooltip: None,
        }
    }

    /// Set a stable identity for the built-in controls: the whole-card click
    /// layer, the remove control, and the retry control.
    pub fn id(mut self, id: impl Into<ElementId>) -> Self {
        self.id = Some(id.into());
        self
    }

    /// Make the whole card clickable, e.g. to open a preview.
    ///
    /// The click layer is painted below the actions slot, so action buttons
    /// stay independently clickable. Click state needs a stable identity, so
    /// the handler takes effect only together with [`Self::id`].
    pub fn on_click(
        mut self,
        handler: impl Fn(&ClickEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_click = Some(Rc::new(handler));
        self
    }

    /// Show a remove control riding the card's upper trailing corner.
    ///
    /// The control appears on hover on desktop and stays visible on touch
    /// platforms. It needs a stable identity, so it takes effect only together
    /// with [`Self::id`].
    pub fn on_remove(
        mut self,
        handler: impl Fn(&ClickEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_remove = Some(Rc::new(handler));
        self
    }

    /// Offer a retry control while the attachment is [`AttachmentStatus::Failed`]:
    /// a round button over an image preview, or a link after the typed
    /// description. It takes effect only together with [`Self::id`].
    pub fn on_retry(
        mut self,
        handler: impl Fn(&ClickEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_retry = Some(Rc::new(handler));
        self
    }

    /// Report upload progress as a percentage from 0 to 100.
    ///
    /// While [`AttachmentStatus::Uploading`], the media shows a progress ring
    /// instead of the spinner, a horizontal card draws a thin bar along its
    /// bottom edge, and a typed description gains the percentage.
    pub fn progress(mut self, percent: f32) -> Self {
        self.progress = Some(percent.clamp(0., 100.));
        self
    }

    /// Show a tooltip while the card is hovered, e.g. the reason an upload
    /// failed. It takes effect only together with [`Self::id`].
    pub fn tooltip(mut self, text: impl Into<SharedString>) -> Self {
        self.tooltip = Some(text.into());
        self
    }

    /// Set the attachment lifecycle status.
    pub fn status(mut self, status: AttachmentStatus) -> Self {
        self.status = status;
        self
    }

    /// Set the attachment layout axis.
    pub fn axis(mut self, axis: Axis) -> Self {
        self.axis = axis;
        self
    }

    /// Set the media slot.
    pub fn media(mut self, media: AttachmentMedia) -> Self {
        self.media = Some(media);
        self
    }

    /// Set the metadata content slot.
    pub fn content(mut self, content: AttachmentContent) -> Self {
        self.content = Some(content);
        self
    }

    /// Set the actions slot.
    pub fn actions(mut self, actions: AttachmentActions) -> Self {
        self.actions = Some(actions);
        self
    }
}

impl Default for Attachment {
    fn default() -> Self {
        Self::new()
    }
}

impl Sizable for Attachment {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl Styled for Attachment {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl Attachment {
    /// The retry control the slots may render: only while failed, and only
    /// with an identity to key its state on.
    fn retry_control(&self) -> Option<Control> {
        if !self.status.is_failed() {
            return None;
        }
        Some((self.id.clone()?, self.on_retry.clone()?))
    }

    fn layout_slots(&mut self) {
        let layout = SlotLayout {
            size: self.size,
            status: self.status,
            axis: self.axis,
            // A vertical card without content is an image tile: the media
            // fills the card flush with its border.
            flush: self.axis == Axis::Vertical && self.content.is_none(),
            retry: self.retry_control(),
            // Progress is only meaningful while uploading; processing is
            // indeterminate.
            progress: self.progress.filter(|_| self.status.is_uploading()),
            id: self.id.clone(),
        };

        self.media = self.media.take().map(|media| media.layout(layout.clone()));
        self.content = self
            .content
            .take()
            .map(|content| content.layout(layout.clone()));
        self.actions = self
            .actions
            .take()
            .map(|actions| actions.layout_for_axis(layout.axis));
    }
}

impl RenderOnce for Attachment {
    fn render(mut self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let tokens = cx.theme().semantic_tokens();
        let size = self.size;
        let axis = self.axis;
        let status = self.status;
        let has_media = self.media.is_some();
        let has_content = self.content.is_some();
        let clickable = self.id.is_some() && self.on_click.is_some();
        let remove = self.id.clone().zip(self.on_remove.take());
        let tooltip = self.id.clone().zip(self.tooltip.take());
        let progress_bar = self
            .progress
            .filter(|_| status.is_uploading() && axis == Axis::Horizontal);
        let metrics = card_metrics(size);
        let radius = card_radius(size, cx);
        let flush = axis == Axis::Vertical && !has_content;

        self.layout_slots();

        let card = div()
            .relative()
            .flex()
            .flex_none()
            .max_w_full()
            .min_w_0()
            .rounded(radius)
            .border_1()
            .border_color(if status.is_failed() {
                tokens.colors.destructive
            } else {
                tokens.colors.border
            })
            .when(status.is_pending(), |this| this.border_dashed())
            .bg(tokens.colors.background)
            .text_color(tokens.colors.foreground)
            // Register `hover` unconditionally: a conditionally registered
            // hover style stays cached when the condition later flips off.
            .hover(move |style| {
                if clickable {
                    style.bg(tokens.colors.muted.opacity(0.5))
                } else {
                    style
                }
            })
            .line_height(relative(1.25))
            .text_size(metrics.text)
            .map(|this| match axis {
                // A chip: fixed height, fixed width once it carries content, the
                // media slot flush to the leading padding.
                Axis::Horizontal => this
                    .items_center()
                    .h(metrics.height)
                    .gap(metrics.gap)
                    .pl(metrics.padding_start)
                    .pr(metrics.padding_end)
                    .when(has_content, |this| this.w(metrics.chip_width))
                    .when(!has_content && !has_media, |this| {
                        this.pl(metrics.padding_end)
                    }),
                // An image tile: a square the media fills edge to edge.
                Axis::Vertical if flush => this.size(metrics.height),
                // A preview card: media above the metadata.
                Axis::Vertical => this
                    .w(rems(7.5))
                    .flex_col()
                    .items_start()
                    .gap(metrics.gap)
                    .p(metrics.card_padding),
            })
            .when_some(self.media, |this, media| this.child(media))
            .when_some(self.content, |this, content| this.child(content))
            // A thin bar along the bottom edge tracks the upload, hugging the
            // card's rounded corners.
            .when_some(progress_bar, |this, percent| {
                this.child(upload_bar(percent, radius, tokens.colors.primary))
            })
            .when_some(self.id.zip(self.on_click), |this, (id, on_click)| {
                // The click layer is painted before the actions slot, so the
                // actions' hitboxes stay on top and their buttons keep working.
                this.child(
                    div()
                        .id(id)
                        .absolute()
                        .inset_0()
                        .on_click(move |event, window, cx| on_click(event, window, cx)),
                )
            })
            .when_some(self.actions, |this, actions| this.child(actions))
            .refine_style(&self.style);
        let card = match tooltip {
            Some((id, text)) => card
                .id((id, "card"))
                .tooltip(move |window, cx| Tooltip::new(text.clone()).build(window, cx))
                .into_any_element(),
            None => card.into_any_element(),
        };

        let Some((id, on_remove)) = remove else {
            return card;
        };
        // The remove control rides outside the card, so the card gets a
        // hover group and room for the overhang.
        div()
            .relative()
            .flex_none()
            .max_w_full()
            .min_w_0()
            .group(REMOVE_GROUP)
            .pt(REMOVE_OVERHANG)
            .pr(REMOVE_OVERHANG)
            .child(card)
            .child(
                div()
                    .absolute()
                    .top_0()
                    .right_0()
                    .when(!is_mobile(), |this| {
                        this.invisible()
                            .group_hover(REMOVE_GROUP, |this| this.visible())
                    })
                    .child(remove_button(id, on_remove, cx)),
            )
            .into_any_element()
    }
}

/// The upload bar's thickness.
const UPLOAD_BAR_THICKNESS: f32 = 2.;
/// The card's border width; the padding box's corners are this much tighter.
const CARD_BORDER: f32 = 1.;

/// The upload bar along a card's bottom edge. gpui clips rectangularly, so a
/// plain rectangle could not follow the corner curve; the bar is a filled path
/// whose ends trace the inner corner arcs, as CSS `overflow: hidden` would.
fn upload_bar(percent: f32, radius: Pixels, color: Hsla) -> impl IntoElement {
    canvas(
        |_: Bounds<Pixels>, _: &mut Window, _: &mut App| (),
        move |bounds: Bounds<Pixels>, _: (), window: &mut Window, _: &mut App| {
            if let Some(path) = upload_bar_path(bounds, percent, radius) {
                window.paint_path(path, color);
            }
        },
    )
    .absolute()
    .inset_0()
}

/// The bar as the intersection of its rectangle with the card's inner rounded
/// rectangle: both ends are sampled along the corner arcs. An absolutely
/// positioned child is laid out in the card's padding box, so `bounds` already
/// sits inside the border; only the corner radius shrinks by the border width.
fn upload_bar_path(bounds: Bounds<Pixels>, percent: f32, radius: Pixels) -> Option<Path<Pixels>> {
    const STEPS: usize = 6;
    let width = bounds.size.width.as_f32();
    let height = bounds.size.height.as_f32();
    let radius = (radius.as_f32() - CARD_BORDER).clamp(0., width.min(height) / 2.);
    let inner_left = 0.;
    let inner_right = width;
    let inner_bottom = height;
    let top = inner_bottom - UPLOAD_BAR_THICKNESS;
    let end = inner_left + (inner_right - inner_left) * (percent / 100.).clamp(0., 1.);
    if end <= inner_left || top <= 0. {
        return None;
    }
    // The corner circles' centre line; rows below it lie in the arcs.
    let centre_y = inner_bottom - radius;
    let arc_dx = |y: f32| {
        if radius > 0. && y > centre_y {
            (radius * radius - (y - centre_y) * (y - centre_y))
                .max(0.)
                .sqrt()
        } else {
            radius
        }
    };
    let left_at = |y: f32| inner_left + radius - arc_dx(y);
    let right_at = |y: f32| (inner_right - radius + arc_dx(y)).min(end);
    let at = |x: f32, y: f32| point(bounds.origin.x + px(x), bounds.origin.y + px(y));
    let rows = (0..=STEPS).map(|i| top + UPLOAD_BAR_THICKNESS * i as f32 / STEPS as f32);

    let mut builder = PathBuilder::fill();
    builder.move_to(at(left_at(top), top));
    // Down the right end, then back up the left arc.
    for y in rows.clone() {
        builder.line_to(at(right_at(y), y));
    }
    for y in rows.rev() {
        builder.line_to(at(left_at(y), y));
    }
    builder.build().ok()
}

/// The corner remove control: a surface-colored disc with a hairline border
/// and the foreground glyph, the way a card's close control usually looks.
///
/// The glyphs go in as children: an icon-only `Button` scales its icon with
/// the button, and this disc wants a glyph much smaller than that.
fn remove_button(id: ElementId, on_remove: ControlHandler, cx: &App) -> Button {
    let tokens = cx.theme().semantic_tokens();
    Button::new((id, "remove"))
        // The custom variant thins its color to 20%; the disc must stay
        // opaque, so the surface is set on the instance instead.
        .custom(
            ButtonCustomVariant::new(cx)
                .hover(tokens.colors.muted)
                .active(tokens.colors.muted)
                .foreground(tokens.colors.foreground),
        )
        .accessibility_label(t!("Attachment.Remove"))
        .child(
            Icon::new(IconName::Close)
                .size(px(10.))
                .text_color(tokens.colors.foreground),
        )
        .size(REMOVE_BUTTON_SIZE)
        .p_0()
        .rounded(cx.theme().radius_full())
        .bg(tokens.colors.background)
        .border_1()
        .border_color(tokens.colors.border)
        .shadow_sm()
        .on_click(move |event, window, cx| on_remove(event, window, cx))
}

/// The retry control over a failed image preview: a surface-colored disc
/// with the destructive refresh glyph.
fn retry_button(id: ElementId, on_retry: ControlHandler, cx: &App) -> Button {
    let tokens = cx.theme().semantic_tokens();
    Button::new((id, "retry"))
        .ghost()
        .accessibility_label(t!("Attachment.Retry"))
        .child(
            Icon::new(IconName::RefreshCw)
                .size(px(12.))
                .text_color(tokens.colors.destructive),
        )
        .size(RETRY_BUTTON_SIZE)
        .p_0()
        .rounded(cx.theme().radius_full())
        .bg(tokens.colors.background)
        .shadow_sm()
        .on_click(move |event, window, cx| on_retry(event, window, cx))
}

/// The media slot for an attachment.
///
/// Add an icon or another element as a child for an icon-style preview. Use
/// [`Self::src`] when the attachment has an image preview.
#[derive(IntoElement)]
pub struct AttachmentMedia {
    style: StyleRefinement,
    size: Option<Size>,
    status: AttachmentStatus,
    axis: Axis,
    /// Whether the media fills a vertical card flush with its border.
    flush: bool,
    retry: Option<Control>,
    /// Upload progress in percent, while uploading.
    progress: Option<f32>,
    /// The attachment's identity, keying the progress ring's state.
    id: Option<ElementId>,
    source: Option<ImageSource>,
    children: Vec<AnyElement>,
    overlays: Vec<AnyElement>,
}

impl AttachmentMedia {
    /// Create an empty media slot.
    pub fn new() -> Self {
        Self {
            style: StyleRefinement::default(),
            size: None,
            status: AttachmentStatus::Complete,
            axis: Axis::Horizontal,
            flush: false,
            retry: None,
            progress: None,
            id: None,
            source: None,
            children: Vec::new(),
            overlays: Vec::new(),
        }
    }

    /// Set an image preview source.
    pub fn src(mut self, source: impl Into<ImageSource>) -> Self {
        self.source = Some(source.into());
        self
    }

    /// Add centered content above the preview and above the status treatment.
    pub fn overlay(mut self, overlay: impl IntoElement) -> Self {
        self.overlays.push(
            div()
                .absolute()
                .inset_0()
                .flex()
                .items_center()
                .justify_center()
                .child(overlay)
                .into_any_element(),
        );
        self
    }

    fn layout(mut self, layout: SlotLayout) -> Self {
        if self.size.is_none() {
            self.size = Some(layout.size);
        }
        self.status = layout.status;
        self.axis = layout.axis;
        self.flush = layout.flush;
        self.retry = layout.retry;
        self.progress = layout.progress;
        self.id = layout.id;
        self
    }
}

impl Default for AttachmentMedia {
    fn default() -> Self {
        Self::new()
    }
}

impl ParentElement for AttachmentMedia {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Sizable for AttachmentMedia {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = Some(size.into());
        self
    }
}

impl Styled for AttachmentMedia {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for AttachmentMedia {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let tokens = cx.theme().semantic_tokens();
        let resolved_size = self.size.unwrap_or_default();
        let metrics = card_metrics(resolved_size);
        // Flush media sits inside the card's 1px border, so its corners are
        // one border width tighter than the card's to stay concentric.
        let radius = if self.flush {
            (card_radius(resolved_size, cx) - px(1.)).max(px(0.))
        } else if resolved_size == Size::XSmall {
            tokens.radius.sm
        } else {
            tokens.radius.md
        };
        let glyph_size = metrics.media_glyph;
        let spinner_size = if resolved_size == Size::XSmall {
            Size::XSmall
        } else {
            Size::Small
        };
        let ring_size = if resolved_size == Size::XSmall {
            px(14.)
        } else {
            px(20.)
        };
        let status = self.status;
        let source = self.source;
        let has_source = source.is_some();
        let failed_media = status.is_failed() && !has_source;
        let corner_radii = self.style.corner_radii.clone();
        let ring_id: ElementId = match self.id {
            Some(id) => (id, "progress").into(),
            None => "attachment-progress".into(),
        };
        // In progress: a determinate ring while uploading with a known
        // percentage, a spinner otherwise.
        let busy = |color: Hsla| -> AnyElement {
            match self.progress {
                Some(percent) => ProgressCircle::new(ring_id.clone())
                    .value(percent)
                    .color(color)
                    .size(ring_size)
                    .into_any_element(),
                None => Spinner::new()
                    .with_size(spinner_size)
                    .color(color)
                    .into_any_element(),
            }
        };
        // An icon slot shows the status itself; children come back with
        // `Complete`.
        let glyph = if has_source {
            None
        } else if status.is_in_progress() {
            Some(busy(tokens.colors.primary))
        } else if status.is_failed() {
            Some(match self.retry.clone() {
                Some((id, on_retry)) => retry_button(id, on_retry, cx).into_any_element(),
                None => Icon::new(IconName::Ban).size(glyph_size).into_any_element(),
            })
        } else {
            None
        };
        // An image keeps its colors and takes a scrim instead, so the white
        // control on top stays legible on any picture.
        let scrim = if !has_source {
            None
        } else if status.is_in_progress() {
            Some((PROGRESS_SCRIM, busy(white())))
        } else if status.is_failed() {
            let control = match self.retry {
                Some((id, on_retry)) => retry_button(id, on_retry, cx).into_any_element(),
                None => Icon::new(IconName::Ban)
                    .size(glyph_size)
                    .text_color(white())
                    .into_any_element(),
            };
            Some((FAILED_SCRIM, control))
        } else {
            None
        };

        div()
            .relative()
            .flex()
            .flex_shrink_0()
            .items_center()
            .justify_center()
            .overflow_hidden()
            .when(self.axis == Axis::Horizontal, |this| {
                this.size(metrics.media)
            })
            // An icon child without its own size follows the slot's text size.
            .text_size(glyph_size)
            .when(self.axis == Axis::Vertical, |this| {
                this.w_full().aspect_ratio(1.)
            })
            .rounded(radius)
            .bg(if failed_media {
                tokens.colors.destructive.opacity(0.1)
            } else {
                tokens.colors.muted
            })
            .text_color(if failed_media {
                tokens.colors.destructive
            } else {
                tokens.colors.foreground
            })
            .when_some(source, |this, source| {
                // gpui clips rectangularly, so the slot's `overflow_hidden` cannot
                // round the image: it carries the slot's radius itself, including
                // a caller's `.rounded()` refinement.
                let mut image = img(source)
                    .absolute()
                    .inset_0()
                    .size_full()
                    .rounded(radius)
                    .object_fit(ObjectFit::Cover);
                image.style().corner_radii.refine(&corner_radii);
                this.child(image)
            })
            .map(|this| match glyph {
                Some(glyph) => this.child(glyph),
                None => this.children(self.children),
            })
            .when_some(scrim, |this, (opacity, control)| {
                // The scrim is clipped rectangularly like the image, so it
                // rounds itself the same way, refinement included.
                let mut scrim = div()
                    .absolute()
                    .inset_0()
                    .flex()
                    .items_center()
                    .justify_center()
                    .rounded(radius)
                    .bg(black().opacity(opacity))
                    .child(control);
                scrim.style().corner_radii.refine(&corner_radii);
                this.child(scrim)
            })
            .children(self.overlays)
            .refine_style(&self.style)
    }
}

/// The metadata slot for an attachment.
#[derive(IntoElement)]
pub struct AttachmentContent {
    style: StyleRefinement,
    vertical_layout: bool,
    status: AttachmentStatus,
    retry: Option<Control>,
    progress: Option<f32>,
    children: Vec<AttachmentContentChild>,
}

enum AttachmentContentChild {
    Title(AttachmentTitle),
    Description(AttachmentDescription),
    Element(AnyElement),
}

impl AttachmentContent {
    /// Create an empty metadata slot.
    pub fn new() -> Self {
        Self {
            style: StyleRefinement::default(),
            vertical_layout: false,
            status: AttachmentStatus::Complete,
            retry: None,
            progress: None,
            children: Vec::new(),
        }
    }

    /// Add a status-aware single-line title.
    pub fn title(mut self, title: AttachmentTitle) -> Self {
        self.children.push(AttachmentContentChild::Title(title));
        self
    }

    /// Add a status-aware single-line description.
    pub fn description(mut self, description: AttachmentDescription) -> Self {
        self.children
            .push(AttachmentContentChild::Description(description));
        self
    }

    fn layout(mut self, layout: SlotLayout) -> Self {
        let SlotLayout {
            size,
            status,
            axis,
            retry,
            progress,
            ..
        } = layout;
        self.vertical_layout = axis == Axis::Vertical;
        self.status = status;
        self.retry = retry;
        self.progress = progress;

        for child in &mut self.children {
            match child {
                AttachmentContentChild::Title(title) => {
                    if title.status.is_none() {
                        title.status = Some(status);
                    }
                }
                AttachmentContentChild::Description(description) => {
                    if description.status.is_none() {
                        description.status = Some(status);
                    }
                    if description.size.is_none() {
                        description.size = Some(size);
                    }
                }
                AttachmentContentChild::Element(_) => {}
            }
        }

        self
    }
}

impl Default for AttachmentContent {
    fn default() -> Self {
        Self::new()
    }
}

impl ParentElement for AttachmentContent {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children
            .extend(elements.into_iter().map(AttachmentContentChild::Element));
    }
}

impl Styled for AttachmentContent {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for AttachmentContent {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let tokens = cx.theme().semantic_tokens();
        // The retry link follows the first typed description while failed;
        // the percentage joins it while uploading.
        let mut retry = self.retry.filter(|_| self.status.is_failed());
        let progress = self.progress.filter(|_| self.status.is_uploading());
        v_flex()
            .max_w_full()
            .min_w_0()
            .flex_1()
            .gap_0p5()
            .line_height(relative(1.25))
            .when(self.vertical_layout, |this| this.w_full().px_1())
            .children(self.children.into_iter().map(|child| {
                match child {
                    AttachmentContentChild::Title(title) => title.into_any_element(),
                    AttachmentContentChild::Description(mut description) => match retry.take() {
                        Some((id, on_retry)) => h_flex()
                            .max_w_full()
                            .min_w_0()
                            .gap_1()
                            .child(description)
                            .child(
                                div()
                                    .text_xs()
                                    .text_color(tokens.colors.muted_foreground)
                                    .child("·"),
                            )
                            .child(
                                Button::new((id, "retry"))
                                    .link()
                                    .xsmall()
                                    .label(t!("Attachment.Retry"))
                                    .on_click(move |event, window, cx| on_retry(event, window, cx)),
                            )
                            .into_any_element(),
                        None => {
                            if let Some(percent) = progress {
                                description.text =
                                    format!("{} · {}%", description.text, percent.round() as u32)
                                        .into();
                            }
                            description.into_any_element()
                        }
                    },
                    AttachmentContentChild::Element(element) => element,
                }
            }))
            .refine_style(&self.style)
    }
}

/// A single-line attachment title.
#[derive(IntoElement)]
pub struct AttachmentTitle {
    style: StyleRefinement,
    text: SharedString,
    status: Option<AttachmentStatus>,
    shimmer_style: Option<ShimmerStyle>,
}

impl AttachmentTitle {
    /// Create an attachment title.
    pub fn new(text: impl Into<SharedString>) -> Self {
        Self {
            style: StyleRefinement::default(),
            text: text.into(),
            status: None,
            shimmer_style: None,
        }
    }

    /// Override the attachment lifecycle status used for the loading shimmer.
    pub fn status(mut self, status: AttachmentStatus) -> Self {
        self.status = Some(status);
        self
    }

    /// Customize the shimmer used while this attachment is uploading or processing.
    pub fn with_shimmer_style(mut self, style: ShimmerStyle) -> Self {
        self.shimmer_style = Some(style);
        self
    }
}

impl Styled for AttachmentTitle {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for AttachmentTitle {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        let loading = self.status.is_some_and(AttachmentStatus::is_in_progress);

        div()
            .max_w_full()
            .min_w_0()
            .truncate()
            .font_medium()
            .map(|this| {
                if loading {
                    this.child(
                        ShimmerText::new(self.text).when_some(self.shimmer_style, |this, style| {
                            this.with_shimmer_style(style)
                        }),
                    )
                } else {
                    this.child(self.text)
                }
            })
            .refine_style(&self.style)
    }
}

/// A single-line attachment description or status message.
#[derive(IntoElement)]
pub struct AttachmentDescription {
    style: StyleRefinement,
    text: SharedString,
    status: Option<AttachmentStatus>,
    /// The card size whose type scale the description follows.
    size: Option<Size>,
}

impl AttachmentDescription {
    /// Create an attachment description.
    pub fn new(text: impl Into<SharedString>) -> Self {
        Self {
            style: StyleRefinement::default(),
            text: text.into(),
            status: None,
            size: None,
        }
    }

    /// Set the status used for the semantic description color.
    pub fn status(mut self, status: AttachmentStatus) -> Self {
        self.status = Some(status);
        self
    }
}

impl Styled for AttachmentDescription {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for AttachmentDescription {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let tokens = cx.theme().semantic_tokens();
        let color = self
            .status
            .is_some_and(AttachmentStatus::is_failed)
            .then_some(tokens.colors.destructive)
            .unwrap_or(tokens.colors.muted_foreground);

        div()
            .max_w_full()
            .min_w_0()
            .truncate()
            .text_size(card_metrics(self.size.unwrap_or_default()).description)
            .line_height(relative(1.25))
            .text_color(color)
            .child(self.text)
            .refine_style(&self.style)
    }
}

/// A composition slot for attachment actions.
///
/// Add existing [`crate::button::Button`] or other controls as children. A
/// separate attachment-specific action wrapper is intentionally unnecessary.
#[derive(IntoElement)]
pub struct AttachmentActions {
    style: StyleRefinement,
    vertical_layout: bool,
    children: Vec<AnyElement>,
}

impl AttachmentActions {
    /// Create an empty actions slot.
    pub fn new() -> Self {
        Self {
            style: StyleRefinement::default(),
            vertical_layout: false,
            children: Vec::new(),
        }
    }

    fn layout_for_axis(mut self, axis: Axis) -> Self {
        self.vertical_layout = axis == Axis::Vertical;
        self
    }
}

impl Default for AttachmentActions {
    fn default() -> Self {
        Self::new()
    }
}

impl ParentElement for AttachmentActions {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Styled for AttachmentActions {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for AttachmentActions {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        div()
            .relative()
            .flex()
            .flex_shrink_0()
            .items_center()
            .gap_1()
            .when(self.vertical_layout, |this| {
                this.absolute().top_3().right_3()
            })
            // The actions cluster owns its presses: an action (or the gap
            // between actions) must not also arm the whole-card click layer
            // below, mirroring the shadcn stacking where actions sit above
            // the trigger. Buttons run first in the bubble phase, so they
            // are unaffected.
            .on_mouse_down(MouseButton::Left, |_, _, cx| cx.stop_propagation())
            .children(self.children)
            .refine_style(&self.style)
    }
}

/// How long an edge fade takes to appear or disappear.
const EDGE_FADE_TRANSITION: Duration = Duration::from_millis(200);

/// The scroll state a group keeps for itself when the caller passes none.
struct AttachmentGroupScroll {
    handle: ScrollHandle,
    /// Whether the frame after the first layout has been requested: the
    /// scroll extent is unknown until then, so the fades need one more pass.
    primed: bool,
}

/// A horizontally scrollable row of attachments.
#[derive(IntoElement)]
pub struct AttachmentGroup {
    id: ElementId,
    style: StyleRefinement,
    scroll_handle: Option<ScrollHandle>,
    edge_fade: Option<Hsla>,
    children: Vec<AnyElement>,
}

impl AttachmentGroup {
    /// Create an empty attachment group with a stable scroll identifier.
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            id: id.into(),
            style: StyleRefinement::default(),
            scroll_handle: None,
            edge_fade: None,
            children: Vec::new(),
        }
    }

    /// Scroll the row through the caller's handle.
    ///
    /// The group keeps its own scroll state otherwise. Pass a handle when the
    /// application moves the row itself, for example from paging buttons.
    pub fn track_scroll(mut self, handle: &ScrollHandle) -> Self {
        self.scroll_handle = Some(handle.clone());
        self
    }

    /// Fade the row's edges into `color` while attachments continue past them.
    ///
    /// Pass the color of the surface behind the row. Each fade shows only while
    /// its edge still hides content, so a row that fits shows none; the fades
    /// sit above the attachments and do not take pointer events.
    pub fn with_edge_fade(mut self, color: impl Into<Hsla>) -> Self {
        self.edge_fade = Some(color.into());
        self
    }
}

impl ParentElement for AttachmentGroup {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Styled for AttachmentGroup {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for AttachmentGroup {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let id = self.id;
        // Element-local state keyed on the id: the fades read the offset across
        // frames, and the first layout must be followed by one more render
        // before the scroll extent is known.
        let scroll =
            window.use_keyed_state((id.clone(), "scroll"), cx, |_, _| AttachmentGroupScroll {
                handle: ScrollHandle::new(),
                primed: false,
            });
        let handle = self
            .scroll_handle
            .unwrap_or_else(|| scroll.read(cx).handle.clone());
        let view_id = window.current_view();

        let fades = self.edge_fade.map(|color| {
            if !scroll.read(cx).primed {
                scroll.update(cx, |scroll, _| scroll.primed = true);
                window.on_next_frame(move |_, cx| cx.notify(view_id));
            }
            let max = handle.max_offset().x;
            // Scrolling right makes the offset negative.
            let offset = handle.offset().x;
            let scrollable = max > px(1.);
            let hides_leading = scrollable && offset < px(-1.);
            let hides_trailing = scrollable && offset > px(1.) - max;
            let leading = transition(
                (id.clone(), "leading-fade"),
                if hides_leading { 1. } else { 0. },
                Transition::new(EDGE_FADE_TRANSITION),
                window,
                cx,
            );
            let trailing = transition(
                (id.clone(), "trailing-fade"),
                if hides_trailing { 1. } else { 0. },
                Transition::new(EDGE_FADE_TRANSITION),
                window,
                cx,
            );
            (color, leading, trailing)
        });

        let row = h_flex()
            .id(id)
            .w_full()
            .min_w_0()
            .gap_3()
            .py_1()
            .overflow_x_scroll()
            .lock_scroll_axis()
            .track_scroll(&handle)
            // Scrolling only moves the offset; the fades need a render to follow.
            .when(fades.is_some(), |this| {
                this.on_scroll(move |_, _, cx| cx.notify(view_id))
            })
            .refine_style(&self.style)
            .children(self.children);

        // Gradient angle: 0 points up and increases clockwise, so 90 runs from
        // the leading edge to the trailing edge.
        let fade = |color: Hsla, opacity: f32, leading: bool| {
            let (from, to) = if leading {
                (color, color.opacity(0.))
            } else {
                (color.opacity(0.), color)
            };
            div()
                .absolute()
                .top_0()
                .bottom_0()
                .when(leading, |this| this.left_0())
                .when(!leading, |this| this.right_0())
                .w(rems(1.5))
                .opacity(opacity)
                .bg(linear_gradient(
                    90.,
                    linear_color_stop(from, 0.),
                    linear_color_stop(to, 1.),
                ))
        };

        div()
            .relative()
            .w_full()
            .min_w_0()
            .child(row)
            .child(ScrollableMask::vertical_wheel(&handle))
            .when_some(fades, |this, (color, leading, trailing)| {
                this.when(leading > 0., |this| this.child(fade(color, leading, true)))
                    .when(trailing > 0., |this| {
                        this.child(fade(color, trailing, false))
                    })
            })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_attachment_builder() {
        let mut attachment = Attachment::new()
            .status(AttachmentStatus::Uploading)
            .axis(Axis::Vertical)
            .with_size(Size::Small)
            .media(AttachmentMedia::new().src("preview.png"))
            .content(
                AttachmentContent::new()
                    .title(AttachmentTitle::new("report.pdf"))
                    .description(AttachmentDescription::new("Uploading")),
            )
            .actions(AttachmentActions::new().child("Cancel"));

        assert_eq!(attachment.status, AttachmentStatus::Uploading);
        assert_eq!(attachment.axis, Axis::Vertical);
        assert_eq!(attachment.size, Size::Small);
        assert!(attachment.media.is_some());
        assert!(attachment.content.is_some());
        assert!(attachment.actions.is_some());

        attachment.layout_slots();
        assert_eq!(attachment.media.as_ref().unwrap().size, Some(Size::Small));
        assert_eq!(
            attachment.media.as_ref().unwrap().status,
            AttachmentStatus::Uploading
        );
        assert!(attachment.content.as_ref().unwrap().vertical_layout);
        assert!(attachment.actions.as_ref().unwrap().vertical_layout);

        let handle = ScrollHandle::new();
        let group = AttachmentGroup::new("group")
            .track_scroll(&handle)
            .with_edge_fade(gpui::black())
            .child("first")
            .child("second");
        assert!(group.scroll_handle.is_some());
        assert_eq!(group.edge_fade, Some(gpui::black()));
        assert_eq!(group.children.len(), 2);
        assert!(AttachmentGroup::new("plain").scroll_handle.is_none());
        assert!(AttachmentGroup::new("plain").edge_fade.is_none());
    }

    #[test]
    fn test_attachment_whole_card_click_builder() {
        assert!(Attachment::new().id.is_none());
        assert!(Attachment::new().on_click.is_none());

        let clickable = Attachment::new()
            .id("report-attachment")
            .on_click(|_, _, _| {});
        assert_eq!(clickable.id, Some("report-attachment".into()));
        assert!(clickable.on_click.is_some());
    }

    #[test]
    fn test_attachment_corner_controls_builder() {
        assert!(Attachment::new().on_remove.is_none());
        assert!(Attachment::new().on_retry.is_none());

        let attachment = Attachment::new()
            .id("upload")
            .on_remove(|_, _, _| {})
            .on_retry(|_, _, _| {});
        assert!(attachment.on_remove.is_some());
        assert!(attachment.on_retry.is_some());
    }

    #[test]
    fn test_attachment_retry_control_reaches_slots_only_while_failed() {
        let mut failed = Attachment::new()
            .id("upload")
            .status(AttachmentStatus::Failed)
            .on_retry(|_, _, _| {})
            .media(AttachmentMedia::new().src("preview.png"))
            .content(AttachmentContent::new().description(AttachmentDescription::new("Failed")));
        failed.layout_slots();
        assert!(failed.media.as_ref().unwrap().retry.is_some());
        assert!(failed.content.as_ref().unwrap().retry.is_some());

        // A completed attachment offers no retry, and one without an identity
        // has nothing to key the control on.
        let mut complete = Attachment::new()
            .id("upload")
            .on_retry(|_, _, _| {})
            .media(AttachmentMedia::new().src("preview.png"));
        complete.layout_slots();
        assert!(complete.media.as_ref().unwrap().retry.is_none());

        let mut anonymous = Attachment::new()
            .status(AttachmentStatus::Failed)
            .on_retry(|_, _, _| {})
            .media(AttachmentMedia::new().src("preview.png"));
        anonymous.layout_slots();
        assert!(anonymous.media.as_ref().unwrap().retry.is_none());
    }

    #[test]
    fn test_attachment_progress_and_tooltip_builder() {
        assert!(Attachment::new().progress.is_none());
        assert!(Attachment::new().tooltip.is_none());
        assert_eq!(Attachment::new().progress(130.).progress, Some(100.));
        assert_eq!(Attachment::new().progress(-5.).progress, Some(0.));
        assert_eq!(
            Attachment::new().tooltip("Network error").tooltip,
            Some("Network error".into())
        );

        // Progress reaches the slots only while uploading.
        let mut uploading = Attachment::new()
            .id("upload")
            .status(AttachmentStatus::Uploading)
            .progress(62.)
            .media(AttachmentMedia::new().src("preview.png"))
            .content(AttachmentContent::new().description(AttachmentDescription::new("Uploading")));
        uploading.layout_slots();
        assert_eq!(uploading.media.as_ref().unwrap().progress, Some(62.));
        assert_eq!(uploading.content.as_ref().unwrap().progress, Some(62.));

        let mut processing = Attachment::new()
            .status(AttachmentStatus::Processing)
            .progress(62.)
            .media(AttachmentMedia::new().src("preview.png"));
        processing.layout_slots();
        assert!(processing.media.as_ref().unwrap().progress.is_none());
    }

    #[test]
    fn test_attachment_image_tile_media_is_flush() {
        let mut tile = Attachment::new()
            .axis(Axis::Vertical)
            .media(AttachmentMedia::new().src("preview.png"));
        tile.layout_slots();
        assert!(tile.media.as_ref().unwrap().flush);

        let mut card = Attachment::new()
            .axis(Axis::Vertical)
            .media(AttachmentMedia::new().src("preview.png"))
            .content(AttachmentContent::new().title(AttachmentTitle::new("preview.png")));
        card.layout_slots();
        assert!(!card.media.as_ref().unwrap().flush);
    }

    #[test]
    fn test_attachment_defaults_and_status_helpers() {
        assert_eq!(Attachment::new().status, AttachmentStatus::Complete);
        assert_eq!(AttachmentStatus::default(), AttachmentStatus::Complete);
        assert!(AttachmentStatus::Pending.is_pending());
        assert!(AttachmentStatus::Uploading.is_in_progress());
        assert!(AttachmentStatus::Processing.is_processing());
        assert!(AttachmentStatus::Failed.is_failed());
        assert!(AttachmentStatus::Complete.is_complete());
        assert!(!AttachmentStatus::Complete.is_in_progress());
    }

    #[test]
    fn test_attachment_slots_are_composable() {
        let media = AttachmentMedia::new().child("icon");
        assert_eq!(media.children.len(), 1);

        let content = AttachmentContent::new()
            .title(AttachmentTitle::new("name"))
            .description(AttachmentDescription::new("Details"))
            .child("Custom progress");
        assert_eq!(content.children.len(), 3);
        assert!(matches!(
            content.children[0],
            AttachmentContentChild::Title(_)
        ));
        assert!(matches!(
            content.children[1],
            AttachmentContentChild::Description(_)
        ));
        assert!(matches!(
            content.children[2],
            AttachmentContentChild::Element(_)
        ));

        let legacy = AttachmentContent::new().child(AttachmentTitle::new("legacy"));
        assert!(matches!(
            legacy.children[0],
            AttachmentContentChild::Element(_)
        ));

        let actions = AttachmentActions::new().child("remove");
        assert_eq!(actions.children.len(), 1);
    }

    #[test]
    fn test_attachment_typed_content_inherits_status() {
        let mut attachment = Attachment::new()
            .status(AttachmentStatus::Uploading)
            .content(
                AttachmentContent::new()
                    .title(AttachmentTitle::new("report.pdf"))
                    .description(AttachmentDescription::new("Uploading")),
            );

        attachment.layout_slots();

        let content = attachment.content.unwrap();
        let AttachmentContentChild::Title(title) = &content.children[0] else {
            panic!("expected the typed title slot");
        };
        assert_eq!(title.status, Some(AttachmentStatus::Uploading));

        let AttachmentContentChild::Description(description) = &content.children[1] else {
            panic!("expected the typed description slot");
        };
        assert_eq!(description.status, Some(AttachmentStatus::Uploading));
    }

    #[test]
    fn test_attachment_explicit_child_status_overrides_parent() {
        let mut attachment = Attachment::new().status(AttachmentStatus::Failed).content(
            AttachmentContent::new()
                .title(AttachmentTitle::new("report.pdf").status(AttachmentStatus::Processing))
                .description(
                    AttachmentDescription::new("Previous upload completed")
                        .status(AttachmentStatus::Complete),
                ),
        );

        attachment.layout_slots();

        let content = attachment.content.unwrap();
        let AttachmentContentChild::Title(title) = &content.children[0] else {
            panic!("expected the typed title slot");
        };
        assert_eq!(title.status, Some(AttachmentStatus::Processing));

        let AttachmentContentChild::Description(description) = &content.children[1] else {
            panic!("expected the typed description slot");
        };
        assert_eq!(description.status, Some(AttachmentStatus::Complete));
    }

    #[test]
    fn test_attachment_title_keeps_custom_shimmer_style() {
        let mut attachment = Attachment::new()
            .status(AttachmentStatus::Processing)
            .content(
                AttachmentContent::new().title(
                    AttachmentTitle::new("report.pdf")
                        .with_shimmer_style(ShimmerStyle::new().spread(0.45).reverse(true)),
                ),
            );

        attachment.layout_slots();

        let content = attachment.content.unwrap();
        let AttachmentContentChild::Title(title) = &content.children[0] else {
            panic!("expected the typed title slot");
        };
        assert_eq!(title.status, Some(AttachmentStatus::Processing));
        assert!(title.shimmer_style.is_some());
    }

    #[test]
    fn test_attachment_media_preview_keeps_children_and_overlays() {
        let media = AttachmentMedia::new()
            .src("preview.png")
            .child("Existing overlay")
            .overlay("Centered overlay");

        assert!(media.source.is_some());
        assert_eq!(media.children.len(), 1);
        assert_eq!(media.overlays.len(), 1);
    }

    #[test]
    fn test_attachment_media_size_inherits_root_unless_explicit() {
        let slot = |size, status, axis, flush| SlotLayout {
            size,
            status,
            axis,
            flush,
            retry: None,
            progress: None,
            id: None,
        };
        let inherited = AttachmentMedia::new().layout(slot(
            Size::Small,
            AttachmentStatus::Complete,
            Axis::Vertical,
            true,
        ));
        assert_eq!(inherited.size, Some(Size::Small));
        assert_eq!(inherited.axis, Axis::Vertical);
        assert!(inherited.flush);

        let explicit = AttachmentMedia::new().with_size(Size::XSmall).layout(slot(
            Size::Large,
            AttachmentStatus::Failed,
            Axis::Horizontal,
            false,
        ));
        assert_eq!(explicit.size, Some(Size::XSmall));
        assert_eq!(explicit.status, AttachmentStatus::Failed);
    }

    #[test]
    fn test_attachment_group_builder() {
        let group = AttachmentGroup::new("attachments")
            .child("First")
            .child("Second");

        assert_eq!(group.children.len(), 2);
    }

    mod click_dispatch {
        use std::{cell::Cell, rc::Rc};

        use gpui::{Context, Modifiers, Render, TestAppContext, point, px};

        use super::super::*;
        use crate::button::Button;

        struct AttachmentClickHarness {
            card_clicks: Rc<Cell<usize>>,
            action_clicks: Rc<Cell<usize>>,
        }

        impl Render for AttachmentClickHarness {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                let card_clicks = self.card_clicks.clone();
                let action_clicks = self.action_clicks.clone();

                Attachment::new()
                    .id("attachment")
                    .w(px(200.))
                    .h(px(60.))
                    .on_click(move |_, _, _| card_clicks.set(card_clicks.get() + 1))
                    .actions(
                        AttachmentActions::new().child(
                            Button::new("open")
                                .w(px(40.))
                                .h(px(40.))
                                .on_click(move |_, _, _| {
                                    action_clicks.set(action_clicks.get() + 1)
                                }),
                        ),
                    )
            }
        }

        #[gpui::test]
        fn whole_card_click_stays_below_the_actions(cx: &mut TestAppContext) {
            cx.update(crate::init);
            let card_clicks = Rc::new(Cell::new(0));
            let action_clicks = Rc::new(Cell::new(0));
            let (_, cx) = cx.add_window_view({
                let card_clicks = card_clicks.clone();
                let action_clicks = action_clicks.clone();
                move |_, _| AttachmentClickHarness {
                    card_clicks,
                    action_clicks,
                }
            });
            cx.update(|window, cx| window.draw(cx).clear(cx));

            // A click on an action must not also fire the whole-card handler.
            cx.simulate_click(point(px(20.), px(30.)), Modifiers::default());
            assert_eq!(action_clicks.get(), 1);
            assert_eq!(card_clicks.get(), 0);

            // A click elsewhere on the card fires the whole-card handler.
            cx.simulate_click(point(px(150.), px(30.)), Modifiers::default());
            assert_eq!(action_clicks.get(), 1);
            assert_eq!(card_clicks.get(), 1);
        }
    }

    mod retry_dispatch {
        use std::{cell::Cell, rc::Rc};

        use gpui::{
            Context, KeyDownEvent, KeyUpEvent, Keystroke, Modifiers, Render, TestAppContext,
            VisualTestContext, point, px,
        };

        use super::super::*;

        struct FailedMediaHarness {
            retry: bool,
            retries: Rc<Cell<usize>>,
        }

        impl Render for FailedMediaHarness {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                let retries = self.retries.clone();
                Attachment::new()
                    .id("failed-attachment")
                    .status(AttachmentStatus::Failed)
                    .media(AttachmentMedia::new())
                    .when(self.retry, |attachment| {
                        attachment.on_retry(move |_, _, _| retries.set(retries.get() + 1))
                    })
            }
        }

        fn harness(
            cx: &mut TestAppContext,
            retry: bool,
        ) -> (&mut VisualTestContext, Rc<Cell<usize>>) {
            cx.update(crate::init);
            let retries = Rc::new(Cell::new(0));
            let (_, cx) = cx.add_window_view({
                let retries = retries.clone();
                move |_, _| FailedMediaHarness { retry, retries }
            });
            cx.update(|window, cx| window.draw(cx).clear(cx));
            (cx, retries)
        }

        #[gpui::test]
        fn failed_media_without_source_retries_by_pointer_and_keyboard(cx: &mut TestAppContext) {
            let (cx, retries) = harness(cx, true);
            cx.simulate_click(point(px(20.), px(20.)), Modifiers::default());
            assert_eq!(retries.get(), 1);

            cx.update(|window, cx| window.focus_next(cx));
            cx.update(|window, cx| assert!(window.focused(cx).is_some()));
            let keystroke = Keystroke::parse("enter").unwrap();
            cx.simulate_event(KeyDownEvent {
                keystroke: keystroke.clone(),
                is_held: false,
                prefer_character_input: false,
            });
            cx.simulate_event(KeyUpEvent { keystroke });
            assert_eq!(retries.get(), 2);
        }

        #[gpui::test]
        fn failed_media_without_retry_has_no_action(cx: &mut TestAppContext) {
            let (cx, retries) = harness(cx, false);
            cx.simulate_click(point(px(20.), px(20.)), Modifiers::default());
            assert_eq!(retries.get(), 0);
            cx.update(|window, cx| window.focus_next(cx));
            cx.update(|window, cx| assert!(window.focused(cx).is_none()));
        }
    }
}
