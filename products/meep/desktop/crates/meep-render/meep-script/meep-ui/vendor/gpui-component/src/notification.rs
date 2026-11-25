use std::{
    any::TypeId,
    borrow::Cow,
    collections::{HashMap, HashSet},
    rc::Rc,
    time::Duration,
};

use gpui::{
    Anchor, Animation, AnimationExt, AnyElement, AnyWindowHandle, App, AppContext, ClickEvent,
    Context, DismissEvent, ElementId, Entity, EventEmitter, FocusHandle, Global,
    InteractiveElement as _, IntoElement, ParentElement as _, Pixels, Render, SharedString,
    StatefulInteractiveElement, StyleRefinement, Styled, Subscription, SystemNotification,
    SystemNotificationResponse, WeakEntity, Window, WindowId, div, prelude::FluentBuilder, px,
    relative,
};
use gpui_base::{
    Toast as BaseToast, ToastManager, ToastMotion, ToastOptions, ToastStack, ToastStackState,
    ToastTransitionStatus,
};

use crate::{
    ActiveTheme as _, Edges, Icon, IconName, Sizable as _, StyledExt, TITLE_BAR_HEIGHT,
    animation::cubic_bezier,
    button::{Button, ButtonVariants as _},
    styled::toast_shadow,
    v_flex,
};

const NOTIFICATION_TRANSITION_DURATION: Duration = Duration::from_millis(400);
const NOTIFICATION_EXIT_DURATION: Duration = Duration::from_millis(200);
const NOTIFICATION_TRANSITION_OFFSET: Pixels = px(96.);
const DEFAULT_NOTIFICATION_WIDTH: Pixels = px(382.);
const NOTIFICATION_ADVANCE_INTERVAL: Duration = Duration::from_millis(50);
struct DismissRequest;

#[derive(Debug, Clone, Copy, Default)]
pub enum NotificationType {
    #[default]
    Info,
    Success,
    Warning,
    Error,
}

impl NotificationType {
    fn icon(&self, cx: &App) -> Icon {
        match self {
            Self::Info => Icon::new(IconName::Info).text_color(cx.theme().info),
            Self::Success => Icon::new(IconName::CircleCheck).text_color(cx.theme().success),
            Self::Warning => Icon::new(IconName::TriangleAlert).text_color(cx.theme().warning),
            Self::Error => Icon::new(IconName::CircleX).text_color(cx.theme().danger),
        }
    }
}

/// Where a notification is presented: as an in-app toast, in the operating
/// system's notification center, or both.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum NotificationDelivery {
    /// Show only the in-app toast.
    #[default]
    InApp,
    /// Post only to the OS notification center; no in-app toast is shown.
    System,
    /// Show the in-app toast and post to the OS notification center.
    InAppAndSystem,
}

impl NotificationDelivery {
    /// Whether this delivery shows an in-app toast.
    pub fn includes_in_app(&self) -> bool {
        matches!(self, Self::InApp | Self::InAppAndSystem)
    }

    /// Whether this delivery posts to the OS notification center.
    pub fn includes_system(&self) -> bool {
        matches!(self, Self::System | Self::InAppAndSystem)
    }
}

/// Namespaces the library's system-notification tags away from tags the
/// application posts itself, so the response handler can tell them apart.
const SYSTEM_TAG_PREFIX: &str = "gpui-component/notification/";

#[derive(Debug, PartialEq, Clone, Hash, Eq)]
pub(crate) enum NotificationId {
    Id(TypeId),
    IdAndElementId(TypeId, ElementId),
}

impl NotificationId {
    /// Stable OS-notification tag for this id within a running binary, so a
    /// repeat push with the same id replaces the previous system
    /// notification, mirroring the in-app replace semantics.
    fn system_tag(&self) -> SharedString {
        format!("{SYSTEM_TAG_PREFIX}{self:?}").into()
    }
}

impl From<TypeId> for NotificationId {
    fn from(type_id: TypeId) -> Self {
        Self::Id(type_id)
    }
}

impl From<(TypeId, ElementId)> for NotificationId {
    fn from((type_id, id): (TypeId, ElementId)) -> Self {
        Self::IdAndElementId(type_id, id)
    }
}

/// A notification element.
pub struct Notification {
    /// The id is used make the notification unique.
    /// Then you push a notification with the same id, the previous notification will be replaced.
    ///
    /// None means the notification will be added to the end of the list.
    id: NotificationId,
    style: StyleRefinement,
    type_: Option<NotificationType>,
    title: Option<SharedString>,
    message: Option<SharedString>,
    icon: Option<Icon>,
    placement: Option<Anchor>,
    delivery: Option<NotificationDelivery>,
    autohide: bool,
    action_builder: Option<Rc<dyn Fn(&mut Self, &mut Window, &mut Context<Self>) -> Button>>,
    content_builder: Option<Rc<dyn Fn(&mut Self, &mut Window, &mut Context<Self>) -> AnyElement>>,
    on_click: Option<Rc<dyn Fn(&ClickEvent, &mut Window, &mut App)>>,
    on_close: Option<Rc<dyn Fn(&mut Window, &mut App)>>,
    transition_status: ToastTransitionStatus,
}

impl From<String> for Notification {
    fn from(s: String) -> Self {
        Self::new().message(s)
    }
}

impl From<SharedString> for Notification {
    fn from(s: SharedString) -> Self {
        Self::new().message(s)
    }
}

impl From<&str> for Notification {
    fn from(s: &str) -> Self {
        Self::new().message(s)
    }
}

impl<'a> From<Cow<'a, str>> for Notification {
    fn from(s: Cow<'a, str>) -> Self {
        Self::new().message(s)
    }
}

impl<T> From<(NotificationType, T)> for Notification
where
    T: Into<SharedString>,
{
    fn from((type_, content): (NotificationType, T)) -> Self {
        Self::new().message(content).with_type(type_)
    }
}

struct DefaultIdType;

impl Notification {
    /// Create a new notification.
    ///
    /// The default id is a random UUID.
    pub fn new() -> Self {
        let id: SharedString = uuid::Uuid::new_v4().to_string().into();
        let id = (TypeId::of::<DefaultIdType>(), id.into());

        Self {
            id: id.into(),
            style: StyleRefinement::default(),
            title: None,
            message: None,
            type_: None,
            icon: None,
            placement: None,
            delivery: None,
            autohide: true,
            action_builder: None,
            content_builder: None,
            on_click: None,
            on_close: None,
            transition_status: ToastTransitionStatus::Starting,
        }
    }

    /// Set the message of the notification, default is None.
    pub fn message(mut self, message: impl Into<SharedString>) -> Self {
        self.message = Some(message.into());
        self
    }

    /// Create an info notification with the given message.
    pub fn info(message: impl Into<SharedString>) -> Self {
        Self::new()
            .message(message)
            .with_type(NotificationType::Info)
    }

    /// Create a success notification with the given message.
    pub fn success(message: impl Into<SharedString>) -> Self {
        Self::new()
            .message(message)
            .with_type(NotificationType::Success)
    }

    /// Create a warning notification with the given message.
    pub fn warning(message: impl Into<SharedString>) -> Self {
        Self::new()
            .message(message)
            .with_type(NotificationType::Warning)
    }

    /// Create an error notification with the given message.
    pub fn error(message: impl Into<SharedString>) -> Self {
        Self::new()
            .message(message)
            .with_type(NotificationType::Error)
    }

    /// Set the type for unique identification of the notification.
    ///
    /// ```rs
    /// struct MyNotificationKind;
    /// let notification = Notification::new().message("Hello").id::<MyNotificationKind>();
    /// ```
    pub fn id<T: Sized + 'static>(mut self) -> Self {
        self.id = TypeId::of::<T>().into();
        self
    }

    /// Set the type and id of the notification, used to uniquely identify the notification.
    pub fn id1<T: Sized + 'static>(mut self, key: impl Into<ElementId>) -> Self {
        self.id = (TypeId::of::<T>(), key.into()).into();
        self
    }

    /// Set the title of the notification, default is None.
    ///
    /// If title is None, the notification will not have a title.
    pub fn title(mut self, title: impl Into<SharedString>) -> Self {
        self.title = Some(title.into());
        self
    }

    /// Set the icon of the notification.
    ///
    /// If icon is None, the notification will use the default icon of the type.
    pub fn icon(mut self, icon: impl Into<Icon>) -> Self {
        self.icon = Some(icon.into());
        self
    }

    /// Set the type of the notification, default is NotificationType::Info.
    pub fn with_type(mut self, type_: NotificationType) -> Self {
        self.type_ = Some(type_);
        self
    }

    /// Set the placement of the notification, overriding the global
    /// [`NotificationSettings::placement`].
    ///
    /// Notifications are stacked separately for each placement.
    pub fn placement(mut self, placement: Anchor) -> Self {
        self.placement = Some(placement);
        self
    }

    /// Set where this notification is delivered, overriding the global
    /// [`NotificationSettings::delivery`].
    ///
    /// System delivery uses the OS notification center: the title and message
    /// become the system notification's title and body (a notification with
    /// neither is not posted). Pushing again with the same [`Notification::id`]
    /// replaces the previous system notification. Clicking the system
    /// notification activates the window, closes the in-app toast (if any),
    /// and fires [`Notification::on_click`]; with
    /// [`NotificationDelivery::System`] the toast never exists, so
    /// [`Notification::on_close`] is never called.
    ///
    /// Platform requirements: on macOS the application must run from a bundled
    /// `.app` in a location the system trusts, such as `/Applications` (posts
    /// are silently dropped under plain `cargo run`, and the first post
    /// triggers the authorization prompt); on Windows the application must
    /// call [`gpui::App::set_app_identity`] early in startup; on Linux a
    /// notification daemon must be present and retraction is unsupported
    /// (dismissed notifications age out).
    pub fn delivery(mut self, delivery: NotificationDelivery) -> Self {
        self.delivery = Some(delivery);
        self
    }

    /// Deliver this notification only to the OS notification center.
    ///
    /// Shorthand for [`Notification::delivery`] with
    /// [`NotificationDelivery::System`]; see there for platform requirements.
    pub fn system(self) -> Self {
        self.delivery(NotificationDelivery::System)
    }

    /// Deliver this notification as an in-app toast and to the OS
    /// notification center.
    ///
    /// Shorthand for [`Notification::delivery`] with
    /// [`NotificationDelivery::InAppAndSystem`]; see there for platform
    /// requirements.
    pub fn in_app_and_system(self) -> Self {
        self.delivery(NotificationDelivery::InAppAndSystem)
    }

    /// Set the auto hide of the notification, default is true.
    pub fn autohide(mut self, autohide: bool) -> Self {
        self.autohide = autohide;
        self
    }

    /// Set the click callback of the notification.
    pub fn on_click(
        mut self,
        on_click: impl Fn(&ClickEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_click = Some(Rc::new(on_click));
        self
    }

    /// Set the close callback of the notification.
    ///
    /// Triggered when the notification is closed by any means
    /// (close button, middle-click, autohide, click handler, or programmatic close).
    pub fn on_close(mut self, on_close: impl Fn(&mut Window, &mut App) + 'static) -> Self {
        self.on_close = Some(Rc::new(on_close));
        self
    }

    /// Set the action button of the notification.
    ///
    /// When an action is set, the notification will not autohide.
    pub fn action<F>(mut self, action: F) -> Self
    where
        F: Fn(&mut Self, &mut Window, &mut Context<Self>) -> Button + 'static,
    {
        self.action_builder = Some(Rc::new(action));
        self.autohide = false;
        self
    }

    /// Dismiss the notification.
    pub fn dismiss(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let _ = window;
        cx.emit(DismissRequest);
    }

    fn begin_close(&mut self, cx: &mut Context<Self>) {
        if self.transition_status != ToastTransitionStatus::Ending {
            self.transition_status = ToastTransitionStatus::Ending;
            cx.notify();
        }
    }

    fn complete_enter(&mut self, cx: &mut Context<Self>) {
        if self.transition_status == ToastTransitionStatus::Starting {
            self.transition_status = ToastTransitionStatus::Present;
            cx.notify();
        }
    }

    fn complete_close(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        cx.emit(DismissEvent);
        if let Some(on_close) = self.on_close.clone() {
            on_close(window, cx);
        }
    }

    /// Set the content of the notification.
    pub fn content(
        mut self,
        content: impl Fn(&mut Self, &mut Window, &mut Context<Self>) -> AnyElement + 'static,
    ) -> Self {
        self.content_builder = Some(Rc::new(content));
        self
    }
}

impl EventEmitter<DismissEvent> for Notification {}
impl EventEmitter<DismissRequest> for Notification {}
impl FluentBuilder for Notification {}
impl Styled for Notification {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl Render for Notification {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let content = self
            .content_builder
            .clone()
            .map(|builder| builder(self, window, cx));
        let action = self
            .action_builder
            .clone()
            .map(|builder| builder(self, window, cx).small().mr_3p5());

        let transition_status = self.transition_status;
        let closing = transition_status == ToastTransitionStatus::Ending;
        let icon = match self.type_ {
            None => self.icon.clone(),
            Some(type_) => Some(type_.icon(cx)),
        };
        let has_icon = icon.is_some();
        let placement = self.placement.unwrap_or(cx.theme().notification.placement);

        BaseToast::new("notification")
            .transition_status(transition_status)
            .h_flex()
            .group("")
            .occlude()
            .relative()
            .w_full()
            .border_1()
            .border_color(cx.theme().border)
            .bg(cx.theme().tokens.popover)
            .rounded(cx.theme().radius_lg)
            .shadow(toast_shadow(1.))
            .py_3p5()
            .px_4()
            .gap_3()
            .refine_style(&self.style)
            .when_some(icon, |this, icon| {
                this.child(div().absolute().top(px(18.)).left_4().child(icon))
            })
            .child(
                v_flex()
                    .flex_1()
                    .overflow_hidden()
                    .when(has_icon, |this| this.pl_6())
                    .when_some(self.title.clone(), |this, title| {
                        this.child(div().text_sm().font_semibold().child(title))
                    })
                    .when_some(self.message.clone(), |this, message| {
                        this.child(div().text_sm().child(message))
                    })
                    .when_some(content, |this, content| this.child(content)),
            )
            .when_some(action, |this, action| this.child(action))
            .child(
                div()
                    .absolute()
                    .top_1()
                    .right_1()
                    .invisible()
                    .group_hover("", |this| this.visible())
                    .child(
                        Button::new("close")
                            .icon(IconName::Close)
                            .accessibility_label("Close")
                            .ghost()
                            .xsmall()
                            .on_click(cx.listener(|this, _, window, cx| {
                                cx.stop_propagation();
                                this.dismiss(window, cx);
                            })),
                    ),
            )
            .when_some(self.on_click.clone(), |this, on_click| {
                this.on_click(cx.listener(move |view, event, window, cx| {
                    view.dismiss(window, cx);
                    on_click(event, window, cx);
                }))
            })
            .on_aux_click(cx.listener(move |view, event: &ClickEvent, window, cx| {
                if event.is_middle_click() {
                    view.dismiss(window, cx);
                }
            }))
            .with_animation(
                ElementId::NamedInteger("slide-down".into(), closing as u64),
                Animation::new(if closing {
                    NOTIFICATION_EXIT_DURATION
                } else {
                    NOTIFICATION_TRANSITION_DURATION
                })
                .with_easing(cubic_bezier(0.25, 0.1, 0.25, 1.)),
                move |this, delta| {
                    if closing {
                        let opacity = 1. - delta;
                        let that = this.opacity(opacity).shadow(toast_shadow(opacity.powi(3)));
                        let y_offset = match placement {
                            Anchor::TopLeft | Anchor::TopRight | Anchor::TopCenter => {
                                -delta * NOTIFICATION_TRANSITION_OFFSET
                            }
                            Anchor::BottomLeft | Anchor::BottomRight | Anchor::BottomCenter => {
                                delta * NOTIFICATION_TRANSITION_OFFSET
                            }
                            _ => px(0.),
                        };
                        that.top(y_offset)
                    } else {
                        let y_offset = match placement {
                            Anchor::TopLeft | Anchor::TopRight | Anchor::TopCenter => {
                                -NOTIFICATION_TRANSITION_OFFSET
                                    + delta * NOTIFICATION_TRANSITION_OFFSET
                            }
                            Anchor::BottomLeft | Anchor::BottomRight | Anchor::BottomCenter => {
                                NOTIFICATION_TRANSITION_OFFSET
                                    - delta * NOTIFICATION_TRANSITION_OFFSET
                            }
                            _ => px(0.),
                        };
                        let opacity = delta;
                        // GPUI paints a drop shadow *under* the card and has no
                        // group compositing, so a card that is still translucent
                        // does not hide its own shadow and it shows through as a
                        // dark slab. Ramping the ink by the cube of the fade
                        // keeps it out of sight until the card can cover it —
                        // where this used to drop the shadow outright past a
                        // threshold, which popped.
                        this.top(px(0.) + y_offset)
                            .opacity(opacity)
                            .shadow(toast_shadow(opacity.powi(3)))
                    }
                },
            )
    }
}

/// The settings for notifications.
#[derive(Debug, Clone)]
#[non_exhaustive]
pub struct NotificationSettings {
    /// The placement of the notifications, default: [`Anchor::TopRight`]
    ///
    /// A single notification can override this with [`Notification::placement`].
    pub placement: Anchor,
    /// The margins of the notification with respect to the window edges.
    pub margins: Edges<Pixels>,
    /// The maximum number of notifications to show at once, default: 10
    pub max_items: usize,
    /// The width of the notifications, default: 382px
    pub width: Pixels,
    /// Where notifications are delivered, default: [`NotificationDelivery::InApp`]
    ///
    /// A single notification can override this with [`Notification::delivery`].
    pub delivery: NotificationDelivery,
}

impl Default for NotificationSettings {
    fn default() -> Self {
        let offset = px(16.);
        Self {
            placement: Anchor::TopRight,
            margins: Edges {
                top: TITLE_BAR_HEIGHT + offset, // avoid overlap with title bar
                right: offset,
                bottom: offset,
                left: offset,
            },
            max_items: 10,
            width: DEFAULT_NOTIFICATION_WIDTH,
            delivery: NotificationDelivery::default(),
        }
    }
}

/// Registers the app-global system-notification response handler.
///
/// gpui keeps a single such handler (later registrations replace earlier
/// ones), so gpui-component owns it: applications must not call
/// [`gpui::App::on_system_notification_response`] after `gpui_component::init`.
/// Responses to notifications the application posts itself are ignored here.
pub(crate) fn init(cx: &mut App) {
    cx.on_system_notification_response(SystemNotificationRegistry::handle_response);
}

struct SystemNotificationEntry {
    window: AnyWindowHandle,
    list: WeakEntity<NotificationList>,
    id: NotificationId,
    on_click: Option<Rc<dyn Fn(&ClickEvent, &mut Window, &mut App)>>,
}

const MAX_SYSTEM_NOTIFICATION_ENTRIES: usize = 100;

/// App-global map from system-notification tag to the state needed to
/// dispatch the user's response, ordered oldest-first so overflow prunes the
/// stalest entries.
#[derive(Default)]
struct SystemNotificationRegistry {
    entries: Vec<(SharedString, SystemNotificationEntry)>,
}

impl Global for SystemNotificationRegistry {}

impl SystemNotificationRegistry {
    fn insert(cx: &mut App, tag: SharedString, entry: SystemNotificationEntry) {
        let entries = &mut cx.default_global::<Self>().entries;
        entries.retain(|(existing, _)| *existing != tag);
        entries.push((tag, entry));
        if entries.len() > MAX_SYSTEM_NOTIFICATION_ENTRIES {
            let overflow = entries.len() - MAX_SYSTEM_NOTIFICATION_ENTRIES;
            entries.drain(..overflow);
        }
    }

    /// Retract the system notification for `id`, but only if it was posted
    /// from the given window: another window pushing the same id owns the tag
    /// now, and this window's local dismiss must not clobber it.
    fn dismiss(cx: &mut App, id: &NotificationId, window_id: WindowId) {
        let tag = id.system_tag();
        let entries = &mut cx.default_global::<Self>().entries;
        let Some(ix) = entries.iter().position(|(existing, entry)| {
            *existing == tag && entry.window.window_id() == window_id
        }) else {
            return;
        };
        entries.remove(ix);
        cx.dismiss_system_notification(&tag);
    }

    /// Retract all of the window's system notifications whose id matches the
    /// given [`TypeId`], regardless of the [`NotificationId`] variant.
    fn dismiss_by_type(cx: &mut App, type_id: TypeId, window_id: WindowId) {
        Self::dismiss_matching(cx, window_id, |id| match id {
            NotificationId::Id(t) | NotificationId::IdAndElementId(t, _) => *t == type_id,
        });
    }

    /// Retract all system notifications posted from the given window.
    fn dismiss_all(cx: &mut App, window_id: WindowId) {
        Self::dismiss_matching(cx, window_id, |_| true);
    }

    fn dismiss_matching(
        cx: &mut App,
        window_id: WindowId,
        matches: impl Fn(&NotificationId) -> bool,
    ) {
        let entries = &mut cx.default_global::<Self>().entries;
        let mut tags = Vec::new();
        entries.retain(|(tag, entry)| {
            if entry.window.window_id() == window_id && matches(&entry.id) {
                tags.push(tag.clone());
                false
            } else {
                true
            }
        });
        for tag in tags {
            cx.dismiss_system_notification(&tag);
        }
    }

    fn handle_response(response: SystemNotificationResponse, cx: &mut App) {
        if !response.tag.starts_with(SYSTEM_TAG_PREFIX) {
            return;
        }
        // Platforms usually remove a clicked notification themselves; retract
        // explicitly for the ones that keep it in the notification center.
        cx.dismiss_system_notification(&response.tag);
        // The prefix already proves the notification is ours, so activate even
        // when nothing is left to dispatch to: the platform can deliver a
        // response for a notification posted before the process restarted, and
        // entries are pruned past `MAX_SYSTEM_NOTIFICATION_ENTRIES`.
        cx.activate(true);
        let entries = &mut cx.default_global::<Self>().entries;
        let Some(ix) = entries.iter().position(|(tag, _)| *tag == response.tag) else {
            return;
        };
        let (_, entry) = entries.remove(ix);
        // Errs when the window is already closed: the entry is removed and the
        // application is still brought to the foreground.
        let _ = entry.window.update(cx, |_, window, cx| {
            window.activate_window();
            if let Some(list) = entry.list.upgrade() {
                // No-op when the toast already closed or was never created
                // (system-only delivery).
                list.update(cx, |list, cx| list.close(entry.id.clone(), window, cx));
            }
            if let Some(on_click) = entry.on_click {
                on_click(&ClickEvent::default(), window, cx);
            }
        });
    }
}

/// Per-placement stack state, created lazily for placements in use.
struct AnchorStack {
    state: ToastStackState,
    focus_handle: FocusHandle,
}

/// A list of notifications.
pub struct NotificationList {
    /// Notifications that will be auto hidden.
    pub(crate) notifications: ToastManager<NotificationId, Entity<Notification>>,
    stacks: Vec<(Anchor, AnchorStack)>,
    focus_handle: FocusHandle,
    /// Mounted notifications that hide themselves after a timeout.
    autohide_ids: HashSet<NotificationId>,
    /// Whether the lifecycle clock is running. The loop clears it as it exits.
    is_advancing: bool,
    _subscriptions: HashMap<NotificationId, Subscription>,
}

impl NotificationList {
    pub fn new(_: &mut Window, cx: &mut Context<Self>) -> Self {
        Self {
            notifications: ToastManager::new(ToastMotion::sonner()),
            stacks: Vec::new(),
            focus_handle: cx.focus_handle().tab_stop(true),
            autohide_ids: HashSet::new(),
            is_advancing: false,
            _subscriptions: HashMap::new(),
        }
    }

    /// Tick the toast lifecycle while a notification still has time to track.
    ///
    /// It advances the transition phases and samples the pause input (stack
    /// expansion) that reaches the list through no event.
    /// With nothing mounted, or only persistent notifications at rest, there is
    /// nothing to do, so the window arms no timer until a push or close.
    fn start_advancing(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        if self.is_advancing {
            return;
        }
        self.is_advancing = true;
        // Detached rather than kept as a `Task`: the loop ends itself, and a
        // handle on the list would have to be dropped from inside its own future.
        cx.spawn_in(window, async move |view, cx| {
            loop {
                cx.background_executor()
                    .timer(NOTIFICATION_ADVANCE_INTERVAL)
                    .await;
                let running = view.update_in(cx, |view, window, cx| {
                    view.advance(window, cx);
                    view.is_advancing = view.needs_clock();
                    view.is_advancing
                });
                if !matches!(running, Ok(true)) {
                    break;
                }
            }
        })
        .detach();
    }

    /// Whether a mounted notification is in transition or counting down to
    /// autohide. A paused countdown still needs its last sample kept current.
    fn needs_clock(&self) -> bool {
        self.notifications
            .iter()
            .any(|(id, _, status)| match status {
                ToastTransitionStatus::Present => self.autohide_ids.contains(id),
                ToastTransitionStatus::Starting | ToastTransitionStatus::Ending => true,
            })
    }

    fn is_expanded(&self) -> bool {
        self.stacks
            .iter()
            .any(|(_, stack)| stack.state.is_expanded())
    }

    /// Group the visible notifications by their effective placement, pairing
    /// each group with the element id its stack renders under and preserving
    /// the display order within each group.
    fn grouped(
        &self,
        cx: &App,
    ) -> Vec<(
        Anchor,
        ElementId,
        Vec<(NotificationId, Entity<Notification>)>,
    )> {
        let settings = &cx.theme().notification;
        let (max_items, placement) = (settings.max_items, settings.placement);

        let mut groups: Vec<(Anchor, Vec<(NotificationId, Entity<Notification>)>)> = Vec::new();
        for (id, item, _) in self.notifications.visible(max_items) {
            let anchor = item.read(cx).placement.unwrap_or(placement);
            match groups.iter_mut().find(|(a, _)| *a == anchor) {
                Some((_, items)) => items.push((id.clone(), item.clone())),
                None => groups.push((anchor, vec![(id.clone(), item.clone())])),
            }
        }
        groups
            .into_iter()
            .map(|(anchor, items)| (anchor, Self::stack_id(anchor), items))
            .collect()
    }

    /// The element id a placement's stack renders under.
    ///
    /// Keyed by the placement itself rather than by position among the mounted
    /// stacks: a stack whose id changes loses the element state of its whole
    /// subtree, which replays the enter animation of every notification in it.
    fn stack_id(anchor: Anchor) -> ElementId {
        let ix = match anchor {
            Anchor::TopLeft => 0,
            Anchor::TopCenter => 1,
            Anchor::TopRight => 2,
            Anchor::BottomLeft => 3,
            Anchor::BottomCenter => 4,
            Anchor::BottomRight => 5,
            Anchor::LeftCenter => 6,
            Anchor::RightCenter => 7,
        };
        ("notification-list", ix as usize).into()
    }

    pub fn push(
        &mut self,
        notification: impl Into<Notification>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let notification = notification.into();
        let delivery = notification
            .delivery
            .unwrap_or(cx.theme().notification.delivery);
        if delivery.includes_system() {
            Self::push_system(&notification, window, cx);
        }
        if !delivery.includes_in_app() {
            return;
        }

        let id = notification.id.clone();
        let autohide = notification.autohide;
        let window_id = window.window_handle().window_id();

        let notification = cx.new(|_| notification);

        let dismiss_id = id.clone();
        self._subscriptions.insert(
            id.clone(),
            cx.subscribe_in(
                &notification,
                window,
                move |view, _, _: &DismissRequest, window, cx| {
                    if view
                        .notifications
                        .dismiss(&dismiss_id, cx.background_executor().now())
                    {
                        if let Some(note) = view.notifications.get(&dismiss_id) {
                            note.update(cx, |note, cx| note.begin_close(cx));
                        }
                        SystemNotificationRegistry::dismiss(cx, &dismiss_id, window_id);
                        view.start_advancing(window, cx);
                    }
                },
            ),
        );
        if autohide {
            self.autohide_ids.insert(id.clone());
        } else {
            self.autohide_ids.remove(&id);
        }

        self.notifications.push(
            id,
            notification,
            ToastOptions {
                timeout: autohide.then_some(Duration::from_secs(5)),
            },
            cx.background_executor().now(),
        );
        self.start_advancing(window, cx);
        cx.notify();
    }

    /// Post the notification to the OS notification center and register the
    /// state needed to dispatch the user's response back to this window.
    fn push_system(notification: &Notification, window: &Window, cx: &mut Context<Self>) {
        let (title, body) = match (&notification.title, &notification.message) {
            (Some(title), message) => (title.clone(), message.clone().unwrap_or_default()),
            (None, Some(message)) => (message.clone(), SharedString::default()),
            // A content-only notification has nothing textual to show.
            (None, None) => return,
        };
        let tag = notification.id.system_tag();
        let entry = SystemNotificationEntry {
            window: window.window_handle(),
            list: cx.entity().downgrade(),
            id: notification.id.clone(),
            on_click: notification.on_click.clone(),
        };
        SystemNotificationRegistry::insert(cx, tag.clone(), entry);
        cx.show_system_notification(SystemNotification {
            tag,
            title,
            body,
            actions: Vec::new(),
        });
    }

    fn advance(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let changes = self
            .notifications
            .advance(cx.background_executor().now(), self.is_expanded());
        for id in changes.presented {
            if let Some(note) = self.notifications.get(&id) {
                note.update(cx, |note, cx| note.complete_enter(cx));
            }
        }
        for id in changes.ending {
            if let Some(note) = self.notifications.get(&id) {
                note.update(cx, |note, cx| note.begin_close(cx));
            }
        }
        for (id, note) in changes.removed {
            self._subscriptions.remove(&id);
            self.autohide_ids.remove(&id);
            note.update(cx, |note, cx| note.complete_close(window, cx));
        }
        if changes.changed {
            cx.notify();
        }
    }

    pub(crate) fn close(
        &mut self,
        id: impl Into<NotificationId>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let id: NotificationId = id.into();
        // Unconditional: a system-only notification has no toast to dismiss,
        // but its system counterpart must still be retracted.
        SystemNotificationRegistry::dismiss(cx, &id, window.window_handle().window_id());
        if self
            .notifications
            .dismiss(&id, cx.background_executor().now())
        {
            if let Some(n) = self.notifications.get(&id) {
                n.update(cx, |note, cx| note.begin_close(cx))
            }
            self.start_advancing(window, cx);
        }
        cx.notify();
    }

    /// Close all notifications whose id matches the given [`TypeId`], regardless of
    /// whether they were registered via [`Notification::id`] or [`Notification::id1`].
    pub(crate) fn close_by_type(
        &mut self,
        type_id: TypeId,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        SystemNotificationRegistry::dismiss_by_type(
            cx,
            type_id,
            window.window_handle().window_id(),
        );
        let matched: Vec<_> = self
            .notifications
            .iter()
            .filter(|(id, _, _)| match id {
                NotificationId::Id(t) | NotificationId::IdAndElementId(t, _) => *t == type_id,
            })
            .map(|(_, notification, _)| notification)
            .cloned()
            .collect();
        for n in matched {
            let id = n.read(cx).id.clone();
            if self
                .notifications
                .dismiss(&id, cx.background_executor().now())
            {
                n.update(cx, |note, cx| note.begin_close(cx));
                self.start_advancing(window, cx);
            }
        }
        cx.notify();
    }

    pub fn clear(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        SystemNotificationRegistry::dismiss_all(cx, window.window_handle().window_id());
        for id in self
            .notifications
            .dismiss_all(cx.background_executor().now())
        {
            if let Some(note) = self.notifications.get(&id) {
                note.update(cx, |note, cx| note.begin_close(cx));
            }
            self.start_advancing(window, cx);
        }
        cx.notify();
    }

    pub fn notifications(&self) -> Vec<Entity<Notification>> {
        self.notifications
            .iter()
            .map(|(_, value, _)| value.clone())
            .collect()
    }
}

impl Render for NotificationList {
    fn render(
        &mut self,
        window: &mut gpui::Window,
        cx: &mut gpui::Context<Self>,
    ) -> impl IntoElement {
        let size = window.fully_visible_bounds().size;
        let settings = &cx.theme().notification;
        let (placement, margins, width) =
            (settings.placement, settings.margins.clone(), settings.width);

        let groups = self.grouped(cx);
        self.stacks
            .retain(|(anchor, _)| groups.iter().any(|(a, _, _)| a == anchor));

        let default_focus_handle = self.focus_handle.clone();
        let stacks = groups.into_iter().map(|(anchor, stack_id, items)| {
            let stack_ix = self
                .stacks
                .iter()
                .position(|(a, _)| *a == anchor)
                .unwrap_or_else(|| {
                    self.stacks.push((
                        anchor,
                        AnchorStack {
                            state: ToastStackState::default(),
                            focus_handle: if anchor == placement {
                                default_focus_handle.clone()
                            } else {
                                cx.focus_handle().tab_stop(true)
                            },
                        },
                    ));
                    self.stacks.len() - 1
                });
            let stack = &self.stacks[stack_ix].1;

            items
                .into_iter()
                .fold(
                    ToastStack::new(stack_id, stack.state.clone()),
                    |stack, (id, item)| stack.item(format!("{id:?}"), item),
                )
                .placement(anchor)
                .focus_handle(stack.focus_handle.clone())
                .v_flex()
                .w(width)
                .max_h(size.height)
                .absolute()
                .map(|this| match anchor {
                    Anchor::TopLeft => this.top(margins.top).left(margins.left),
                    Anchor::TopRight => this.top(margins.top).right(margins.right),
                    Anchor::TopCenter => this.top(margins.top).left(relative(0.5)).ml(-width / 2.),
                    Anchor::BottomLeft => this.bottom(margins.bottom).left(margins.left),
                    Anchor::BottomRight => this.bottom(margins.bottom).right(margins.right),
                    Anchor::BottomCenter => this
                        .bottom(margins.bottom)
                        .left(relative(0.5))
                        .ml(-width / 2.),
                    Anchor::LeftCenter => this.left(margins.left).top_0().bottom_0().my_auto(),
                    Anchor::RightCenter => this.right(margins.right).top_0().bottom_0().my_auto(),
                })
        });

        div().size_full().children(stacks)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::theme::Theme;
    use gpui::{TestAppContext, VisualTestContext};

    struct FooKind;
    struct BarKind;

    struct TestRoot {
        list: Entity<NotificationList>,
        other_focus: FocusHandle,
    }

    impl Render for TestRoot {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div()
                .child(self.list.clone())
                .child(div().track_focus(&self.other_focus))
        }
    }

    fn ids(list: &Entity<NotificationList>, cx: &mut VisualTestContext) -> Vec<NotificationId> {
        list.read_with(cx, |l, cx| {
            l.notifications
                .iter()
                .map(|(_, n, _)| n.read(cx).id.clone())
                .collect()
        })
    }

    /// Drive the dismiss animation timer + propagate the resulting `DismissEvent`
    /// so that closed notifications are removed from the list.
    fn flush_dismiss(cx: &mut VisualTestContext) {
        cx.background_executor
            .advance_clock(NOTIFICATION_EXIT_DURATION + Duration::from_millis(50));
        cx.run_until_parked();
    }

    #[test]
    fn test_notification_builder() {
        let note = Notification::new()
            .title("title")
            .message("message")
            .with_type(NotificationType::Success)
            .placement(Anchor::BottomLeft)
            .delivery(NotificationDelivery::System)
            .autohide(false);
        assert_eq!(note.title, Some("title".into()));
        assert_eq!(note.message, Some("message".into()));
        assert!(matches!(note.type_, Some(NotificationType::Success)));
        assert_eq!(note.placement, Some(Anchor::BottomLeft));
        assert_eq!(note.delivery, Some(NotificationDelivery::System));
        assert!(!note.autohide);

        assert_eq!(Notification::new().delivery, None);
        assert_eq!(
            Notification::new().system().delivery,
            Some(NotificationDelivery::System)
        );
        assert_eq!(
            Notification::new().in_app_and_system().delivery,
            Some(NotificationDelivery::InAppAndSystem)
        );
    }

    #[test]
    fn notification_delivery_includes() {
        assert!(NotificationDelivery::InApp.includes_in_app());
        assert!(!NotificationDelivery::InApp.includes_system());
        assert!(!NotificationDelivery::System.includes_in_app());
        assert!(NotificationDelivery::System.includes_system());
        assert!(NotificationDelivery::InAppAndSystem.includes_in_app());
        assert!(NotificationDelivery::InAppAndSystem.includes_system());
    }

    #[test]
    fn system_tag_is_stable_and_namespaced() {
        let by_type = NotificationId::from(TypeId::of::<FooKind>());
        assert_eq!(by_type.system_tag(), by_type.clone().system_tag());
        assert!(by_type.system_tag().starts_with(SYSTEM_TAG_PREFIX));

        let key1 = NotificationId::from((TypeId::of::<FooKind>(), ElementId::from(1usize)));
        let key2 = NotificationId::from((TypeId::of::<FooKind>(), ElementId::from(2usize)));
        assert_ne!(key1.system_tag(), key2.system_tag());
        assert_ne!(by_type.system_tag(), key1.system_tag());

        // Default (uuid) ids never collide, so they never replace each other.
        assert_ne!(
            Notification::new().id.system_tag(),
            Notification::new().id.system_tag()
        );
    }

    /// A stack's element id must not depend on how many other placements are
    /// mounted: a changing id drops the element state of the whole subtree,
    /// which replays each notification's enter animation.
    #[gpui::test]
    fn stack_element_id_survives_other_placements_disappearing(cx: &mut TestAppContext) {
        cx.update(|cx| cx.set_global(Theme::default()));
        let (root, cx) = cx.add_window_view(|window, cx| TestRoot {
            list: cx.new(|cx| NotificationList::new(window, cx)),
            other_focus: cx.focus_handle(),
        });
        cx.update(|window, _| window.activate_window());
        let list = root.read_with(cx, |root, _| root.list.clone());

        // The left stack is pushed first, so it owns the lower group index.
        list.update_in(cx, |list, window, cx| {
            list.push(
                Notification::info("left")
                    .id::<FooKind>()
                    .placement(Anchor::BottomLeft)
                    .autohide(false),
                window,
                cx,
            );
            list.push(
                Notification::info("right").id::<BarKind>().autohide(false),
                window,
                cx,
            );
        });

        let right_id = |cx: &mut VisualTestContext| {
            list.read_with(cx, |list, cx| {
                list.grouped(cx)
                    .into_iter()
                    .find(|(anchor, _, _)| *anchor == Anchor::TopRight)
                    .map(|(_, id, _)| id)
                    .expect("the right stack is mounted")
            })
        };
        let before = right_id(cx);

        list.update_in(cx, |list, window, cx| {
            list.close(TypeId::of::<FooKind>(), window, cx);
        });
        flush_dismiss(cx);

        assert_eq!(right_id(cx), before);
    }

    #[gpui::test]
    fn per_notification_placement_stacks_by_anchor(cx: &mut TestAppContext) {
        cx.update(|cx| cx.set_global(Theme::default()));
        let (root, cx) = cx.add_window_view(|window, cx| TestRoot {
            list: cx.new(|cx| NotificationList::new(window, cx)),
            other_focus: cx.focus_handle(),
        });
        cx.update(|window, _| window.activate_window());
        let list = root.read_with(cx, |root, _| root.list.clone());

        list.update_in(cx, |list, window, cx| {
            list.push(
                Notification::info("default")
                    .id::<FooKind>()
                    .autohide(false),
                window,
                cx,
            );
            list.push(
                Notification::info("bottom")
                    .id::<BarKind>()
                    .placement(Anchor::BottomLeft)
                    .autohide(false),
                window,
                cx,
            );
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));

        let anchors =
            |list: &NotificationList| list.stacks.iter().map(|(a, _)| *a).collect::<Vec<_>>();
        assert_eq!(
            list.read_with(cx, |list, _| anchors(list)),
            [Anchor::TopRight, Anchor::BottomLeft]
        );

        // Dismissing the overridden notification prunes its stack.
        list.update_in(cx, |list, window, cx| {
            list.close(TypeId::of::<BarKind>(), window, cx);
        });
        flush_dismiss(cx);
        cx.update(|window, cx| window.draw(cx).clear(cx));
        assert_eq!(
            list.read_with(cx, |list, _| anchors(list)),
            [Anchor::TopRight]
        );
    }

    #[gpui::test]
    fn closing_toast_stays_mounted_until_its_transition_finishes(cx: &mut TestAppContext) {
        cx.update(|cx| cx.set_global(Theme::default()));
        let (root, cx) = cx.add_window_view(|window, cx| TestRoot {
            list: cx.new(|cx| NotificationList::new(window, cx)),
            other_focus: cx.focus_handle(),
        });
        cx.update(|window, _| window.activate_window());
        let list = root.read_with(cx, |root, _| root.list.clone());

        list.update_in(cx, |list, window, cx| {
            list.push(
                Notification::info("closing")
                    .id::<FooKind>()
                    .autohide(false),
                window,
                cx,
            );
            list.close(TypeId::of::<FooKind>(), window, cx);
        });

        cx.background_executor
            .advance_clock(NOTIFICATION_EXIT_DURATION - Duration::from_millis(1));
        cx.run_until_parked();
        assert_eq!(ids(&list, cx).len(), 1);

        cx.background_executor
            .advance_clock(Duration::from_millis(1));
        cx.run_until_parked();
        assert!(ids(&list, cx).is_empty());
    }

    #[gpui::test]
    fn lifecycle_clock_runs_only_while_a_notification_is_mounted(cx: &mut TestAppContext) {
        cx.update(|cx| cx.set_global(Theme::default()));
        let (root, cx) = cx.add_window_view(|window, cx| TestRoot {
            list: cx.new(|cx| NotificationList::new(window, cx)),
            other_focus: cx.focus_handle(),
        });
        cx.update(|window, _| window.activate_window());
        let list = root.read_with(cx, |root, _| root.list.clone());

        // A list that has never shown anything arms no timer.
        cx.background_executor.advance_clock(Duration::from_secs(1));
        cx.run_until_parked();
        assert!(!list.read_with(cx, |list, _| list.is_advancing));

        list.update_in(cx, |list, window, cx| {
            list.push(Notification::info("tick").id::<FooKind>(), window, cx);
        });
        assert!(list.read_with(cx, |list, _| list.is_advancing));

        // Autohide expiry plus the exit transition stops the clock with it.
        cx.background_executor
            .advance_clock(NOTIFICATION_TRANSITION_DURATION + Duration::from_secs(5));
        cx.run_until_parked();
        flush_dismiss(cx);
        assert!(ids(&list, cx).is_empty());
        assert!(!list.read_with(cx, |list, _| list.is_advancing));

        // A later notification restarts it.
        list.update_in(cx, |list, window, cx| {
            list.push(Notification::info("again").id::<BarKind>(), window, cx);
        });
        assert!(list.read_with(cx, |list, _| list.is_advancing));
        cx.background_executor
            .advance_clock(NOTIFICATION_TRANSITION_DURATION + Duration::from_secs(5));
        cx.run_until_parked();
        flush_dismiss(cx);
        assert!(ids(&list, cx).is_empty());
        assert!(!list.read_with(cx, |list, _| list.is_advancing));
    }

    #[gpui::test]
    fn lifecycle_clock_rests_while_only_persistent_notifications_are_shown(
        cx: &mut TestAppContext,
    ) {
        cx.update(|cx| cx.set_global(Theme::default()));
        let (root, cx) = cx.add_window_view(|window, cx| TestRoot {
            list: cx.new(|cx| NotificationList::new(window, cx)),
            other_focus: cx.focus_handle(),
        });
        cx.update(|window, _| window.activate_window());
        let list = root.read_with(cx, |root, _| root.list.clone());

        list.update_in(cx, |list, window, cx| {
            list.push(
                Notification::info("first").id::<FooKind>().autohide(false),
                window,
                cx,
            );
            list.push(
                Notification::info("second").id::<BarKind>().autohide(false),
                window,
                cx,
            );
        });
        assert!(list.read_with(cx, |list, _| list.is_advancing));

        // Once both have entered, nothing is left to time.
        cx.background_executor
            .advance_clock(NOTIFICATION_TRANSITION_DURATION + NOTIFICATION_ADVANCE_INTERVAL);
        cx.run_until_parked();
        assert!(!list.read_with(cx, |list, _| list.is_advancing));
        assert_eq!(ids(&list, cx).len(), 2);

        // A programmatic close restarts the clock to finish the exit.
        list.update_in(cx, |list, window, cx| {
            list.close(TypeId::of::<FooKind>(), window, cx);
        });
        assert!(list.read_with(cx, |list, _| list.is_advancing));
        flush_dismiss(cx);
        assert_eq!(
            ids(&list, cx),
            [NotificationId::from(TypeId::of::<BarKind>())]
        );
        assert!(!list.read_with(cx, |list, _| list.is_advancing));

        // So does a dismiss requested by the notification itself.
        let note = list.read_with(cx, |list, _| list.notifications()[0].clone());
        note.update_in(cx, |note, window, cx| note.dismiss(window, cx));
        cx.run_until_parked();
        assert!(list.read_with(cx, |list, _| list.is_advancing));
        flush_dismiss(cx);
        assert!(ids(&list, cx).is_empty());
        assert!(!list.read_with(cx, |list, _| list.is_advancing));
    }

    #[gpui::test]
    fn inactive_window_does_not_pause_autohide(cx: &mut TestAppContext) {
        cx.update(|cx| cx.set_global(Theme::default()));
        let (root, cx) = cx.add_window_view(|window, cx| TestRoot {
            list: cx.new(|cx| NotificationList::new(window, cx)),
            other_focus: cx.focus_handle(),
        });
        let list = root.read_with(cx, |root, _| root.list.clone());
        list.update_in(cx, |list, window, cx| {
            assert!(!window.is_window_active());
            list.push(Notification::info("background").id::<FooKind>(), window, cx);
        });

        cx.background_executor
            .advance_clock(NOTIFICATION_TRANSITION_DURATION);
        cx.run_until_parked();
        let note = list.read_with(cx, |list, _| {
            list.notifications
                .get(&NotificationId::from(TypeId::of::<FooKind>()))
                .unwrap()
                .clone()
        });
        assert_eq!(
            note.read_with(cx, |note, _| note.transition_status),
            ToastTransitionStatus::Present
        );

        cx.background_executor
            .advance_clock(Duration::from_secs(5) + Duration::from_millis(50));
        cx.run_until_parked();
        assert_eq!(
            note.read_with(cx, |note, _| note.transition_status),
            ToastTransitionStatus::Ending
        );
    }

    #[gpui::test]
    fn focus_pauses_autohide_and_present_phase_is_projected(cx: &mut TestAppContext) {
        cx.update(|cx| cx.set_global(Theme::default()));
        let (root, cx) = cx.add_window_view(|window, cx| TestRoot {
            list: cx.new(|cx| NotificationList::new(window, cx)),
            other_focus: cx.focus_handle(),
        });
        let list = root.read_with(cx, |root, _| root.list.clone());
        list.update_in(cx, |list, window, cx| {
            list.push(Notification::info("paused").id::<FooKind>(), window, cx);
        });

        cx.background_executor
            .advance_clock(NOTIFICATION_TRANSITION_DURATION);
        cx.run_until_parked();
        let note = list.read_with(cx, |list, _| {
            list.notifications
                .get(&NotificationId::from(TypeId::of::<FooKind>()))
                .unwrap()
                .clone()
        });
        assert_eq!(
            note.read_with(cx, |note, _| note.transition_status),
            ToastTransitionStatus::Present
        );

        let list_focus = list.read_with(cx, |list, _| list.focus_handle.clone());
        cx.update(|window, cx| {
            list_focus.focus(window, cx);
            window.draw(cx).clear(cx);
        });
        cx.background_executor.advance_clock(Duration::from_secs(5));
        cx.run_until_parked();
        assert_eq!(
            note.read_with(cx, |note, _| note.transition_status),
            ToastTransitionStatus::Present
        );

        let other_focus = root.read_with(cx, |root, _| root.other_focus.clone());
        cx.update(|window, cx| {
            other_focus.focus(window, cx);
            window.draw(cx).clear(cx);
        });
        assert!(!list.read_with(cx, |list, _| list.is_expanded()));
        cx.background_executor
            .advance_clock(Duration::from_secs(5) + Duration::from_millis(50));
        cx.run_until_parked();
        assert_eq!(
            note.read_with(cx, |note, _| note.transition_status),
            ToastTransitionStatus::Ending
        );
    }

    #[gpui::test]
    fn close_by_type_removes_id_and_all_id1_of_same_type(cx: &mut TestAppContext) {
        cx.update(|cx| cx.set_global(Theme::default()));
        let (root, cx) = cx.add_window_view(|window, cx| TestRoot {
            list: cx.new(|cx| NotificationList::new(window, cx)),
            other_focus: cx.focus_handle(),
        });
        let list = root.read_with(cx, |r, _| r.list.clone());

        list.update_in(cx, |list, window, cx| {
            list.push(
                Notification::info("plain").id::<FooKind>().autohide(false),
                window,
                cx,
            );
            list.push(
                Notification::info("a").id1::<FooKind>(1).autohide(false),
                window,
                cx,
            );
            list.push(
                Notification::info("b").id1::<FooKind>(2).autohide(false),
                window,
                cx,
            );
            list.push(
                Notification::info("bar").id::<BarKind>().autohide(false),
                window,
                cx,
            );
        });
        cx.run_until_parked();
        assert_eq!(ids(&list, cx).len(), 4);

        list.update_in(cx, |list, window, cx| {
            list.close_by_type(TypeId::of::<FooKind>(), window, cx);
        });
        flush_dismiss(cx);

        let remaining = ids(&list, cx);
        assert_eq!(
            remaining,
            vec![NotificationId::Id(TypeId::of::<BarKind>())],
            "only the BarKind notification should survive"
        );
    }

    #[gpui::test]
    fn close_with_id_and_element_id_removes_only_matching_key(cx: &mut TestAppContext) {
        cx.update(|cx| cx.set_global(Theme::default()));
        let (root, cx) = cx.add_window_view(|window, cx| TestRoot {
            list: cx.new(|cx| NotificationList::new(window, cx)),
            other_focus: cx.focus_handle(),
        });
        let list = root.read_with(cx, |r, _| r.list.clone());

        list.update_in(cx, |list, window, cx| {
            list.push(
                Notification::info("a").id1::<FooKind>(1).autohide(false),
                window,
                cx,
            );
            list.push(
                Notification::info("b").id1::<FooKind>(2).autohide(false),
                window,
                cx,
            );
            list.push(
                Notification::info("plain").id::<FooKind>().autohide(false),
                window,
                cx,
            );
        });

        list.update_in(cx, |list, window, cx| {
            list.close(
                (TypeId::of::<FooKind>(), ElementId::from(1usize)),
                window,
                cx,
            );
        });
        flush_dismiss(cx);

        let remaining = ids(&list, cx);
        assert_eq!(remaining.len(), 2);
        assert!(remaining.contains(&NotificationId::IdAndElementId(
            TypeId::of::<FooKind>(),
            ElementId::from(2usize),
        )));
        assert!(remaining.contains(&NotificationId::Id(TypeId::of::<FooKind>())));
    }

    #[gpui::test]
    fn close_with_only_type_id_does_not_match_id1_entries(cx: &mut TestAppContext) {
        // The plain `close(TypeId)` form (used by the legacy code path) must keep
        // its narrow semantics: it only matches `NotificationId::Id`, not
        // `NotificationId::IdAndElementId`. The new `close_by_type` is the broad form.
        cx.update(|cx| cx.set_global(Theme::default()));
        let (root, cx) = cx.add_window_view(|window, cx| TestRoot {
            list: cx.new(|cx| NotificationList::new(window, cx)),
            other_focus: cx.focus_handle(),
        });
        let list = root.read_with(cx, |r, _| r.list.clone());

        list.update_in(cx, |list, window, cx| {
            list.push(
                Notification::info("a").id1::<FooKind>(1).autohide(false),
                window,
                cx,
            );
        });

        list.update_in(cx, |list, window, cx| {
            list.close(TypeId::of::<FooKind>(), window, cx);
        });
        flush_dismiss(cx);

        assert_eq!(ids(&list, cx).len(), 1, "id1 entry should remain untouched");
    }

    #[gpui::test]
    fn close_by_type_with_no_match_is_noop(cx: &mut TestAppContext) {
        cx.update(|cx| cx.set_global(Theme::default()));
        let (root, cx) = cx.add_window_view(|window, cx| TestRoot {
            list: cx.new(|cx| NotificationList::new(window, cx)),
            other_focus: cx.focus_handle(),
        });
        let list = root.read_with(cx, |r, _| r.list.clone());

        list.update_in(cx, |list, window, cx| {
            list.push(
                Notification::info("bar").id::<BarKind>().autohide(false),
                window,
                cx,
            );
        });

        list.update_in(cx, |list, window, cx| {
            list.close_by_type(TypeId::of::<FooKind>(), window, cx);
        });
        flush_dismiss(cx);

        assert_eq!(ids(&list, cx).len(), 1);
    }

    /// Applications may post their own system notifications; a response for
    /// one of those must not be retracted or dispatched by the library.
    #[gpui::test]
    fn response_for_a_foreign_tag_is_ignored(cx: &mut TestAppContext) {
        cx.update(|cx| {
            init(cx);
            cx.set_app_identity("com.example.test", "Test");
        });
        cx.simulate_system_notification_response(SystemNotificationResponse {
            tag: "com.example.app/own-tag".into(),
            action_id: None,
        });
        cx.run_until_parked();
        assert!(cx.dismissed_system_notifications().is_empty());
    }

    #[gpui::test]
    fn system_delivery_posts_to_center_without_in_app_toast(cx: &mut TestAppContext) {
        cx.update(|cx| {
            cx.set_global(Theme::default());
            init(cx);
            // The test platform drops posts until an identity is set,
            // mirroring Windows.
            cx.set_app_identity("com.example.test", "Test");
        });
        let (root, cx) = cx.add_window_view(|window, cx| TestRoot {
            list: cx.new(|cx| NotificationList::new(window, cx)),
            other_focus: cx.focus_handle(),
        });
        let list = root.read_with(cx, |r, _| r.list.clone());

        list.update_in(cx, |list, window, cx| {
            list.push(
                Notification::info("body text")
                    .title("Title")
                    .id::<FooKind>()
                    .delivery(NotificationDelivery::System),
                window,
                cx,
            );
            // Message-only: the message becomes the system title.
            list.push(
                Notification::info("message only")
                    .id::<BarKind>()
                    .delivery(NotificationDelivery::System),
                window,
                cx,
            );
        });
        cx.run_until_parked();

        let shown = cx.shown_system_notifications();
        assert_eq!(shown.len(), 2);
        assert_eq!(
            shown[0].tag,
            NotificationId::Id(TypeId::of::<FooKind>()).system_tag()
        );
        assert_eq!(shown[0].title, "Title");
        assert_eq!(shown[0].body, "body text");
        assert_eq!(shown[1].title, "message only");
        assert_eq!(shown[1].body, "");
        assert!(ids(&list, cx).is_empty(), "no in-app toast should exist");

        // System-only notifications are still retractable through the
        // regular close path even though no toast entity exists.
        list.update_in(cx, |list, window, cx| {
            list.close(TypeId::of::<FooKind>(), window, cx);
        });
        assert_eq!(
            cx.dismissed_system_notifications(),
            vec![NotificationId::Id(TypeId::of::<FooKind>()).system_tag()]
        );
    }

    #[gpui::test]
    fn system_click_activates_window_closes_toast_and_fires_on_click(cx: &mut TestAppContext) {
        cx.update(|cx| {
            cx.set_global(Theme::default());
            init(cx);
            cx.set_app_identity("com.example.test", "Test");
        });
        let (root, cx) = cx.add_window_view(|window, cx| TestRoot {
            list: cx.new(|cx| NotificationList::new(window, cx)),
            other_focus: cx.focus_handle(),
        });
        let list = root.read_with(cx, |r, _| r.list.clone());

        let clicked = Rc::new(std::cell::Cell::new(false));
        let on_click_flag = clicked.clone();
        list.update_in(cx, |list, window, cx| {
            list.push(
                Notification::info("message")
                    .title("Title")
                    .id::<FooKind>()
                    .delivery(NotificationDelivery::InAppAndSystem)
                    .autohide(false)
                    .on_click(move |_, _, _| on_click_flag.set(true)),
                window,
                cx,
            );
        });
        cx.run_until_parked();
        assert_eq!(ids(&list, cx).len(), 1);
        assert_eq!(cx.shown_system_notifications().len(), 1);

        cx.simulate_system_notification_response(SystemNotificationResponse {
            tag: NotificationId::Id(TypeId::of::<FooKind>()).system_tag(),
            action_id: None,
        });
        cx.run_until_parked();

        assert!(clicked.get(), "on_click should fire on system response");
        flush_dismiss(cx);
        assert!(
            ids(&list, cx).is_empty(),
            "the in-app counterpart should be closed"
        );
    }

    #[gpui::test]
    fn explicit_close_retracts_system_notification_but_autohide_does_not(cx: &mut TestAppContext) {
        cx.update(|cx| {
            cx.set_global(Theme::default());
            init(cx);
            cx.set_app_identity("com.example.test", "Test");
        });
        let (root, cx) = cx.add_window_view(|window, cx| TestRoot {
            list: cx.new(|cx| NotificationList::new(window, cx)),
            other_focus: cx.focus_handle(),
        });
        cx.update(|window, _| window.activate_window());
        let list = root.read_with(cx, |r, _| r.list.clone());

        // Autohide expiry leaves the system notification in the center.
        list.update_in(cx, |list, window, cx| {
            list.push(
                Notification::info("auto")
                    .id::<FooKind>()
                    .delivery(NotificationDelivery::InAppAndSystem),
                window,
                cx,
            );
        });
        cx.run_until_parked();
        cx.background_executor.advance_clock(Duration::from_secs(6));
        cx.run_until_parked();
        flush_dismiss(cx);
        assert!(
            ids(&list, cx).is_empty(),
            "the toast should have autohidden"
        );
        assert!(
            cx.dismissed_system_notifications().is_empty(),
            "autohide must not retract the system notification"
        );

        // An explicit close retracts it.
        list.update_in(cx, |list, window, cx| {
            list.push(
                Notification::info("manual")
                    .id::<BarKind>()
                    .delivery(NotificationDelivery::InAppAndSystem)
                    .autohide(false),
                window,
                cx,
            );
        });
        cx.run_until_parked();
        list.update_in(cx, |list, window, cx| {
            list.close(TypeId::of::<BarKind>(), window, cx);
        });
        flush_dismiss(cx);
        assert_eq!(
            cx.dismissed_system_notifications(),
            vec![NotificationId::Id(TypeId::of::<BarKind>()).system_tag()]
        );
    }
}
