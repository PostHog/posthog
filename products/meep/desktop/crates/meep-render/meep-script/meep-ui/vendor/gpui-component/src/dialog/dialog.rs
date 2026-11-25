use super::entrance::{DialogEntrance, EntranceSurface};
use crate::root::WindowState;
use gpui_base::TestSupportExt as _;
use std::{rc::Rc, sync::LazyLock, time::Duration};

use gpui::{
    Action, Anchor, AnyElement, App, BoxShadow, ClickEvent, Edges, FocusHandle, Hsla,
    InteractiveElement, IntoElement, ParentElement, Pixels, RenderOnce, SharedString,
    StyleRefinement, Styled, Window, WindowControlArea, anchored, div, hsla, point,
    prelude::FluentBuilder, px,
};
use gpui_base::{ElementExt as _, TextSelectionScopeId, motion::Transition};
use rust_i18n::t;

use crate::{
    ActiveTheme as _, IconName, Sizable as _, StyledExt, TITLE_BAR_HEIGHT, WindowExt as _,
    animation::cubic_bezier,
    button::{Button, ButtonVariant, ButtonVariants as _},
    dialog::{DialogContent, DialogDispatchAnchor, DialogTitle},
    scroll::ScrollableElement as _,
    v_flex,
};

pub static ANIMATION_DURATION: LazyLock<Duration> = LazyLock::new(|| Duration::from_secs_f64(0.25));
pub use gpui_base::actions::{Cancel, Confirm};

type OkHandler = Rc<dyn Fn(&ClickEvent, &mut Window, &mut App) -> bool + 'static>;
type CancelHandler = Rc<dyn Fn(&ClickEvent, &mut Window, &mut App) -> bool + 'static>;
type CloseHandler = Rc<dyn Fn(&ClickEvent, &mut Window, &mut App) + 'static>;

/// Overwrite `slot` only when `value` was explicitly set.
fn merge_field<T>(slot: &mut Option<T>, value: Option<T>) {
    if value.is_some() {
        *slot = value;
    }
}

/// Dialog button props.
///
/// Every field is unset until a builder sets it, and an unset field falls back
/// to its documented default when the dialog renders. Handing a value to
/// [`Dialog::button_props`] or [`crate::dialog::AlertDialog::button_props`]
/// therefore overrides only the fields that value sets: whatever the dialog
/// already carries — the Cancel button `AlertDialog::confirm` asked for, a
/// callback an earlier `on_ok` installed — survives.
#[derive(Clone, Default)]
pub struct DialogButtonProps {
    pub(crate) ok_text: Option<SharedString>,
    pub(crate) ok_variant: Option<ButtonVariant>,
    pub(crate) cancel_text: Option<SharedString>,
    pub(crate) cancel_variant: Option<ButtonVariant>,
    pub(crate) show_cancel: Option<bool>,
    pub(crate) on_ok: Option<OkHandler>,
    pub(crate) on_cancel: Option<CancelHandler>,
    pub(crate) on_close: Option<CloseHandler>,
}

impl DialogButtonProps {
    /// Sets the text of the OK button. Default is `OK`.
    pub fn ok_text(mut self, ok_text: impl Into<SharedString>) -> Self {
        self.ok_text = Some(ok_text.into());
        self
    }

    /// Sets the variant of the OK button. Default is `ButtonVariant::Primary`.
    pub fn ok_variant(mut self, ok_variant: ButtonVariant) -> Self {
        self.ok_variant = Some(ok_variant);
        self
    }

    /// Sets the text of the Cancel button. Default is `Cancel`.
    pub fn cancel_text(mut self, cancel_text: impl Into<SharedString>) -> Self {
        self.cancel_text = Some(cancel_text.into());
        self
    }

    /// Sets the variant of the Cancel button. Default is `ButtonVariant::default()`.
    pub fn cancel_variant(mut self, cancel_variant: ButtonVariant) -> Self {
        self.cancel_variant = Some(cancel_variant);
        self
    }

    /// Sets whether to show the Cancel button. Default is `false`.
    pub fn show_cancel(mut self, show_cancel: bool) -> Self {
        self.show_cancel = Some(show_cancel);
        self
    }

    /// Sets the callback for when the dialog is has been confirmed.
    ///
    /// The callback should return `true` to close the dialog, if return `false` the dialog will not be closed.
    pub fn on_ok(
        mut self,
        on_ok: impl Fn(&ClickEvent, &mut Window, &mut App) -> bool + 'static,
    ) -> Self {
        self.on_ok = Some(Rc::new(on_ok));
        self
    }

    /// Sets the callback for when the dialog is has been canceled.
    ///
    /// The callback should return `true` to close the dialog, if return `false` the dialog will not be closed.
    pub fn on_cancel(
        mut self,
        on_cancel: impl Fn(&ClickEvent, &mut Window, &mut App) -> bool + 'static,
    ) -> Self {
        self.on_cancel = Some(Rc::new(on_cancel));
        self
    }

    /// Takes over every field `other` sets and keeps the rest.
    pub(crate) fn merge(&mut self, other: Self) {
        merge_field(&mut self.ok_text, other.ok_text);
        merge_field(&mut self.ok_variant, other.ok_variant);
        merge_field(&mut self.cancel_text, other.cancel_text);
        merge_field(&mut self.cancel_variant, other.cancel_variant);
        merge_field(&mut self.show_cancel, other.show_cancel);
        merge_field(&mut self.on_ok, other.on_ok);
        merge_field(&mut self.on_cancel, other.on_cancel);
        merge_field(&mut self.on_close, other.on_close);
    }

    /// Whether the default footer renders a Cancel button. Default is `false`.
    pub(crate) fn is_cancel_shown(&self) -> bool {
        self.show_cancel.unwrap_or(false)
    }

    /// The confirm callback, defaulting to one that closes the dialog.
    pub(crate) fn ok_handler(&self) -> OkHandler {
        self.on_ok
            .clone()
            .unwrap_or_else(|| Rc::new(|_, _, _| true))
    }

    /// The cancel callback, defaulting to one that closes the dialog.
    pub(crate) fn cancel_handler(&self) -> CancelHandler {
        self.on_cancel
            .clone()
            .unwrap_or_else(|| Rc::new(|_, _, _| true))
    }

    /// The close callback, defaulting to one that does nothing.
    pub(crate) fn close_handler(&self) -> CloseHandler {
        self.on_close
            .clone()
            .unwrap_or_else(|| Rc::new(|_, _, _| {}))
    }

    pub(crate) fn render_ok(&self, _: &mut Window, _: &mut App) -> AnyElement {
        let ok_text = self
            .ok_text
            .clone()
            .unwrap_or_else(|| t!("Dialog.ok").into());

        DialogButton {
            anchor_key: "dialog-ok-anchor",
            button: Button::new("ok")
                .label(ok_text)
                .with_variant(self.ok_variant.unwrap_or(ButtonVariant::Primary)),
            action: Rc::new(Confirm { secondary: false }),
        }
        .into_any_element()
    }

    pub(crate) fn render_cancel(&self, _: &mut Window, _: &mut App) -> AnyElement {
        let cancel_text = self
            .cancel_text
            .clone()
            .unwrap_or_else(|| t!("Dialog.cancel").into());

        DialogButton {
            anchor_key: "dialog-cancel-anchor",
            button: Button::new("cancel")
                .label(cancel_text)
                .with_variant(self.cancel_variant.unwrap_or_default()),
            action: Rc::new(Cancel),
        }
        .into_any_element()
    }
}

/// A default dialog button: activating it dispatches `action` on the dialog
/// it sits in, whatever holds focus at that moment.
#[derive(IntoElement)]
struct DialogButton {
    /// Distinct per button: OK and Cancel render as siblings in one scope.
    anchor_key: &'static str,
    button: Button,
    action: Rc<dyn Action>,
}

impl RenderOnce for DialogButton {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let anchor = DialogDispatchAnchor::new(self.anchor_key, window, cx);
        self.button
            .child(anchor.element())
            .on_click(move |_, window, cx| anchor.dispatch(&*self.action, window, cx))
    }
}

type ContentBuilderFn = Rc<dyn Fn(DialogContent, &mut Window, &mut App) -> DialogContent + 'static>;

#[derive(Clone)]
pub(crate) struct DialogProps {
    width: Pixels,
    max_width: Option<Pixels>,
    margin_top: Option<Pixels>,
    centered: bool,
    close_button: bool,

    overlay: bool,
    overlay_closable: bool,
    pub(crate) overlay_visible: bool,
    keyboard: bool,
    entrance: DialogEntrance,
}

impl Default for DialogProps {
    fn default() -> Self {
        Self {
            margin_top: None,
            centered: false,
            width: px(448.),
            max_width: None,
            overlay: true,
            keyboard: true,
            overlay_visible: false,
            close_button: true,
            overlay_closable: true,
            entrance: DialogEntrance::default(),
        }
    }
}

enum BaseDialogRoot {
    Dialog(gpui_base::Dialog),
    AlertDialog(gpui_base::AlertDialog),
}

macro_rules! map_base_root {
    ($self:expr, $method:ident($($arg:expr),* $(,)?)) => {
        match $self {
            BaseDialogRoot::Dialog(root) => BaseDialogRoot::Dialog(root.$method($($arg),*)),
            BaseDialogRoot::AlertDialog(root) => {
                BaseDialogRoot::AlertDialog(root.$method($($arg),*))
            }
        }
    };
}

impl BaseDialogRoot {
    fn layer(self, index: usize, topmost: bool) -> Self {
        map_base_root!(self, layer(index, topmost))
    }
    fn focus_handle(self, focus: FocusHandle) -> Self {
        map_base_root!(self, focus_handle(focus))
    }
    fn close_on_escape(self, value: bool) -> Self {
        map_base_root!(self, close_on_escape(value))
    }
    fn close_on_backdrop_press(self, value: bool) -> Self {
        match self {
            Self::Dialog(root) => Self::Dialog(root.close_on_backdrop_press(value)),
            Self::AlertDialog(root) => Self::AlertDialog(root),
        }
    }
    fn dismiss_below_y(self, value: Pixels) -> Self {
        map_base_root!(self, dismiss_below_y(value))
    }
    fn backdrop(self, element: impl IntoElement) -> Self {
        map_base_root!(self, backdrop(element))
    }
    fn popup(self, element: impl IntoElement) -> Self {
        map_base_root!(self, popup(element))
    }
    fn on_ok(self, handler: impl Fn(&ClickEvent, &mut Window, &mut App) -> bool + 'static) -> Self {
        map_base_root!(self, on_ok(handler))
    }
    fn on_cancel(
        self,
        handler: impl Fn(&ClickEvent, &mut Window, &mut App) -> bool + 'static,
    ) -> Self {
        map_base_root!(self, on_cancel(handler))
    }
    fn on_close(self, handler: impl Fn(&ClickEvent, &mut Window, &mut App) + 'static) -> Self {
        map_base_root!(self, on_close(handler))
    }
    fn request_close(self, handler: impl Fn(bool, &mut Window, &mut App) + 'static) -> Self {
        map_base_root!(self, request_close(handler))
    }
}

impl IntoElement for BaseDialogRoot {
    type Element = <gpui_base::Dialog as IntoElement>::Element;
    fn into_element(self) -> Self::Element {
        match self {
            Self::Dialog(root) => root.into_element(),
            Self::AlertDialog(root) => root.into_element(),
        }
    }
}

/// The shared entrance and exit sample for a mounted dialog.
///
/// Built by the window dialog layer with stable per-dialog identity.
#[derive(Clone, Copy, Debug)]
pub(crate) struct DialogMotion {
    pub(crate) visibility: f32,
    pub(crate) closing: bool,
}

/// A modal to display content in a dialog box.
#[derive(IntoElement)]
pub struct Dialog {
    base: Option<BaseDialogRoot>,
    pub(crate) style: StyleRefinement,
    children: Vec<AnyElement>,
    trigger: Option<AnyElement>,
    title: Option<AnyElement>,
    pub(crate) header: Option<AnyElement>,
    pub(crate) footer: Option<AnyElement>,
    pub(crate) content_builder: Option<ContentBuilderFn>,
    pub(crate) props: DialogProps,

    pub(super) button_props: DialogButtonProps,

    /// This will be change when open the dialog, the focus handle is create when open the dialog.
    pub(crate) focus_handle: FocusHandle,
    pub(crate) layer_ix: usize,
    pub(crate) selection_scope: TextSelectionScopeId,
    pub(crate) motion: Option<DialogMotion>,
    pub(crate) id: usize,
}

pub(crate) fn overlay_color(overlay: bool, cx: &App) -> Hsla {
    if !overlay {
        return hsla(0., 0., 0., 0.);
    }

    cx.theme().overlay
}

fn dialog_shadow(delta: f32) -> Vec<BoxShadow> {
    vec![
        BoxShadow {
            color: hsla(0., 0., 0., 0.1 * delta),
            offset: point(px(0.), px(20.)),
            blur_radius: px(25.),
            spread_radius: px(-5.),
            inset: false,
        },
        BoxShadow {
            color: hsla(0., 0., 0., 0.1 * delta),
            offset: point(px(0.), px(8.)),
            blur_radius: px(10.),
            spread_radius: px(-6.),
            inset: false,
        },
    ]
}

impl Dialog {
    /// Create a new dialog.
    pub fn new(cx: &mut App) -> Self {
        Self {
            base: Some(BaseDialogRoot::Dialog(gpui_base::Dialog::new(cx))),
            focus_handle: cx.focus_handle(),
            style: StyleRefinement::default(),
            trigger: None,
            title: None,
            header: None,
            footer: None,
            content_builder: None,
            props: DialogProps::default(),
            children: Vec::new(),
            layer_ix: 0,
            selection_scope: TextSelectionScopeId::default(),
            button_props: DialogButtonProps::default(),
            motion: None,
            id: 0,
        }
    }

    /// Sets the trigger element for the dialog.
    ///
    /// When a trigger is set, the dialog will render as a trigger button that opens the dialog when clicked.
    pub fn trigger(mut self, trigger: impl IntoElement) -> Self {
        self.trigger = Some(trigger.into_any_element());
        self
    }

    /// Sets the content of the dialog.
    pub fn content<F>(mut self, builder: F) -> Self
    where
        F: Fn(DialogContent, &mut Window, &mut App) -> DialogContent + 'static,
    {
        self.content_builder = Some(Rc::new(builder));
        self
    }

    /// Sets the title of the dialog.
    pub fn title(mut self, title: impl IntoElement) -> Self {
        self.title = Some(title.into_any_element());
        self
    }

    /// Sets the header of the dialog, rendered above the title and content.
    pub(crate) fn header(mut self, header: impl IntoElement) -> Self {
        self.header = Some(header.into_any_element());
        self
    }

    /// Sets the footer of the dialog, the footer will render at the bottom of the dialog, usually for action buttons.
    ///
    /// A plain `Dialog` never renders buttons from `button_props`: the props
    /// only install the callbacks behind the `Confirm` and `Cancel` actions.
    /// Compose the action buttons yourself — typically with a
    /// [`DialogFooter`](crate::dialog::DialogFooter) — or use an
    /// [`AlertDialog`](crate::dialog::AlertDialog), which builds a default
    /// footer from `button_props` when no footer is set.
    pub fn footer(mut self, footer: impl IntoElement) -> Self {
        self.footer = Some(footer.into_any_element());
        self
    }

    /// Set the button props of the dialog.
    ///
    /// This overrides only the fields `button_props` sets; the rest of the
    /// dialog's button configuration is kept, so the call order does not
    /// matter.
    ///
    /// On a plain `Dialog` these props install the callbacks behind the
    /// `Confirm` and `Cancel` actions and the labels an
    /// [`AlertDialog`](crate::dialog::AlertDialog) default footer would use;
    /// the dialog surface itself renders no buttons from them, see
    /// [`Self::footer`].
    pub fn button_props(mut self, button_props: DialogButtonProps) -> Self {
        self.button_props.merge(button_props);
        self
    }

    pub(crate) fn with_base_alert_dialog(mut self, base: gpui_base::AlertDialog) -> Self {
        self.base = Some(BaseDialogRoot::AlertDialog(base));
        self.props.overlay_closable = false;
        self
    }

    /// Sets the callback for when the dialog is closed.
    ///
    /// Called after [`Self::on_ok`] or [`Self::on_cancel`] callback.
    pub fn on_close(
        mut self,
        on_close: impl Fn(&ClickEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.button_props.on_close = Some(Rc::new(on_close));
        self
    }

    /// Sets the callback for when the dialog is has been confirmed.
    ///
    /// The callback should return `true` to close the dialog, if return `false` the dialog will not be closed.
    pub fn on_ok(
        mut self,
        on_ok: impl Fn(&ClickEvent, &mut Window, &mut App) -> bool + 'static,
    ) -> Self {
        self.button_props = self.button_props.on_ok(on_ok);
        self
    }

    /// Sets the callback for when the dialog is has been canceled.
    ///
    /// The callback should return `true` to close the dialog, if return `false` the dialog will not be closed.
    pub fn on_cancel(
        mut self,
        on_cancel: impl Fn(&ClickEvent, &mut Window, &mut App) -> bool + 'static,
    ) -> Self {
        self.button_props = self.button_props.on_cancel(on_cancel);
        self
    }

    /// Sets the false to hide close icon, default: true
    pub fn close_button(mut self, close_button: bool) -> Self {
        self.props.close_button = close_button;
        self
    }

    /// Set the top offset of the dialog, defaults to None, will use the 1/10 of the viewport height.
    pub fn margin_top(mut self, margin_top: impl Into<Pixels>) -> Self {
        self.props.margin_top = Some(margin_top.into());
        self
    }

    /// Centers the dialog vertically in the window, whatever its height, in
    /// place of the [`Self::margin_top`] offset.
    pub fn centered(mut self) -> Self {
        self.props.centered = true;
        self
    }

    /// Sets the width of the dialog, defaults to 448px.
    ///
    /// The dialog is never wider than the viewport minus a margin on each side.
    ///
    /// See also [`Self::width`]
    pub fn w(mut self, width: impl Into<Pixels>) -> Self {
        self.props.width = width.into();
        self
    }

    /// Sets the width of the dialog, defaults to 448px.
    ///
    /// The dialog is never wider than the viewport minus a margin on each side.
    pub fn width(mut self, width: impl Into<Pixels>) -> Self {
        self.props.width = width.into();
        self
    }

    /// Set the maximum width of the dialog, defaults to `None`.
    pub fn max_w(mut self, max_width: impl Into<Pixels>) -> Self {
        self.props.max_width = Some(max_width.into());
        self
    }

    /// Set the overlay of the dialog, defaults to `true`.
    pub fn overlay(mut self, overlay: bool) -> Self {
        self.props.overlay = overlay;
        self
    }

    /// Set the overlay closable of the dialog, defaults to `true`.
    ///
    /// When the overlay is clicked, the dialog will be closed.
    pub fn overlay_closable(mut self, overlay_closable: bool) -> Self {
        self.props.overlay_closable = overlay_closable;
        self
    }

    /// Set whether to support keyboard esc to close the dialog, defaults to `true`.
    pub fn keyboard(mut self, keyboard: bool) -> Self {
        self.props.keyboard = keyboard;
        self
    }

    /// Sets how the dialog enters, defaulting to [`DialogEntrance::SlideDown`].
    ///
    /// This controls the surface and backdrop together, and closing animates
    /// both back out. Reduced motion skips both and shows the final state
    /// immediately, as does [`DialogEntrance::None`].
    pub fn entrance(mut self, entrance: DialogEntrance) -> Self {
        self.props.entrance = entrance;
        self
    }

    /// How long the exit transition runs; `Duration::ZERO` closes in one frame.
    ///
    /// Mirrors the entrance: [`DialogEntrance::None`], reduced motion, and a
    /// zero theme duration leave nothing to animate out.
    pub(crate) fn exit_duration(&self, cx: &App) -> Duration {
        if cx.reduce_motion() {
            return Duration::ZERO;
        }

        match self.props.entrance {
            DialogEntrance::None => Duration::ZERO,
            DialogEntrance::SlideDown => *ANIMATION_DURATION,
            _ => cx.theme().motion_tokens().duration_normal,
        }
    }

    pub(crate) fn motion_transition(&self, cx: &App) -> Transition {
        let transition = Transition::new(self.exit_duration(cx));
        // Use the same curve in both directions: changing the curve at the
        // reversal would resample the entrance at a different position.
        if self.props.entrance == DialogEntrance::SlideDown {
            transition.ease(cubic_bezier(1. / 3., 0.72, 2. / 3., 1.))
        } else {
            let easing = cx.theme().motion_tokens().easing_enter.clone();
            transition.ease(move |delta| easing.sample(delta).clamp(0., 1.))
        }
    }

    pub(crate) fn has_overlay(&self) -> bool {
        self.props.overlay
    }

    pub(crate) fn with_props(mut self, props: DialogProps) -> Self {
        self.props = props;
        self
    }

    fn defer_close_dialog(window: &mut Window, cx: &mut App) {
        WindowState::update(window, cx, |root, window, cx| {
            root.defer_close_dialog(window, cx);
        });
    }
}

impl ParentElement for Dialog {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Styled for Dialog {
    fn style(&mut self) -> &mut gpui::StyleRefinement {
        &mut self.style
    }
}

impl Dialog {
    fn render_trigger(self, trigger: AnyElement, _: &mut Window, _: &mut App) -> AnyElement {
        let content_builder = self.content_builder.clone();
        let style = self.style.clone();
        let props = self.props.clone();
        let button_props = self.button_props.clone();

        gpui_base::DialogTrigger::new(trigger)
            .on_open(move |window, cx| {
                let content_builder = content_builder.clone();
                let style = style.clone();
                let props = props.clone();
                let button_props = button_props.clone();
                window.open_dialog(cx, move |dialog, _, _| {
                    dialog
                        .refine_style(&style)
                        .button_props(button_props.clone())
                        .with_props(props.clone())
                        .content({
                            let content_builder = content_builder.clone();
                            move |content, window, cx| {
                                if let Some(builder) = content_builder.clone() {
                                    builder(content, window, cx)
                                } else {
                                    content
                                }
                            }
                        })
                });
            })
            .into_any_element()
    }
}

impl RenderOnce for Dialog {
    fn render(mut self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        if let Some(trigger) = self.trigger.take() {
            return self.render_trigger(trigger, window, cx);
        }

        let layer_ix = self.layer_ix;
        let selection_scope = self.selection_scope;
        let on_close = self.button_props.close_handler();
        let on_ok = self.button_props.ok_handler();
        let on_cancel = self.button_props.cancel_handler();

        let window_paddings = crate::window_border::window_paddings(window);
        let view_size = window.viewport_size()
            - gpui::size(
                window_paddings.left + window_paddings.right,
                window_paddings.top + window_paddings.bottom,
            );
        // The dialog keeps this much of the viewport clear around its edges,
        // so a small window shrinks the surface instead of letting it run off
        // the window. A dialog that fits keeps `margin_top` (a tenth of the
        // viewport by default); an overflowing one is snapped up to this edge
        // margin so that the preferred offset does not waste usable height.
        let margin = cx.theme().spacing_tokens().lg;
        let layer_offset = px(layer_ix as f32 * 16.);
        let (anchor, y) = if self.props.centered {
            (Anchor::LeftCenter, view_size.height / 2.)
        } else {
            let y = self.props.margin_top.unwrap_or(view_size.height / 10.);
            (Anchor::TopLeft, y)
        };
        let y = y + layer_offset;
        let entrance = self.props.entrance;
        let motion = cx.theme().motion_tokens();
        let closing = self.motion.is_some_and(|motion| motion.closing);
        let visibility = self
            .motion
            .map_or(1.0, |motion| motion.visibility.clamp(0., 1.));
        let fade_overlay = closing && self.props.overlay_visible;
        let travel = motion.distance_short.to_pixels(window.rem_size());
        let width = self
            .props
            .width
            .min((view_size.width - margin * 2.).max(px(0.)));
        let x = (view_size.width - width) / 2.;
        let max_height = (view_size.height - margin * 2. - layer_offset).max(px(0.));

        let base_size = window.text_style().font_size;
        let rem_size = window.rem_size();

        let mut paddings = Edges::all(px(16.));
        if let Some(pl) = self.style.padding.left {
            paddings.left = pl.to_pixels(base_size, rem_size);
        }
        if let Some(pr) = self.style.padding.right {
            paddings.right = pr.to_pixels(base_size, rem_size);
        }
        if let Some(pt) = self.style.padding.top {
            paddings.top = pt.to_pixels(base_size, rem_size);
        }
        if let Some(pb) = self.style.padding.bottom {
            paddings.bottom = pb.to_pixels(base_size, rem_size);
        }

        // The newest dialog still open owns Escape, the backdrop, and the
        // focus trap; a closing dialog keeps its layer only to finish leaving.
        let topmost = WindowState::read(window, cx)
            .active_dialogs
            .iter()
            .rposition(|dialog| !dialog.closing);
        let is_topmost = !closing && topmost == Some(layer_ix);

        anchored()
            .position(point(window_paddings.left, window_paddings.top))
            .snap_to_window()
            .child(
                div()
                    .id("dialog")
                    .test_support()
                    // A closing dialog is leaving: it must not swallow input
                    // aimed at what is already usable again beneath it.
                    .when(!closing, |this| this.occlude())
                    .w(view_size.width)
                    .h(view_size.height)
                    .when(fade_overlay, |this| {
                        this.child(div().absolute().inset_0().bg(overlay_color(true, cx)))
                    })
                    .child(
                        self.base
                            .take()
                            .expect("Dialog base host is always present")
                            .layer(self.id, is_topmost)
                            .focus_handle(self.focus_handle.clone())
                            .close_on_escape(self.props.keyboard && !closing)
                            .close_on_backdrop_press(self.props.overlay_closable && !closing)
                            .dismiss_below_y(TITLE_BAR_HEIGHT)
                            .when(self.props.overlay && !closing, |this| {
                                this.backdrop(
                                    div()
                                        .absolute()
                                        .size_full()
                                        .window_control_area(WindowControlArea::Drag)
                                        .when(self.props.overlay_visible, |overlay| {
                                            overlay.bg(overlay_color(true, cx))
                                        }),
                                )
                            })
                            .on_ok(move |event, window, cx| !closing && on_ok(event, window, cx))
                            .on_cancel(move |event, window, cx| {
                                !closing && on_cancel(event, window, cx)
                            })
                            .on_close(move |event, window, cx| on_close(event, window, cx))
                            .request_close(move |deferred, window, cx| {
                                // A dialog already leaving must not close
                                // whatever sits below it.
                                if closing {
                                    return;
                                }
                                if deferred {
                                    Self::defer_close_dialog(window, cx);
                                } else {
                                    window.close_dialog(cx);
                                }
                            })
                            .popup(
                                gpui_base::Positioner::corner(
                                    anchor,
                                    point(window_paddings.left + x, window_paddings.top + y),
                                )
                                .margin(margin)
                                .child(
                                    v_flex()
                                        .id("surface")
                                        .test_support()
                                        .debug_selector(move || format!("dialog-{layer_ix}"))
                                        .bg(cx.theme().tokens.background)
                                        .border_1()
                                        .border_color(cx.theme().border)
                                        .rounded(cx.theme().radius_lg)
                                        .min_h_24()
                                        .pt(paddings.top)
                                        .pb(paddings.bottom)
                                        .gap(paddings.top.max(px(8.)))
                                        .refine_style(&self.style)
                                        .px_0()
                                        .occlude()
                                        .w(width)
                                        .when_some(self.props.max_width, |this, w| this.max_w(w))
                                        .max_h(max_height)
                                        .child(
                                            v_flex()
                                                .flex_1()
                                                .overflow_hidden()
                                                .gap_y_2()
                                                .when_some(self.header, |this, header| {
                                                    this.child(
                                                        div()
                                                            .pl(paddings.left)
                                                            .pr(paddings.right)
                                                            .child(header),
                                                    )
                                                })
                                                .when_some(self.title, |this, title| {
                                                    this.child(
                                                        DialogTitle::new()
                                                            .pl(paddings.left)
                                                            .pr(paddings.right)
                                                            .child(title),
                                                    )
                                                })
                                                .when_some(self.content_builder, |this, builder| {
                                                    this.child(builder(
                                                        DialogContent::new()
                                                            .gap(paddings.bottom)
                                                            .pl(paddings.left)
                                                            .pr(paddings.right),
                                                        window,
                                                        cx,
                                                    ))
                                                })
                                                .when(!self.children.is_empty(), |this| {
                                                    this.child(
                                                        div().flex_1().overflow_hidden().child(
                                                            // Body
                                                            v_flex()
                                                                .size_full()
                                                                .overflow_y_scrollbar()
                                                                .pl(paddings.left)
                                                                .pr(paddings.right)
                                                                .children(self.children),
                                                        ),
                                                    )
                                                }),
                                        )
                                        .when_some(self.footer, |this, footer| {
                                            this.child(
                                                div()
                                                    .pl(paddings.left)
                                                    .pr(paddings.right)
                                                    .child(footer),
                                            )
                                        })
                                        .children(self.props.close_button.then(|| {
                                            let top = (paddings.top - px(10.)).max(px(8.));
                                            let right = (paddings.right - px(10.)).max(px(8.));

                                            gpui_base::DialogClose::new()
                                                .absolute()
                                                .top(top)
                                                .right(right)
                                                .trigger(|button| {
                                                    Button::new("close")
                                                        .with_base(button)
                                                        .small()
                                                        .ghost()
                                                        .icon(IconName::Close)
                                                        .accessibility_label("Close")
                                                })
                                        }))
                                        .when(closing, |surface| {
                                            // The shield is painted after the content, so
                                            // descendant hitboxes cannot receive input.
                                            surface
                                                .capture_any_mouse_down(|_, _, cx| {
                                                    cx.stop_propagation()
                                                })
                                                .capture_any_mouse_up(|_, _, cx| {
                                                    cx.stop_propagation()
                                                })
                                                .capture_key_down(|_, window, cx| {
                                                    window.prevent_default();
                                                    cx.stop_propagation();
                                                })
                                                .capture_key_up(|_, _, cx| cx.stop_propagation())
                                                .child(
                                                    div()
                                                        .absolute()
                                                        .inset_0()
                                                        .occlude()
                                                        .on_any_mouse_down(|_, _, cx| {
                                                            cx.stop_propagation()
                                                        })
                                                        .on_scroll(|_, _, cx| {
                                                            cx.stop_propagation()
                                                        }),
                                                )
                                        })
                                        // Base paints its popup in a deferred pass; the
                                        // surface must apply opacity itself.
                                        .opacity(visibility)
                                        .shadow(dialog_shadow(visibility))
                                        .text_selection_scope(selection_scope)
                                        .map(|surface| {
                                            if entrance == DialogEntrance::FadeSlide {
                                                let mut surface = EntranceSurface::new(
                                                    surface.into_any_element(),
                                                    travel,
                                                    window_paddings.top + margin,
                                                );
                                                surface.progress = visibility;
                                                surface.into_any_element()
                                            } else {
                                                surface.into_any_element()
                                            }
                                        }),
                                )
                                .when(
                                    entrance == DialogEntrance::SlideDown,
                                    |positioner| {
                                        positioner.position(point(
                                            window_paddings.left + x,
                                            window_paddings.top + y * visibility,
                                        ))
                                    },
                                ),
                            ),
                    )
                    .opacity(visibility),
            )
            .into_any_element()
    }
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    use gpui::{
        AppContext as _, Bounds, Context, Render, StatefulInteractiveElement as _, TestAppContext,
        VisualTestContext, size,
    };
    use std::{cell::Cell, rc::Rc};

    struct DialogHost {
        clicks: Rc<Cell<usize>>,
    }

    impl Render for DialogHost {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let clicks = self.clicks.clone();
            div().size_full().child(
                // A target beneath the dialog's backdrop, so tests can observe
                // whether presses reach the application while it is covered.
                div()
                    .id("background-target")
                    .absolute()
                    .top_0()
                    .left_0()
                    .w_full()
                    .h(px(200.))
                    .on_click(move |_, _, _| clicks.set(clicks.get() + 1)),
            )
        }
    }

    /// A window of `window_size` whose root renders the dialog layer, with
    /// motion reduced so the entrance animation settles on its first frame.
    pub(crate) fn window(
        cx: &mut TestAppContext,
        window_size: gpui::Size<Pixels>,
    ) -> &mut VisualTestContext {
        let (cx, _) = window_with_click_count(cx, window_size);
        cx
    }

    /// [`window`], also returning how often the click target beneath the
    /// dialog was pressed.
    fn window_with_click_count(
        cx: &mut TestAppContext,
        window_size: gpui::Size<Pixels>,
    ) -> (&mut VisualTestContext, Rc<Cell<usize>>) {
        cx.update(|cx| {
            crate::init(cx);
            cx.set_reduce_motion(true);
        });
        let clicks = Rc::new(Cell::new(0));
        let counter = clicks.clone();
        let (_, cx) = cx.add_window_view(|window, cx| {
            let view = cx.new(|_| DialogHost { clicks: counter });
            crate::Root::new(view, window, cx)
        });
        cx.simulate_resize(window_size);
        cx.update(|window, cx| window.draw(cx).clear(cx));
        (cx, clicks)
    }

    fn open(
        cx: &mut VisualTestContext,
        build: impl Fn(Dialog, &mut Window, &mut App) -> Dialog + 'static,
    ) {
        cx.update(|window, cx| window.open_dialog(cx, build));
        cx.run_until_parked();
        // Mount the layer and paint the current animation sample.
        cx.update(|window, cx| window.draw(cx).clear(cx));
        cx.update(|window, cx| window.draw(cx).clear(cx));
    }

    /// Draws one frame, so an exit transition samples the clock at its
    /// current value.
    fn frame(cx: &mut VisualTestContext) {
        cx.update(|window, _| window.refresh());
        cx.run_until_parked();
    }

    fn surface(cx: &mut VisualTestContext, layer_ix: usize) -> Bounds<Pixels> {
        let selector = ["dialog-0", "dialog-1"][layer_ix];
        cx.debug_bounds(selector)
            .unwrap_or_else(|| panic!("dialog layer {layer_ix} was not painted"))
    }

    /// The clamp must not touch a dialog that already fits: the default width
    /// and the tenth-of-the-viewport top offset are the documented contract.
    #[gpui::test]
    fn a_dialog_that_fits_keeps_its_default_width_and_top_offset(cx: &mut TestAppContext) {
        let cx = window(cx, size(px(1000.), px(800.)));
        open(cx, |dialog, _, _| dialog.title("Fits").child("body"));

        let bounds = surface(cx, 0);
        assert_eq!(bounds.size.width, px(448.));
        assert_eq!(bounds.origin.x, px(276.));
        assert_eq!(bounds.origin.y, px(80.));
    }

    /// A dialog wider and taller than the window must shrink to the viewport
    /// instead of running off both edges. It also gives up the usual top
    /// offset so that space is available to its content, while its footer
    /// remains inside the surface rather than clipped below it.
    #[gpui::test]
    fn a_dialog_larger_than_the_window_stays_inside_it(cx: &mut TestAppContext) {
        let viewport = size(px(400.), px(300.));
        let cx = window(cx, viewport);
        open(cx, |dialog, _, _| {
            dialog
                .w(px(800.))
                .title("Too big")
                .child(div().h(px(1000.)).child("tall body"))
                .footer(div().h(px(32.)).debug_selector(|| "footer-probe".into()))
        });

        let bounds = surface(cx, 0);
        let footer = cx.debug_bounds("footer-probe").unwrap();
        let margin = px(16.);
        assert!(
            bounds.origin.x >= margin && bounds.right() <= viewport.width - margin,
            "the dialog ran off the sides: {bounds:?}"
        );
        assert!(
            bounds.bottom() <= viewport.height - margin,
            "the dialog ran off the bottom: {bounds:?}"
        );
        assert_eq!(bounds.origin.y, margin);
        assert!(
            footer.bottom() <= bounds.bottom(),
            "the footer was clipped below the dialog: footer {footer:?}, dialog {bounds:?}"
        );
    }

    /// `Dialog::button_props` overrides only the fields it sets.
    #[gpui::test]
    fn dialog_button_props_merge_with_what_the_dialog_already_carries(cx: &mut TestAppContext) {
        let cx = window(cx, size(px(400.), px(300.)));
        cx.update(|_, cx| {
            let dialog = Dialog::new(cx)
                .button_props(DialogButtonProps::default().cancel_text("Keep"))
                .button_props(DialogButtonProps::default().ok_text("Delete"))
                .button_props(DialogButtonProps::default().ok_variant(ButtonVariant::Danger));

            assert_eq!(dialog.button_props.ok_text.as_deref(), Some("Delete"));
            assert_eq!(dialog.button_props.cancel_text.as_deref(), Some("Keep"));
            assert_eq!(dialog.button_props.ok_variant, Some(ButtonVariant::Danger));
        });
    }

    /// Each stacked dialog steps down 16px; the deepest one must still end
    /// above the bottom margin.
    #[gpui::test]
    fn stacked_dialogs_each_fit_the_window(cx: &mut TestAppContext) {
        let viewport = size(px(400.), px(300.));
        let cx = window(cx, viewport);
        open(cx, |dialog, _, _| {
            dialog.title("First").child(div().h(px(1000.)))
        });
        open(cx, |dialog, _, _| {
            dialog.title("Second").child(div().h(px(1000.)))
        });

        let first = surface(cx, 0);
        let second = surface(cx, 1);
        assert_eq!(second.origin.y, first.origin.y + px(16.));
        assert!(first.bottom() <= viewport.height - px(16.), "{first:?}");
        assert!(second.bottom() <= viewport.height - px(16.), "{second:?}");
        assert!(second.size.height < first.size.height);
    }

    #[gpui::test]
    fn test_dialog_entrance_builder(cx: &mut TestAppContext) {
        cx.update(crate::init);
        cx.update(|cx| {
            assert_eq!(Dialog::new(cx).props.entrance, DialogEntrance::SlideDown);
            for entrance in [
                DialogEntrance::SlideDown,
                DialogEntrance::Fade,
                DialogEntrance::FadeSlide,
                DialogEntrance::None,
            ] {
                assert_eq!(Dialog::new(cx).entrance(entrance).props.entrance, entrance);
            }
        });
    }

    #[gpui::test]
    fn reduced_motion_displays_every_entrance_at_rest(cx: &mut TestAppContext) {
        for entrance in [
            DialogEntrance::SlideDown,
            DialogEntrance::Fade,
            DialogEntrance::FadeSlide,
            DialogEntrance::None,
        ] {
            let cx = window(cx, size(px(1000.), px(800.)));
            open(cx, move |dialog, _, _| {
                dialog
                    .title("Entrance")
                    .child("body")
                    .entrance(entrance)
                    .margin_top(px(300.))
            });
            assert_eq!(surface(cx, 0).top(), px(300.));
        }
    }

    #[gpui::test]
    fn no_entrance_displays_immediately_and_keeps_keyboard_dismissal(cx: &mut TestAppContext) {
        let cx = window(cx, size(px(1000.), px(800.)));
        cx.update(|_, cx| cx.set_reduce_motion(false));
        open(cx, |dialog, _, _| {
            dialog
                .title("Immediate")
                .child("body")
                .entrance(DialogEntrance::None)
                .margin_top(px(300.))
        });
        assert_eq!(surface(cx, 0).top(), px(300.));
        cx.simulate_keystrokes("escape");
        cx.update(|window, cx| assert!(WindowState::read(window, cx).active_dialogs.is_empty()));
    }

    /// Closing keeps the dialog mounted until the entrance plays back out, and
    /// the dialog stops counting as active before it leaves the screen.
    #[gpui::test]
    fn closing_plays_the_entrance_backwards_before_the_dialog_unmounts(cx: &mut TestAppContext) {
        let cx = window(cx, size(px(1000.), px(800.)));
        cx.update(|_, cx| cx.set_reduce_motion(false));
        open(cx, |dialog, _, _| {
            dialog.title("Closing").child("body").margin_top(px(300.))
        });

        cx.background_executor.advance_clock(*ANIMATION_DURATION);
        frame(cx);
        cx.update(|window, cx| window.close_dialog(cx));
        frame(cx);
        // The exit starts from the resting position and the dialog is already
        // logically inactive, though it still paints.
        cx.update(|window, cx| {
            assert_eq!(WindowState::read(window, cx).active_dialogs.len(), 1);
            assert!(!window.has_active_dialog(cx));
        });
        assert_eq!(surface(cx, 0).top(), px(300.));

        // Halfway through, the surface has slid up between rest and the top.
        cx.background_executor
            .advance_clock(*ANIMATION_DURATION / 2);
        frame(cx);
        cx.update(|window, cx| assert_eq!(WindowState::read(window, cx).active_dialogs.len(), 1));
        let halfway = surface(cx, 0).top();
        assert!(
            halfway > px(0.) && halfway < px(300.),
            "the closing dialog should slide back up: {halfway:?}"
        );

        // Once the transition finishes the dialog leaves the window state.
        cx.background_executor
            .advance_clock(*ANIMATION_DURATION / 2 + Duration::from_millis(1));
        frame(cx);
        cx.update(|window, cx| {
            assert!(WindowState::read(window, cx).active_dialogs.is_empty());
            assert!(!window.has_active_dialog(cx));
        });
        assert!(cx.debug_bounds("dialog-0").is_none());
    }

    #[gpui::test]
    fn reduced_motion_closes_in_a_single_frame(cx: &mut TestAppContext) {
        let cx = window(cx, size(px(1000.), px(800.)));
        open(cx, |dialog, _, _| dialog.title("Reduced").child("body"));
        cx.update(|window, cx| window.close_dialog(cx));
        cx.update(|window, cx| {
            assert!(WindowState::read(window, cx).active_dialogs.is_empty());
            assert!(!window.has_active_dialog(cx));
        });
    }

    #[gpui::test]
    fn zero_theme_duration_closes_fade_entrances_immediately(cx: &mut TestAppContext) {
        for entrance in [DialogEntrance::Fade, DialogEntrance::FadeSlide] {
            let cx = window(cx, size(px(1000.), px(800.)));
            cx.update(|_, cx| {
                cx.set_reduce_motion(false);
                crate::Theme::update(cx, |theme| theme.motion.duration_normal = Duration::ZERO);
            });
            open(cx, move |dialog, _, _| {
                dialog.title("Immediate").child("body").entrance(entrance)
            });
            cx.update(|window, cx| window.close_dialog(cx));
            cx.update(|window, cx| {
                assert!(WindowState::read(window, cx).active_dialogs.is_empty());
                assert!(!window.has_active_dialog(cx));
            });
        }
    }

    /// Opening a new dialog while the previous one is leaving keeps both
    /// mounted for the exit: the new dialog owns focus and survives it.
    #[gpui::test]
    fn reopening_during_the_exit_keeps_the_new_dialog(cx: &mut TestAppContext) {
        let cx = window(cx, size(px(1000.), px(800.)));
        cx.update(|_, cx| cx.set_reduce_motion(false));
        open(cx, |dialog, _, _| dialog.title("First").child("body"));
        cx.background_executor.advance_clock(*ANIMATION_DURATION);
        frame(cx);
        cx.update(|window, cx| window.close_dialog(cx));
        frame(cx);

        open(cx, |dialog, _, _| dialog.title("Second").child("body"));
        cx.update(|window, cx| {
            let state = WindowState::read(window, cx);
            assert_eq!(state.active_dialogs.len(), 2);
            assert!(state.active_dialogs[0].closing);
            assert!(!state.active_dialogs[1].closing);
            assert!(
                state.active_dialogs[1].focus_handle().is_focused(window),
                "the reopened dialog owns focus while the old one leaves"
            );
        });

        cx.background_executor
            .advance_clock(*ANIMATION_DURATION + Duration::from_millis(1));
        frame(cx);
        // The old dialog is gone and the new one moves up to its layer.
        frame(cx);
        cx.update(|window, cx| {
            let state = WindowState::read(window, cx);
            assert_eq!(state.active_dialogs.len(), 1);
            assert!(!state.active_dialogs[0].closing);
            assert!(state.active_dialogs[0].focus_handle().is_focused(window));
            assert!(window.has_active_dialog(cx));
        });
        assert_eq!(surface(cx, 0).top(), px(80.));
        assert!(cx.debug_bounds("dialog-1").is_none());
    }

    /// Closing the top of a stack only removes that dialog: the one below stays
    /// mounted and becomes the active dialog for the duration of the exit.
    #[gpui::test]
    fn closing_the_top_dialog_leaves_the_one_below_mounted(cx: &mut TestAppContext) {
        let cx = window(cx, size(px(1000.), px(800.)));
        cx.update(|_, cx| cx.set_reduce_motion(false));
        open(cx, |dialog, _, _| dialog.title("First").child("body"));
        open(cx, |dialog, _, _| dialog.title("Second").child("body"));

        cx.background_executor.advance_clock(*ANIMATION_DURATION);
        frame(cx);
        cx.update(|window, cx| window.close_dialog(cx));
        frame(cx);
        cx.update(|window, cx| {
            assert_eq!(WindowState::read(window, cx).active_dialogs.len(), 2);
            assert!(window.has_active_dialog(cx));
        });
        assert!(
            cx.debug_bounds("dialog-0").is_some(),
            "the lower dialog stays"
        );
        assert!(
            cx.debug_bounds("dialog-1").is_some(),
            "the closing dialog still paints its exit"
        );

        cx.background_executor
            .advance_clock(*ANIMATION_DURATION + Duration::from_millis(1));
        frame(cx);
        cx.update(|window, cx| {
            assert_eq!(WindowState::read(window, cx).active_dialogs.len(), 1);
            assert!(window.has_active_dialog(cx));
        });
        assert!(cx.debug_bounds("dialog-0").is_some());
        assert!(cx.debug_bounds("dialog-1").is_none());
    }

    /// A leaving dialog releases input: a press that the open backdrop used to
    /// swallow now reaches the application beneath it.
    #[gpui::test]
    fn closing_dialog_does_not_block_input_beneath_it(cx: &mut TestAppContext) {
        let (cx, clicks) = window_with_click_count(cx, size(px(1000.), px(800.)));
        cx.update(|_, cx| cx.set_reduce_motion(false));
        open(cx, |dialog, _, _| {
            dialog
                .title("Closing")
                .child("body")
                .margin_top(px(300.))
                .overlay_closable(false)
        });

        // The open dialog covers the window: the backdrop stops the press
        // before it can reach the target underneath.
        let backdrop_point = point(px(100.), px(60.));
        cx.simulate_click(backdrop_point, gpui::Modifiers::default());
        assert_eq!(clicks.get(), 0, "an open dialog blocked the application");

        cx.background_executor.advance_clock(*ANIMATION_DURATION);
        frame(cx);
        cx.update(|window, cx| window.close_dialog(cx));
        frame(cx);
        cx.simulate_click(backdrop_point, gpui::Modifiers::default());
        assert_eq!(
            clicks.get(),
            1,
            "the closing dialog swallowed a press meant for the application"
        );
    }

    #[gpui::test]
    fn zero_theme_duration_displays_fade_entrances_immediately(cx: &mut TestAppContext) {
        for entrance in [DialogEntrance::Fade, DialogEntrance::FadeSlide] {
            let cx = window(cx, size(px(1000.), px(800.)));
            cx.update(|_, cx| {
                cx.set_reduce_motion(false);
                crate::Theme::update(cx, |theme| theme.motion.duration_normal = Duration::ZERO);
            });
            open(cx, move |dialog, _, _| {
                dialog
                    .title("Immediate")
                    .child("body")
                    .entrance(entrance)
                    .margin_top(px(300.))
            });
            assert_eq!(surface(cx, 0).top(), px(300.));
        }
    }

    #[gpui::test]
    fn alert_dialog_uses_the_same_entrance(cx: &mut TestAppContext) {
        for entrance in [
            DialogEntrance::SlideDown,
            DialogEntrance::Fade,
            DialogEntrance::FadeSlide,
            DialogEntrance::None,
        ] {
            let cx = window(cx, size(px(1000.), px(800.)));
            cx.update(|window, cx| {
                let alert = crate::dialog::AlertDialog::new(cx)
                    .title("Alert")
                    .entrance(entrance);
                assert_eq!(alert.build_surface(window, cx).props.entrance, entrance);
                window.open_alert_dialog(cx, move |alert, _, _| {
                    alert.title("Alert").entrance(entrance)
                });
            });
            cx.run_until_parked();
            cx.update(|window, cx| window.draw(cx).clear(cx));
            cx.update(|window, cx| window.draw(cx).clear(cx));
            assert_eq!(surface(cx, 0).top(), px(80.));
        }
    }

    /// Closing fades the surface itself, not only the layer: the base host
    /// paints in a deferred pass, where ancestor opacity no longer applies.
    #[gpui::test]
    fn closing_fades_the_dialog_surface(cx: &mut TestAppContext) {
        let cx = window(cx, size(px(1000.), px(800.)));
        cx.update(|_, cx| cx.set_reduce_motion(false));
        open(cx, |dialog, _, _| {
            dialog
                .title("Fading")
                .child("body")
                .margin_top(px(300.))
                .entrance(DialogEntrance::Fade)
        });
        cx.background_executor.advance_clock(*ANIMATION_DURATION);
        frame(cx);
        cx.update(|window, cx| window.close_dialog(cx));
        frame(cx);
        assert_eq!(
            surface_alpha(cx),
            1.0,
            "the exit should start fully visible"
        );

        cx.background_executor
            .advance_clock(Duration::from_millis(90));
        frame(cx);
        let alpha = surface_alpha(cx);
        assert!(
            alpha > 0.0 && alpha < 1.0,
            "the closing surface should fade, but its background is {alpha}"
        );
    }

    #[gpui::test]
    fn closing_during_entrance_reverses_from_the_current_sample(cx: &mut TestAppContext) {
        for entrance in [
            DialogEntrance::SlideDown,
            DialogEntrance::Fade,
            DialogEntrance::FadeSlide,
        ] {
            let cx = window(cx, size(px(1000.), px(800.)));
            cx.update(|_, cx| cx.set_reduce_motion(false));
            open(cx, move |dialog, _, _| {
                dialog
                    .title("Interrupted")
                    .child("body")
                    .margin_top(px(300.))
                    .entrance(entrance)
            });
            cx.background_executor
                .advance_clock(Duration::from_millis(40));
            frame(cx);
            let before = surface(cx, 0);
            let alpha = surface_alpha(cx);
            assert!(alpha > 0. && alpha < 1.);
            cx.update(|window, cx| window.close_dialog(cx));
            frame(cx);
            assert_eq!(surface(cx, 0), before, "{entrance:?} jumped on close");
            assert!((surface_alpha(cx) - alpha).abs() < 0.001);
            cx.background_executor
                .advance_clock(Duration::from_millis(20));
            frame(cx);
            assert!(surface_alpha(cx) < alpha);
            assert!(surface(cx, 0).top() <= before.top());
        }
    }

    #[gpui::test]
    fn exiting_content_rejects_clicks_focus_and_text_input(cx: &mut TestAppContext) {
        use crate::input::{Input, InputState};
        use gpui::Focusable as _;

        for deferred in [false, true] {
            let cx = window(cx, size(px(1000.), px(800.)));
            let input = cx.update(|window, cx| cx.new(|cx| InputState::new(window, cx)));
            let clicks = Rc::new(Cell::new(0));
            let counter = clicks.clone();
            let field = input.clone();
            cx.update(|_, cx| cx.set_reduce_motion(false));
            open(cx, move |dialog, _, _| {
                let counter = counter.clone();
                dialog
                    .title("Form")
                    .child(
                        div()
                            .debug_selector(|| "exit-input".into())
                            .child(Input::new(&field)),
                    )
                    .footer(
                        div().debug_selector(|| "exit-button".into()).child(
                            Button::new("custom")
                                .label("Custom action")
                                .w_full()
                                .on_click(move |_, _, _| counter.set(counter.get() + 1)),
                        ),
                    )
            });
            cx.background_executor.advance_clock(*ANIMATION_DURATION);
            frame(cx);
            let button = cx.debug_bounds("exit-button").unwrap().center();
            cx.simulate_click(button, gpui::Modifiers::default());
            assert_eq!(clicks.get(), 1);
            cx.update(|window, cx| input.focus_handle(cx).focus(window, cx));
            cx.simulate_input("before");
            assert_eq!(input.read_with(cx, |input, _| input.value()), "before");
            cx.update(|window, cx| {
                if deferred {
                    Dialog::defer_close_dialog(window, cx);
                } else {
                    window.close_dialog(cx);
                }
            });
            frame(cx);
            let button = cx.debug_bounds("exit-button").unwrap().center();
            cx.simulate_click(button, gpui::Modifiers::default());
            assert_eq!(clicks.get(), 1, "a closing footer button ran its callback");
            let field = cx.debug_bounds("exit-input").unwrap().center();
            cx.simulate_click(field, gpui::Modifiers::default());
            cx.simulate_input("after");
            assert_eq!(input.read_with(cx, |input, _| input.value()), "before");
            for key in ["tab", "shift-tab"] {
                cx.simulate_keystrokes(key);
                frame(cx);
                cx.update(|window, cx| assert!(!input.focus_handle(cx).is_focused(window)));
            }
            // Keyboard/a11y focus requests must not revive the exiting scope.
            cx.update(|window, cx| input.focus_handle(cx).focus(window, cx));
            frame(cx);
            cx.update(|window, cx| assert!(!input.focus_handle(cx).is_focused(window)));
            cx.simulate_input("after");
            assert_eq!(input.read_with(cx, |input, _| input.value()), "before");
        }
    }

    /// The most opaque background painted at the surface's current bounds.
    fn surface_alpha(cx: &mut VisualTestContext) -> f32 {
        let bounds = cx.debug_bounds("dialog-0").unwrap();
        let scale = cx.update(|window, _| window.scale_factor());
        let left = f32::from(bounds.origin.x) * scale;
        let top = f32::from(bounds.origin.y) * scale;
        let width = f32::from(bounds.size.width) * scale;
        let height = f32::from(bounds.size.height) * scale;
        cx.update(|window, _| {
            window
                .painted_quads()
                .into_iter()
                .filter(|quad| {
                    (quad.bounds.origin.x.0 - left).abs() < 1.0
                        && (quad.bounds.origin.y.0 - top).abs() < 1.0
                        && (quad.bounds.size.width.0 - width).abs() < 1.0
                        && (quad.bounds.size.height.0 - height).abs() < 1.0
                })
                .filter_map(|quad| quad.background.as_solid().map(|color| color.a))
                .fold(0.0_f32, f32::max)
        })
    }
}
