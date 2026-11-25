use crate::TestSupportExt as _;
use std::rc::Rc;

use chrono::{NaiveTime, Timelike as _};
use gpui::{
    AnyElement, App, Context, ElementId, Empty, Entity, EventEmitter, FocusHandle, Focusable,
    InteractiveElement, IntoElement, KeyBinding, KeyDownEvent, MouseButton, MouseDownEvent,
    ParentElement, Render, RenderOnce, Role, SharedString, StatefulInteractiveElement,
    StyleRefinement, Styled, Window, div, prelude::FluentBuilder as _,
};

use crate::{
    Decrement, Increment, StyledExt as _,
    a11y_disabled::A11yDisabledExt as _,
    actions::{SelectLeft, SelectNextColumn, SelectPrevColumn, SelectRight},
    input::Delete,
};

const CONTEXT: &str = "TimeField";

pub(crate) fn init(cx: &mut App) {
    cx.bind_keys([
        KeyBinding::new("up", Increment, Some(CONTEXT)),
        KeyBinding::new("down", Decrement, Some(CONTEXT)),
        KeyBinding::new("left", SelectLeft, Some(CONTEXT)),
        KeyBinding::new("right", SelectRight, Some(CONTEXT)),
        KeyBinding::new("tab", SelectNextColumn, Some(CONTEXT)),
        KeyBinding::new("shift-tab", SelectPrevColumn, Some(CONTEXT)),
        KeyBinding::new("backspace", Delete, Some(CONTEXT)),
        KeyBinding::new("delete", Delete, Some(CONTEXT)),
    ]);
}

/// The smallest unit a [`TimeField`] edits.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub enum TimePrecision {
    /// Hours and minutes, e.g. `09:30`.
    #[default]
    Minute,
    /// Hours, minutes and seconds, e.g. `09:30:15`.
    Second,
}

impl TimePrecision {
    /// The `chrono` format that displays a time at this precision and cycle.
    pub fn format(self, hour_cycle: HourCycle) -> &'static str {
        match (self, hour_cycle) {
            (Self::Minute, HourCycle::H23) => "%H:%M",
            (Self::Second, HourCycle::H23) => "%H:%M:%S",
            (Self::Minute, HourCycle::H12) => "%I:%M %p",
            (Self::Second, HourCycle::H12) => "%I:%M:%S %p",
        }
    }

    /// Drop the components finer than this precision.
    pub fn truncate(self, time: NaiveTime) -> NaiveTime {
        let second = match self {
            Self::Minute => 0,
            Self::Second => time.second(),
        };
        NaiveTime::from_hms_opt(time.hour(), time.minute(), second).unwrap_or(time)
    }
}

/// How a [`TimeField`] counts the hours of a day.
///
/// The names follow the Unicode `hourCycle` values.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub enum HourCycle {
    /// A 24-hour clock from `00` to `23`.
    #[default]
    H23,
    /// A 12-hour clock from `12` to `11`, with an AM/PM segment.
    H12,
}

/// One editable component of a [`TimeField`].
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum TimeSegment {
    Hour,
    Minute,
    Second,
    /// AM or PM, present with [`HourCycle::H12`].
    Period,
}

impl TimeSegment {
    fn name(self) -> &'static str {
        match self {
            Self::Hour => "hour",
            Self::Minute => "minute",
            Self::Second => "second",
            Self::Period => "period",
        }
    }
}

/// A semantic notification from a [`TimeFieldState`].
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TimeFieldEvent {
    /// Keyboard editing changed the time.
    Change(NaiveTime),
}

/// The pure editing rules of a [`TimeFieldState`], kept apart from focus so
/// they can be tested without a window.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct SegmentEditor {
    time: NaiveTime,
    precision: TimePrecision,
    hour_cycle: HourCycle,
    segment: TimeSegment,
    /// The first digit typed into the selected segment, awaiting a second.
    pending_digit: Option<u32>,
}

impl SegmentEditor {
    fn new() -> Self {
        Self {
            time: NaiveTime::MIN,
            precision: TimePrecision::default(),
            hour_cycle: HourCycle::default(),
            segment: TimeSegment::Hour,
            pending_digit: None,
        }
    }

    /// The segments shown, in reading order.
    fn segments(&self) -> &'static [TimeSegment] {
        use TimeSegment::*;
        match (self.precision, self.hour_cycle) {
            (TimePrecision::Minute, HourCycle::H23) => &[Hour, Minute],
            (TimePrecision::Second, HourCycle::H23) => &[Hour, Minute, Second],
            (TimePrecision::Minute, HourCycle::H12) => &[Hour, Minute, Period],
            (TimePrecision::Second, HourCycle::H12) => &[Hour, Minute, Second, Period],
        }
    }

    /// The inclusive range a segment's displayed value takes.
    fn bounds(&self, segment: TimeSegment) -> (u32, u32) {
        match (segment, self.hour_cycle) {
            (TimeSegment::Hour, HourCycle::H23) => (0, 23),
            (TimeSegment::Hour, HourCycle::H12) => (1, 12),
            (TimeSegment::Minute | TimeSegment::Second, _) => (0, 59),
            (TimeSegment::Period, _) => (0, 1),
        }
    }

    /// The displayed value of a segment: the hour follows the cycle, and the
    /// period is `0` for AM and `1` for PM.
    fn value(&self, segment: TimeSegment) -> u32 {
        let hour = self.time.hour();
        match (segment, self.hour_cycle) {
            (TimeSegment::Hour, HourCycle::H23) => hour,
            (TimeSegment::Hour, HourCycle::H12) => (hour + 11) % 12 + 1,
            (TimeSegment::Minute, _) => self.time.minute(),
            (TimeSegment::Second, _) => self.time.second(),
            (TimeSegment::Period, _) => hour / 12,
        }
    }

    fn label(&self, segment: TimeSegment) -> SharedString {
        match segment {
            TimeSegment::Period if self.value(segment) == 0 => "AM".into(),
            TimeSegment::Period => "PM".into(),
            _ => format!("{:02}", self.value(segment)).into(),
        }
    }

    fn with_value(&self, segment: TimeSegment, value: u32) -> NaiveTime {
        let time = self.time;
        let pm_offset = time.hour() / 12 * 12;
        match (segment, self.hour_cycle) {
            (TimeSegment::Hour, HourCycle::H23) => time.with_hour(value),
            // 12 AM is midnight and 12 PM is noon.
            (TimeSegment::Hour, HourCycle::H12) => time.with_hour(value % 12 + pm_offset),
            (TimeSegment::Minute, _) => time.with_minute(value),
            (TimeSegment::Second, _) => time.with_second(value),
            (TimeSegment::Period, _) => time.with_hour(time.hour() % 12 + value * 12),
        }
        .unwrap_or(time)
    }

    fn set_precision(&mut self, precision: TimePrecision) {
        self.precision = precision;
        self.time = precision.truncate(self.time);
        self.reset_segment();
    }

    fn set_hour_cycle(&mut self, hour_cycle: HourCycle) {
        self.hour_cycle = hour_cycle;
        self.reset_segment();
    }

    fn reset_segment(&mut self) {
        if !self.segments().contains(&self.segment) {
            self.segment = TimeSegment::Hour;
        }
        self.pending_digit = None;
    }

    fn set_time(&mut self, time: NaiveTime) -> bool {
        let time = self.precision.truncate(time);
        if self.time == time {
            // Keep a half-typed segment when the owner echoes the same value back.
            return false;
        }
        self.time = time;
        self.pending_digit = None;
        true
    }

    fn select_segment(&mut self, segment: TimeSegment) -> bool {
        if !self.segments().contains(&segment) {
            return false;
        }
        self.segment = segment;
        self.pending_digit = None;
        true
    }

    /// Move the selected segment by `offset`; returns `false` at either end.
    fn move_segment(&mut self, offset: isize) -> bool {
        let segments = self.segments();
        let ix = segments
            .iter()
            .position(|segment| *segment == self.segment)
            .unwrap_or(0);
        let Some(next) = ix
            .checked_add_signed(offset)
            .and_then(|ix| segments.get(ix))
        else {
            return false;
        };
        self.select_segment(*next)
    }

    /// Step the selected segment by `delta`, wrapping within the segment.
    fn step(&mut self, delta: i32) -> bool {
        self.pending_digit = None;
        let (min, max) = self.bounds(self.segment);
        let span = (max - min + 1) as i32;
        let value = (self.value(self.segment) as i32 - min as i32 + delta).rem_euclid(span);
        self.replace_segment(value as u32 + min)
    }

    fn input_digit(&mut self, digit: u32) -> bool {
        if self.segment == TimeSegment::Period {
            return false;
        }
        let (min, max) = self.bounds(self.segment);
        let (value, complete) = match self.pending_digit.take() {
            Some(first) if (min..=max).contains(&(first * 10 + digit)) => {
                (first * 10 + digit, true)
            }
            // The two digits cannot form a valid value, so the new digit starts over.
            _ => (digit, digit * 10 > max),
        };
        if !complete {
            self.pending_digit = Some(digit);
        }
        let changed = self.replace_segment(value);
        if complete {
            self.move_segment(1);
        }
        changed
    }

    /// Type `a` or `p` into the period segment.
    fn input_period(&mut self, pm: bool) -> bool {
        if self.segment != TimeSegment::Period {
            return false;
        }
        self.replace_segment(pm as u32)
    }

    /// Reset the selected segment to its first value: zero, or `12` / AM on a
    /// 12-hour clock.
    fn clear_segment(&mut self) -> bool {
        self.pending_digit = None;
        self.replace_segment(0)
    }

    fn replace_segment(&mut self, value: u32) -> bool {
        let time = self.with_value(self.segment, value);
        let changed = time != self.time;
        self.time = time;
        changed
    }
}

/// Retained editing behavior for a segmented time field.
///
/// The field is one Tab stop. Inside it, one segment is selected at a time:
/// Up/Down step the selected segment and wrap within it (no carry into the
/// next unit), Left/Right and Tab/Shift-Tab move between segments, digits are
/// typed with a two-digit buffer that advances to the next segment once no
/// further digit could fit, `a`/`p` set the AM/PM segment, and
/// Backspace/Delete reset the segment.
///
/// The owner supplies the value with [`TimeFieldState::set_time`], which does
/// not emit; user edits emit [`TimeFieldEvent::Change`].
pub struct TimeFieldState {
    focus_handle: FocusHandle,
    editor: SegmentEditor,
}

impl TimeFieldState {
    pub fn new(_: &mut Window, cx: &mut Context<Self>) -> Self {
        Self {
            focus_handle: cx.focus_handle().tab_stop(true),
            editor: SegmentEditor::new(),
        }
    }

    /// Set the precision, default: [`TimePrecision::Minute`].
    pub fn precision(mut self, precision: TimePrecision) -> Self {
        self.editor.set_precision(precision);
        self
    }

    pub fn set_precision(
        &mut self,
        precision: TimePrecision,
        _: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if self.editor.precision != precision {
            self.editor.set_precision(precision);
            cx.notify();
        }
    }

    /// Set the hour cycle, default: [`HourCycle::H23`].
    pub fn hour_cycle(mut self, hour_cycle: HourCycle) -> Self {
        self.editor.set_hour_cycle(hour_cycle);
        self
    }

    pub fn set_hour_cycle(
        &mut self,
        hour_cycle: HourCycle,
        _: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if self.editor.hour_cycle != hour_cycle {
            self.editor.set_hour_cycle(hour_cycle);
            cx.notify();
        }
    }

    pub fn time(&self) -> NaiveTime {
        self.editor.time
    }

    /// Replace the time without emitting [`TimeFieldEvent::Change`].
    pub fn set_time(&mut self, time: NaiveTime, _: &mut Window, cx: &mut Context<Self>) {
        if self.editor.set_time(time) {
            cx.notify();
        }
    }

    /// The segment that keyboard editing applies to.
    pub fn selected_segment(&self) -> TimeSegment {
        self.editor.segment
    }

    pub fn focus(&self, window: &mut Window, cx: &mut App) {
        self.focus_handle.focus(window, cx);
    }

    fn edit(&mut self, cx: &mut Context<Self>, edit: impl FnOnce(&mut SegmentEditor) -> bool) {
        if edit(&mut self.editor) {
            cx.emit(TimeFieldEvent::Change(self.editor.time));
        }
        cx.notify();
    }

    fn on_increment(&mut self, _: &Increment, _: &mut Window, cx: &mut Context<Self>) {
        self.edit(cx, |editor| editor.step(1));
    }

    fn on_decrement(&mut self, _: &Decrement, _: &mut Window, cx: &mut Context<Self>) {
        self.edit(cx, |editor| editor.step(-1));
    }

    fn on_delete(&mut self, _: &Delete, _: &mut Window, cx: &mut Context<Self>) {
        self.edit(cx, SegmentEditor::clear_segment);
    }

    fn on_select_left(&mut self, _: &SelectLeft, _: &mut Window, cx: &mut Context<Self>) {
        self.editor.move_segment(-1);
        cx.notify();
    }

    fn on_select_right(&mut self, _: &SelectRight, _: &mut Window, cx: &mut Context<Self>) {
        self.editor.move_segment(1);
        cx.notify();
    }

    // Tab walks the segments first and leaves the field only from the last one.
    fn on_next_column(&mut self, _: &SelectNextColumn, _: &mut Window, cx: &mut Context<Self>) {
        if self.editor.move_segment(1) {
            cx.notify();
        } else {
            cx.propagate();
        }
    }

    fn on_prev_column(&mut self, _: &SelectPrevColumn, _: &mut Window, cx: &mut Context<Self>) {
        if self.editor.move_segment(-1) {
            cx.notify();
        } else {
            cx.propagate();
        }
    }

    fn on_key_down(&mut self, event: &KeyDownEvent, window: &mut Window, cx: &mut Context<Self>) {
        let keystroke = &event.keystroke;
        if keystroke.modifiers.modified() || keystroke.key.chars().count() != 1 {
            return;
        }
        let Some(ch) = keystroke.key.chars().next() else {
            return;
        };
        let edit: Box<dyn FnOnce(&mut SegmentEditor) -> bool> = match ch {
            '0'..='9' => Box::new(move |editor| editor.input_digit(ch as u32 - '0' as u32)),
            'a' | 'A' => Box::new(|editor| editor.input_period(false)),
            'p' | 'P' => Box::new(|editor| editor.input_period(true)),
            _ => return,
        };
        window.prevent_default();
        cx.stop_propagation();
        self.edit(cx, edit);
    }

    fn select_segment(&mut self, segment: TimeSegment, cx: &mut Context<Self>) {
        self.editor.select_segment(segment);
        cx.notify();
    }
}

impl Focusable for TimeFieldState {
    fn focus_handle(&self, _: &App) -> FocusHandle {
        self.focus_handle.clone()
    }
}
impl EventEmitter<TimeFieldEvent> for TimeFieldState {}
impl Render for TimeFieldState {
    fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
        Empty
    }
}

/// State exposed to a [`TimeField`] segment slot for decoration.
#[derive(Clone, Copy, Debug)]
pub struct TimeFieldSegmentState {
    segment: TimeSegment,
    value: u32,
    selected: bool,
    disabled: bool,
}

impl TimeFieldSegmentState {
    pub fn segment(&self) -> TimeSegment {
        self.segment
    }

    /// The displayed value: the hour on the configured clock, the minute or
    /// second, or `0` for AM and `1` for PM.
    pub fn value(&self) -> u32 {
        self.value
    }

    /// Whether keyboard editing applies to this segment: it is the selected
    /// segment and the field has focus.
    pub fn is_selected(&self) -> bool {
        self.selected
    }

    pub fn is_disabled(&self) -> bool {
        self.disabled
    }
}

type SegmentRenderer =
    Rc<dyn Fn(TimeFieldSegment, TimeFieldSegmentState, &mut Window, &mut App) -> AnyElement>;

/// An unstyled, pre-wired segment passed to the [`TimeField`] segment slot.
#[derive(IntoElement)]
pub struct TimeFieldSegment {
    base: crate::ObservedElement<gpui::Stateful<gpui::Div>>,
    style: StyleRefinement,
    children: Vec<AnyElement>,
}

impl TimeFieldSegment {
    /// Remove the default label so a styled facade can provide custom content.
    pub fn clear_children(mut self) -> Self {
        self.children.clear();
        self
    }
}

impl ParentElement for TimeFieldSegment {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}
impl Styled for TimeFieldSegment {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}
impl InteractiveElement for TimeFieldSegment {
    fn interactivity(&mut self) -> &mut gpui::Interactivity {
        self.base.interactivity()
    }
}
impl StatefulInteractiveElement for TimeFieldSegment {}
impl RenderOnce for TimeFieldSegment {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        self.base.children(self.children).refine_style(&self.style)
    }
}

/// Unstyled segmented time editor.
///
/// Base owns focus, the keyboard model and pointer segment selection; the
/// presentation lays out and decorates the field with `Styled` and each
/// segment through [`TimeField::render_segment`]. A `:` separates the numeric
/// segments; the AM/PM segment follows without one.
#[derive(IntoElement)]
pub struct TimeField {
    id: ElementId,
    state: Entity<TimeFieldState>,
    disabled: bool,
    style: StyleRefinement,
    segment: SegmentRenderer,
}

impl TimeField {
    pub fn new(id: impl Into<ElementId>, state: &Entity<TimeFieldState>) -> Self {
        Self {
            id: id.into(),
            state: state.clone(),
            disabled: false,
            style: StyleRefinement::default(),
            segment: Rc::new(|segment, _, _, _| segment.into_any_element()),
        }
    }

    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    /// Decorate each segment. The segment already carries its label: two
    /// digits, or `AM`/`PM`.
    pub fn render_segment(
        mut self,
        render: impl Fn(TimeFieldSegment, TimeFieldSegmentState, &mut Window, &mut App) -> AnyElement
        + 'static,
    ) -> Self {
        self.segment = Rc::new(render);
        self
    }
}

impl Styled for TimeField {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for TimeField {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let disabled = self.disabled;
        let state = self.state.read(cx);
        let focus_handle = state.focus_handle.clone();
        let focused = focus_handle.is_focused(window);
        let editor = state.editor;
        let format = editor.precision.format(editor.hour_cycle);

        let mut root = div()
            .id(self.id.clone())
            .test_support()
            .role(Role::TimeInput)
            .aria_value(SharedString::from(editor.time.format(format).to_string()))
            .track_focus(&focus_handle.clone().tab_stop(!disabled))
            .when(!disabled, |this| {
                this.key_context(CONTEXT)
                    .on_action(window.listener_for(&self.state, TimeFieldState::on_increment))
                    .on_action(window.listener_for(&self.state, TimeFieldState::on_decrement))
                    .on_action(window.listener_for(&self.state, TimeFieldState::on_delete))
                    .on_action(window.listener_for(&self.state, TimeFieldState::on_select_left))
                    .on_action(window.listener_for(&self.state, TimeFieldState::on_select_right))
                    .on_action(window.listener_for(&self.state, TimeFieldState::on_next_column))
                    .on_action(window.listener_for(&self.state, TimeFieldState::on_prev_column))
                    .on_key_down(window.listener_for(&self.state, TimeFieldState::on_key_down))
                    // A press on the field outside any segment focuses it and selects the
                    // first segment; a press on a segment stops here and selects that one.
                    .on_mouse_down(MouseButton::Left, {
                        let state = self.state.clone();
                        let focus_handle = focus_handle.clone();
                        move |_: &MouseDownEvent, window, cx| {
                            focus_handle.focus(window, cx);
                            state.update(cx, |state, cx| {
                                let first = state.editor.segments()[0];
                                state.select_segment(first, cx);
                            });
                        }
                    })
            });

        for (ix, segment) in editor.segments().iter().copied().enumerate() {
            if ix > 0 && segment != TimeSegment::Period {
                root = root.child(div().child(":"));
            }
            let segment_state = TimeFieldSegmentState {
                segment,
                value: editor.value(segment),
                selected: focused && segment == editor.segment,
                disabled,
            };
            let mut item = TimeFieldSegment {
                base: div().id(segment.name()).test_support(),
                style: StyleRefinement::default(),
                children: vec![],
            }
            .child(editor.label(segment));
            if !disabled {
                let state = self.state.clone();
                let focus_handle = focus_handle.clone();
                item =
                    item.on_mouse_down(MouseButton::Left, move |_: &MouseDownEvent, window, cx| {
                        cx.stop_propagation();
                        focus_handle.focus(window, cx);
                        state.update(cx, |state, cx| state.select_segment(segment, cx));
                    });
            }
            root = root.child((self.segment)(item, segment_state, window, cx));
        }

        root.refine_style(&self.style).a11y_disabled(disabled)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hms(h: u32, m: u32, s: u32) -> NaiveTime {
        NaiveTime::from_hms_opt(h, m, s).unwrap()
    }

    fn editor(precision: TimePrecision, hour_cycle: HourCycle) -> SegmentEditor {
        let mut editor = SegmentEditor::new();
        editor.set_precision(precision);
        editor.set_hour_cycle(hour_cycle);
        editor
    }

    fn type_keys(editor: &mut SegmentEditor, keys: &str) {
        for ch in keys.chars() {
            match ch {
                'a' => editor.input_period(false),
                'p' => editor.input_period(true),
                _ => editor.input_digit(ch.to_digit(10).unwrap()),
            };
        }
    }

    #[test]
    fn typing_fills_segments_and_advances() {
        let mut editor = editor(TimePrecision::Second, HourCycle::H23);
        type_keys(&mut editor, "093015");
        assert_eq!(editor.time, hms(9, 30, 15));
        // The last segment stays selected once it is complete.
        assert_eq!(editor.segment, TimeSegment::Second);
    }

    #[test]
    fn a_digit_that_cannot_start_two_digits_completes_the_segment() {
        let mut editor = editor(TimePrecision::Minute, HourCycle::H23);
        type_keys(&mut editor, "7");
        assert_eq!(editor.time, hms(7, 0, 0));
        assert_eq!(editor.segment, TimeSegment::Minute);
        type_keys(&mut editor, "8");
        assert_eq!(editor.time, hms(7, 8, 0));
    }

    #[test]
    fn an_out_of_range_pair_restarts_from_the_second_digit() {
        let mut editor = editor(TimePrecision::Minute, HourCycle::H23);
        // 2 then 5 cannot form 25 hours, so 5 starts a new entry and completes it.
        type_keys(&mut editor, "25");
        assert_eq!(editor.time, hms(5, 0, 0));
        assert_eq!(editor.segment, TimeSegment::Minute);
    }

    #[test]
    fn stepping_wraps_without_carry() {
        let mut editor = editor(TimePrecision::Minute, HourCycle::H23);
        editor.set_time(hms(23, 59, 0));
        editor.step(1);
        assert_eq!(editor.time, hms(0, 59, 0));
        editor.select_segment(TimeSegment::Minute);
        editor.step(1);
        assert_eq!(editor.time, hms(0, 0, 0));
        editor.step(-1);
        assert_eq!(editor.time, hms(0, 59, 0));
    }

    #[test]
    fn segment_movement_stops_at_the_ends() {
        let mut editor = editor(TimePrecision::Minute, HourCycle::H23);
        assert!(!editor.move_segment(-1));
        assert!(editor.move_segment(1));
        assert!(!editor.move_segment(1));
        assert!(!editor.select_segment(TimeSegment::Second));
        assert!(!editor.select_segment(TimeSegment::Period));
    }

    #[test]
    fn precision_truncates_seconds() {
        let mut editor = editor(TimePrecision::Second, HourCycle::H23);
        editor.set_time(hms(9, 30, 15));
        editor.select_segment(TimeSegment::Second);
        editor.set_precision(TimePrecision::Minute);
        assert_eq!(editor.time, hms(9, 30, 0));
        assert_eq!(editor.segment, TimeSegment::Hour);
    }

    #[test]
    fn clearing_resets_only_the_selected_segment() {
        let mut editor = editor(TimePrecision::Minute, HourCycle::H23);
        editor.set_time(hms(9, 30, 0));
        editor.select_segment(TimeSegment::Minute);
        assert!(editor.clear_segment());
        assert_eq!(editor.time, hms(9, 0, 0));
    }

    #[test]
    fn twelve_hour_labels_map_midnight_and_noon_to_twelve() {
        let mut editor = editor(TimePrecision::Minute, HourCycle::H12);
        for (hour, label, period) in [
            (0, "12", "AM"),
            (9, "09", "AM"),
            (12, "12", "PM"),
            (23, "11", "PM"),
        ] {
            editor.set_time(hms(hour, 0, 0));
            assert_eq!(editor.label(TimeSegment::Hour), label);
            assert_eq!(editor.label(TimeSegment::Period), period);
        }
    }

    #[test]
    fn twelve_hour_typing_keeps_the_period_until_it_is_typed() {
        let mut editor = editor(TimePrecision::Minute, HourCycle::H12);
        // "1" may start 10–12, so it waits; "2" makes 12, which is midnight in AM.
        type_keys(&mut editor, "12");
        assert_eq!(editor.time, hms(0, 0, 0));
        type_keys(&mut editor, "30p");
        assert_eq!(editor.time, hms(12, 30, 0));
        assert_eq!(editor.segment, TimeSegment::Period);
        editor.select_segment(TimeSegment::Hour);
        type_keys(&mut editor, "9");
        assert_eq!(editor.time, hms(21, 30, 0));
        // "00" is not an hour on a 12-hour clock.
        editor.select_segment(TimeSegment::Hour);
        type_keys(&mut editor, "00");
        assert_eq!(editor.segment, TimeSegment::Hour);
    }

    #[test]
    fn twelve_hour_stepping_wraps_within_the_period() {
        let mut editor = editor(TimePrecision::Minute, HourCycle::H12);
        editor.set_time(hms(11, 0, 0));
        editor.step(1);
        assert_eq!(editor.time, hms(0, 0, 0), "11 AM steps to 12 AM");
        editor.select_segment(TimeSegment::Period);
        editor.step(1);
        assert_eq!(editor.time, hms(12, 0, 0));
        editor.step(1);
        assert_eq!(editor.time, hms(0, 0, 0));
        assert!(!editor.input_digit(1), "digits do not edit the period");
    }
}
