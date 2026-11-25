use std::rc::Rc;

use chrono::{NaiveDate, NaiveDateTime, NaiveTime, Weekday};
use gpui::{
    App, AppContext, Bounds, ClickEvent, Context, ElementId, Empty, Entity, EventEmitter,
    FocusHandle, Focusable, InteractiveElement as _, IntoElement, KeyBinding, MouseButton,
    ParentElement as _, Pixels, Render, RenderOnce, SharedString, StatefulInteractiveElement as _,
    StyleRefinement, Styled, Subscription, Window, deferred, div, prelude::FluentBuilder as _, px,
};
use rust_i18n::t;

use crate::ThemeStyled as _;
use crate::{
    ActiveTheme, Disableable, Icon, IconName, Sizable, Size, StyleSized as _, StyledExt as _,
    actions::{Cancel, Confirm},
    button::{Button, ButtonVariants as _},
    h_flex,
    input::{Delete, clear_button, input_style},
    v_flex,
};

use super::calendar::{Calendar, CalendarEvent, CalendarState, Date, Matcher};
use super::time_field::{
    HourCycle, TimeField, TimeFieldEvent, TimeFieldState, TimePrecision, tabular_figures,
};
use gpui_base::{DatePicker as BaseDatePicker, ElementExt as _};

const CONTEXT: &'static str = "DatePicker";
pub(crate) fn init(cx: &mut App) {
    cx.bind_keys([
        KeyBinding::new("enter", Confirm { secondary: false }, Some(CONTEXT)),
        KeyBinding::new("escape", Cancel, Some(CONTEXT)),
        KeyBinding::new("delete", Delete, Some(CONTEXT)),
        KeyBinding::new("backspace", Delete, Some(CONTEXT)),
    ])
}

/// Events emitted by the DatePicker.
#[derive(Clone)]
pub enum DatePickerEvent {
    /// The user changed the value. With a time precision set, this is emitted
    /// on every edit while the popup stays open.
    Change(DateTime),
}

/// The value of a [`DatePicker`]: the selected date or dates combined with
/// their times of day.
///
/// When the picker has no time precision, every time is the picker's
/// [`DatePickerState::default_time`], `00:00` unless configured.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DateTime {
    Single(Option<NaiveDateTime>),
    Range(Option<NaiveDateTime>, Option<NaiveDateTime>),
}

impl From<NaiveDateTime> for DateTime {
    fn from(value: NaiveDateTime) -> Self {
        Self::Single(Some(value))
    }
}

impl From<(NaiveDateTime, NaiveDateTime)> for DateTime {
    fn from((start, end): (NaiveDateTime, NaiveDateTime)) -> Self {
        Self::Range(Some(start), Some(end))
    }
}

impl DateTime {
    pub fn is_some(&self) -> bool {
        self.date().is_some()
    }

    pub fn is_complete(&self) -> bool {
        self.date().is_complete()
    }

    pub fn start(&self) -> Option<NaiveDateTime> {
        match self {
            Self::Single(v) | Self::Range(v, _) => *v,
        }
    }

    pub fn end(&self) -> Option<NaiveDateTime> {
        match self {
            Self::Range(_, v) => *v,
            Self::Single(_) => None,
        }
    }

    /// The date part of this value.
    pub fn date(&self) -> Date {
        match self {
            Self::Single(v) => Date::Single(v.map(|v| v.date())),
            Self::Range(a, b) => Date::Range(a.map(|v| v.date()), b.map(|v| v.date())),
        }
    }

    /// Format a complete value, joining a range with ` - `.
    pub fn format(&self, format: &str) -> Option<SharedString> {
        match self {
            Self::Single(Some(v)) => Some(v.format(format).to_string().into()),
            Self::Range(Some(a), Some(b)) => {
                Some(format!("{} - {}", a.format(format), b.format(format)).into())
            }
            _ => None,
        }
    }
}

/// Preset value for DateRangePreset.
#[derive(Clone)]
pub enum DateRangePresetValue {
    Single(NaiveDate),
    Range(NaiveDate, NaiveDate),
    DateTime(DateTime),
}

/// Preset for date range selection.
#[derive(Clone)]
pub struct DateRangePreset {
    label: SharedString,
    value: DateRangePresetValue,
}

impl DateRangePreset {
    /// Creates a new DateRangePreset with a date.
    pub fn single(label: impl Into<SharedString>, date: NaiveDate) -> Self {
        DateRangePreset {
            label: label.into(),
            value: DateRangePresetValue::Single(date),
        }
    }
    /// Creates a new DateRangePreset with a range of dates.
    pub fn range(label: impl Into<SharedString>, start: NaiveDate, end: NaiveDate) -> Self {
        DateRangePreset {
            label: label.into(),
            value: DateRangePresetValue::Range(start, end),
        }
    }
    /// Creates a new DateRangePreset with a date and time, or a range of them.
    ///
    /// Times are kept as given, even though a range picker edits dates only.
    pub fn date_time(label: impl Into<SharedString>, value: impl Into<DateTime>) -> Self {
        DateRangePreset {
            label: label.into(),
            value: DateRangePresetValue::DateTime(value.into()),
        }
    }
}

/// Use to store the state of the date picker.
pub struct DatePickerState {
    focus_handle: FocusHandle,
    date: Date,
    open: bool,
    calendar: Entity<CalendarState>,
    date_format: Option<SharedString>,
    number_of_months: usize,
    disabled_matcher: Option<Rc<Matcher>>,
    /// `None` edits dates only.
    time_precision: Option<TimePrecision>,
    hour_cycle: HourCycle,
    default_time: NaiveTime,
    start_time: NaiveTime,
    /// The time of a range's end. Only [`DatePickerState::set_date_time`]
    /// sets it, since a range picker edits dates only.
    end_time: NaiveTime,
    time_field: Entity<TimeFieldState>,
    time_field_pushed: bool,
    _subscriptions: Vec<Subscription>,
    /// The first day of the week. Defaults to Sunday.
    first_day_of_week: Weekday,
    bounds: Bounds<Pixels>,
}

impl Focusable for DatePickerState {
    fn focus_handle(&self, _: &App) -> FocusHandle {
        self.focus_handle.clone()
    }
}
impl EventEmitter<DatePickerEvent> for DatePickerState {}

impl DatePickerState {
    /// Create a date state.
    pub fn new(window: &mut Window, cx: &mut Context<Self>) -> Self {
        Self::new_with_range(false, window, cx)
    }

    /// Create a date state with range mode.
    pub fn range(window: &mut Window, cx: &mut Context<Self>) -> Self {
        Self::new_with_range(true, window, cx)
    }

    fn new_with_range(is_range: bool, window: &mut Window, cx: &mut Context<Self>) -> Self {
        let date = if is_range {
            Date::Range(None, None)
        } else {
            Date::Single(None)
        };

        let calendar = cx.new(|cx| {
            let mut this = CalendarState::new(window, cx);
            this.set_date(date, window, cx);
            this
        });
        let time_field = cx.new(|cx| TimeFieldState::new(window, cx));

        let _subscriptions = vec![
            cx.subscribe_in(
                &calendar,
                window,
                |this, _, ev: &CalendarEvent, window, cx| match ev {
                    CalendarEvent::Selected(date) => {
                        this.select_date(*date, window, cx);
                    }
                },
            ),
            cx.subscribe_in(
                &time_field,
                window,
                |this, _, ev: &TimeFieldEvent, _, cx| match ev {
                    TimeFieldEvent::Change(time) => {
                        this.start_time = *time;
                        this.emit_change(cx);
                    }
                },
            ),
        ];

        Self {
            focus_handle: cx.focus_handle(),
            date,
            calendar,
            open: false,
            date_format: None,
            number_of_months: 1,
            disabled_matcher: None,
            time_precision: None,
            hour_cycle: HourCycle::default(),
            default_time: NaiveTime::MIN,
            start_time: NaiveTime::MIN,
            end_time: NaiveTime::MIN,
            time_field,
            time_field_pushed: false,
            _subscriptions,
            first_day_of_week: Weekday::Sun,
            bounds: Bounds::default(),
        }
    }

    /// Set the format of the value displayed in the picker.
    ///
    /// Default: `%Y/%m/%d`, followed by the time in the configured precision
    /// and hour cycle when the picker edits times, e.g. `%H:%M` or `%I:%M %p`.
    pub fn date_format(mut self, format: impl Into<SharedString>) -> Self {
        self.date_format = Some(format.into());
        self
    }

    /// Edit the time of day as well as the date, down to `precision`.
    ///
    /// Selecting a date then keeps the popup open, and every change to the
    /// date or time is reported as it happens. Clicking the selected date
    /// again closes the popup.
    ///
    /// A range picker edits dates only; for a range with times, place two
    /// single pickers side by side.
    pub fn time_precision(mut self, precision: TimePrecision) -> Self {
        self.time_precision = Some(precision);
        self.default_time = precision.truncate(self.default_time);
        self.start_time = precision.truncate(self.start_time);
        self.end_time = precision.truncate(self.end_time);
        self.time_field_pushed = false;
        self
    }

    /// Set how the time field counts hours, default: [`HourCycle::H23`].
    pub fn hour_cycle(mut self, hour_cycle: HourCycle) -> Self {
        self.hour_cycle = hour_cycle;
        self.time_field_pushed = false;
        self
    }

    /// Set the time given to a date before the user edits it, default: `00:00`.
    pub fn default_time(mut self, time: NaiveTime) -> Self {
        let time = self.truncate_time(time);
        self.default_time = time;
        self.start_time = time;
        self.end_time = time;
        self.time_field_pushed = false;
        self
    }

    /// Set the number of months calendar view to display, default is 1.
    pub fn number_of_months(mut self, number_of_months: usize) -> Self {
        self.number_of_months = number_of_months;
        self
    }

    /// Set the first day of the week.
    pub fn first_day_of_week(mut self, day: Weekday) -> Self {
        self.first_day_of_week = day;
        self
    }

    /// Get the date part of the value.
    pub fn date(&self) -> Date {
        self.date
    }

    /// Get the value, combining the date with its time of day.
    pub fn date_time(&self) -> DateTime {
        match self.date {
            Date::Single(date) => DateTime::Single(date.map(|d| d.and_time(self.start_time))),
            Date::Range(start, end) => DateTime::Range(
                start.map(|d| d.and_time(self.start_time)),
                end.map(|d| d.and_time(self.end_time)),
            ),
        }
    }

    /// Set the date, keeping the current time of day.
    pub fn set_date(&mut self, date: impl Into<Date>, window: &mut Window, cx: &mut Context<Self>) {
        self.update_date(date.into(), false, window, cx);
    }

    /// Set the date and the time of day.
    pub fn set_date_time(
        &mut self,
        value: impl Into<DateTime>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let value = value.into();
        let start = value.start().map_or(self.default_time, |v| v.time());
        let end = value.end().map_or(start, |v| v.time());
        self.set_times(start, end, window, cx);
        self.update_date(value.date(), false, window, cx);
    }

    /// Set the disabled match for the calendar.
    pub fn disabled_matcher(mut self, disabled: impl Into<Matcher>) -> Self {
        self.disabled_matcher = Some(Rc::new(disabled.into()));
        self
    }

    /// Set the year range for the internal calendar.
    ///
    /// Default is 50 years before and after the current year.
    /// `range` uses a half-open interval `(start, end)` where `end` is exclusive.
    pub fn set_year_range(&mut self, range: (i32, i32), cx: &mut Context<Self>) {
        self.calendar.update(cx, |state, cx| {
            state.set_year_range(range, cx);
        });
    }

    /// The precision the popup edits times at, or `None` when it edits dates only.
    fn edited_time_precision(&self) -> Option<TimePrecision> {
        self.time_precision.filter(|_| self.date.is_single())
    }

    fn truncate_time(&self, time: NaiveTime) -> NaiveTime {
        self.time_precision
            .map_or(time, |precision| precision.truncate(time))
    }

    fn set_times(
        &mut self,
        start: NaiveTime,
        end: NaiveTime,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.start_time = self.truncate_time(start);
        self.end_time = self.truncate_time(end);
        self.push_time_field(window, cx);
    }

    /// Push the configuration and the time into the time field.
    ///
    /// User edits flow the other way, through the field subscription, so this
    /// runs only when the picker's own time changes. Pushing on every render
    /// could overwrite an edit whose event has not been delivered yet.
    fn push_time_field(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let precision = self.time_precision.unwrap_or_default();
        let (hour_cycle, time) = (self.hour_cycle, self.start_time);
        self.time_field.update(cx, |field, cx| {
            field.set_precision(precision, window, cx);
            field.set_hour_cycle(hour_cycle, window, cx);
            field.set_time(time, window, cx);
        });
        self.time_field_pushed = true;
    }

    fn emit_change(&mut self, cx: &mut Context<Self>) {
        if self.date.is_complete() {
            cx.emit(DatePickerEvent::Change(self.date_time()));
        }
        cx.notify();
    }

    fn select_date(&mut self, date: Date, window: &mut Window, cx: &mut Context<Self>) {
        if self.edited_time_precision().is_some() {
            if date == self.date {
                // Clicking the selected day again confirms it, so picking a
                // date and closing is a double-click.
                self.set_open(false, window, cx);
                return;
            }
            // Keep the popup open so the time can be adjusted next.
            self.date = date;
            self.emit_change(cx);
        } else {
            self.update_date(date, true, window, cx);
            self.focus_handle.focus(window, cx);
        }
    }

    fn update_date(&mut self, date: Date, emit: bool, window: &mut Window, cx: &mut Context<Self>) {
        self.date = date;
        self.calendar.update(cx, |view, cx| {
            view.set_date(date, window, cx);
        });
        self.open = false;
        if emit {
            cx.emit(DatePickerEvent::Change(self.date_time()));
        }
        cx.notify();
    }

    /// Sync the builder configuration into the child states before they render.
    fn sync_children(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let matcher = self.disabled_matcher.clone();
        self.calendar.update(cx, |state, _| {
            state.set_disabled_matcher_shared(matcher);
        });
        // Builders cannot reach the field, so apply them before the first render.
        if !self.time_field_pushed {
            self.push_time_field(window, cx);
        }
    }

    fn set_open(&mut self, open: bool, window: &mut Window, cx: &mut Context<Self>) {
        if !open {
            self.focus_back_if_need(window, cx);
        }
        self.open = open;
        cx.notify();
    }

    fn on_escape(&mut self, _: &Cancel, window: &mut Window, cx: &mut Context<Self>) {
        if !self.open {
            cx.propagate();
        }
        self.set_open(false, window, cx);
    }

    fn on_delete(&mut self, _: &Delete, window: &mut Window, cx: &mut Context<Self>) {
        self.clean(&ClickEvent::default(), window, cx);
    }

    // To focus the Picker Input, if current focus in is on the container, or
    // inside the popup (e.g.: the time field).
    //
    // This is because mouse down out the Calendar, GPUI will move focus to the container.
    // So we need to move focus back to the Picker Input.
    //
    // But if mouse down target is some other focusable element (e.g.: [`crate::Input`]), we should not move focus.
    fn focus_back_if_need(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        if !self.open {
            return;
        }

        if let Some(focused) = window.focused(cx) {
            if focused.contains(&self.focus_handle, window)
                || self.focus_handle.contains_focused(window, cx)
            {
                self.focus_handle.focus(window, cx);
            }
        }
    }

    fn clean(&mut self, _: &gpui::ClickEvent, window: &mut Window, cx: &mut Context<Self>) {
        cx.stop_propagation();
        let default_time = self.default_time;
        self.set_times(default_time, default_time, window, cx);
        match self.date {
            Date::Single(_) => {
                self.update_date(Date::Single(None), true, window, cx);
            }
            Date::Range(_, _) => {
                self.update_date(Date::Range(None, None), true, window, cx);
            }
        }
    }

    fn toggle_calendar(
        &mut self,
        _: &gpui::ClickEvent,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let open = !self.open;
        self.set_open(open, window, cx);
    }

    fn select_preset(
        &mut self,
        preset: &DateRangePreset,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        match preset.value {
            DateRangePresetValue::Single(single) => {
                self.update_date(Date::Single(Some(single)), true, window, cx)
            }
            DateRangePresetValue::Range(start, end) => {
                self.update_date(Date::Range(Some(start), Some(end)), true, window, cx)
            }
            DateRangePresetValue::DateTime(value) => {
                self.set_date_time(value, window, cx);
                cx.emit(DatePickerEvent::Change(self.date_time()));
            }
        }
        self.focus_handle.focus(window, cx);
    }

    fn display_format(&self) -> SharedString {
        if let Some(format) = &self.date_format {
            return format.clone();
        }
        match self.edited_time_precision() {
            Some(precision) => format!("%Y/%m/%d {}", precision.format(self.hour_cycle)).into(),
            None => "%Y/%m/%d".into(),
        }
    }
}

/// A DatePicker element.
#[derive(IntoElement)]
pub struct DatePicker {
    id: ElementId,
    style: StyleRefinement,
    state: Entity<DatePickerState>,
    cleanable: bool,
    placeholder: Option<SharedString>,
    size: Size,
    number_of_months: usize,
    presets: Option<Vec<DateRangePreset>>,
    appearance: bool,
    focus_ring_enabled: bool,
    disabled: bool,
}

impl Sizable for DatePicker {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}
impl Focusable for DatePicker {
    fn focus_handle(&self, cx: &App) -> FocusHandle {
        self.state.focus_handle(cx)
    }
}

impl Styled for DatePicker {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl Disableable for DatePicker {
    fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }
}

impl crate::FocusableExt for DatePicker {
    fn focus_ring(mut self, enabled: bool) -> Self {
        self.focus_ring_enabled = enabled;
        self
    }

    fn is_focus_ring_enabled(&self) -> bool {
        self.focus_ring_enabled
    }
}

impl Render for DatePickerState {
    fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl gpui::IntoElement {
        Empty
    }
}

impl DatePicker {
    /// Create a new DatePicker with the given [`DatePickerState`].
    pub fn new(state: &Entity<DatePickerState>) -> Self {
        Self {
            id: ("date-picker", state.entity_id()).into(),
            state: state.clone(),
            cleanable: false,
            placeholder: None,
            size: Size::default(),
            style: StyleRefinement::default(),
            number_of_months: 1,
            presets: None,
            appearance: true,
            focus_ring_enabled: true,
            disabled: false,
        }
    }

    /// Set the placeholder of the date picker, default: "".
    pub fn placeholder(mut self, placeholder: impl Into<SharedString>) -> Self {
        self.placeholder = Some(placeholder.into());
        self
    }

    /// Set whether to show the clear button when the input field is not empty, default is false.
    pub fn cleanable(mut self, cleanable: bool) -> Self {
        self.cleanable = cleanable;
        self
    }

    /// Set preset ranges for the date picker.
    pub fn presets(mut self, presets: Vec<DateRangePreset>) -> Self {
        self.presets = Some(presets);
        self
    }

    /// Set number of months to display in the calendar, default is 1.
    pub fn number_of_months(mut self, number_of_months: usize) -> Self {
        self.number_of_months = number_of_months;
        self
    }

    /// Set appearance of the date picker, if false, the date picker will be in a minimal style.
    pub fn appearance(mut self, appearance: bool) -> Self {
        self.appearance = appearance;
        self
    }

    fn render_time_field(size: Size, state: &DatePickerState, cx: &App) -> impl IntoElement {
        h_flex()
            .map(|this| match size {
                Size::Small => this.mt_2().pt_2(),
                _ => this.mt_3().pt_3(),
            })
            .gap_3()
            .justify_between()
            .border_t_1()
            .border_color(cx.theme().border)
            .child(
                div()
                    .map(|this| match size {
                        Size::Small => this.text_xs(),
                        _ => this.text_sm(),
                    })
                    .text_color(cx.theme().muted_foreground)
                    .child(SharedString::from(t!("DatePicker.time"))),
            )
            .child(
                TimeField::new(&state.time_field)
                    .with_id("time")
                    .with_size(size),
            )
    }
}

impl RenderOnce for DatePicker {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        self.state.update(cx, |state, cx| {
            state.sync_children(window, cx);
        });
        let month_count = self.number_of_months.max(1) as f32;

        // This for keep focus border style, when click on the popup.
        let is_focused = self.focus_handle(cx).contains_focused(window, cx);
        let state = self.state.read(cx);
        let show_clean = self.cleanable && state.date.is_some();
        let placeholder = self
            .placeholder
            .clone()
            .unwrap_or_else(|| t!("DatePicker.placeholder").into());
        let display_title = state
            .date_time()
            .format(&state.display_format())
            .unwrap_or(placeholder.clone());

        let (bg, fg) = input_style(self.disabled, cx);

        let picker_state = self.state.clone();

        BaseDatePicker::new(self.id, &state.focus_handle)
            .open(state.open)
            .when(state.date.is_some(), |this| {
                this.aria_value(display_title.clone())
            })
            .disabled(self.disabled)
            .on_open_change(move |open, window, cx| {
                picker_state.update(cx, |state, cx| state.set_open(open, window, cx));
            })
            .key_context(CONTEXT)
            .on_action(window.listener_for(&self.state, DatePickerState::on_delete))
            .flex_none()
            .w_full()
            .relative()
            .on_prepaint({
                let state = self.state.clone();
                move |bounds, _, cx| state.update(cx, |state, _| state.bounds = bounds)
            })
            .input_text_size(self.size)
            .refine_style(&self.style)
            .child(
                div()
                    .id("date-picker-input")
                    .relative()
                    .flex()
                    .items_center()
                    .justify_between()
                    .when(self.appearance, |this| {
                        this.bg(bg)
                            .text_color(fg)
                            .when(self.disabled, |this| this.opacity(0.5))
                            .border_1()
                            .border_color(cx.theme().input)
                            .rounded(cx.theme().radius)
                            .when(is_focused, |this| {
                                this.border_1().border_color(cx.theme().ring)
                            })
                    })
                    .when(
                        is_focused && self.appearance && !self.disabled && self.focus_ring_enabled,
                        |this| this.focus_ring_style(window, cx),
                    )
                    .input_text_size(self.size)
                    .input_size(self.size)
                    .when(!state.open && !self.disabled, |this| {
                        this.on_click(
                            window.listener_for(&self.state, DatePickerState::toggle_calendar),
                        )
                    })
                    .child(
                        h_flex()
                            .w_full()
                            .min_w_0()
                            .overflow_hidden()
                            .whitespace_nowrap()
                            .items_center()
                            .justify_between()
                            .gap_1()
                            .child(
                                div()
                                    .flex_1()
                                    .min_w_0()
                                    .overflow_hidden()
                                    .whitespace_nowrap()
                                    .truncate()
                                    // The value updates live while its time is typed.
                                    .when(state.edited_time_precision().is_some(), |this| {
                                        this.font_features(tabular_figures())
                                    })
                                    .when(!state.date.is_some(), |this| {
                                        this.text_color(cx.theme().muted_foreground)
                                    })
                                    .child(display_title),
                            )
                            .when(!self.disabled, |this| {
                                this.when(show_clean, |this| {
                                    this.child(clear_button(cx).on_click(
                                        window.listener_for(&self.state, DatePickerState::clean),
                                    ))
                                })
                                .when(!show_clean, |this| {
                                    this.child(
                                        Icon::new(IconName::Calendar)
                                            .xsmall()
                                            .text_color(cx.theme().muted_foreground),
                                    )
                                })
                            }),
                    ),
            )
            .when(state.open, |this| {
                this.child(
                    deferred(crate::popover::dropdown_popup(
                        ("date-picker-popup", self.state.entity_id()),
                        state.bounds,
                        div()
                            .occlude()
                            .p_3()
                            .popover_style(cx)
                            .on_mouse_up_out(
                                MouseButton::Left,
                                window.listener_for(&self.state, |view, _, window, cx| {
                                    view.on_escape(&Cancel, window, cx);
                                }),
                            )
                            .child(
                                h_flex()
                                    .gap_3()
                                    .h_full()
                                    .items_start()
                                    .when_some(self.presets.clone(), |this, presets| {
                                        this.child(v_flex().my_1().gap_2().justify_end().children(
                                            presets.into_iter().enumerate().map(|(i, preset)| {
                                                Button::new(("preset", i))
                                                    .small()
                                                    .ghost()
                                                    .tab_stop(false)
                                                    .label(preset.label.clone())
                                                    .on_click(window.listener_for(
                                                        &self.state,
                                                        move |this, _, window, cx| {
                                                            this.select_preset(&preset, window, cx);
                                                        },
                                                    ))
                                            }),
                                        ))
                                    })
                                    .child(
                                        v_flex()
                                            .child(
                                                Calendar::new(&state.calendar)
                                                    .number_of_months(self.number_of_months)
                                                    .first_day_of_week(state.first_day_of_week)
                                                    .border_0()
                                                    .rounded_none()
                                                    .p_0()
                                                    .map(|this| match self.size {
                                                        Size::Small => {
                                                            this.w(px(196.) * month_count)
                                                        }
                                                        Size::Large => {
                                                            this.w(px(280.) * month_count)
                                                        }
                                                        _ => this.w(px(224.) * month_count),
                                                    })
                                                    .with_size(self.size),
                                            )
                                            .when_some(state.edited_time_precision(), |this, _| {
                                                this.child(Self::render_time_field(
                                                    self.size, state, cx,
                                                ))
                                            }),
                                    ),
                            ),
                        cx,
                    ))
                    .with_priority(gpui_base::POPUP_PRIORITY),
                )
            })
    }
}
