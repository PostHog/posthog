use crate::TestSupportExt as _;
use std::rc::Rc;

use crate::{h_flex, styled::StyledExt as _, v_flex};
use chrono::{Datelike, Local, NaiveDate, Weekday};
use gpui::{
    AnyElement, App, Context, ElementId, Empty, Entity, EventEmitter, FocusHandle,
    InteractiveElement, IntoElement, ParentElement, Render, RenderOnce, SharedString,
    StatefulInteractiveElement, StyleRefinement, Styled, Window, div, px,
};

/// A controlled calendar value.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Date {
    Single(Option<NaiveDate>),
    Range(Option<NaiveDate>, Option<NaiveDate>),
}

impl std::fmt::Display for Date {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Single(Some(date)) => write!(f, "{date}"),
            Self::Single(None) | Self::Range(None, None) => write!(f, "nil"),
            Self::Range(Some(start), Some(end)) => write!(f, "{start} - {end}"),
            Self::Range(Some(start), None) => write!(f, "{start} - nil"),
            Self::Range(None, Some(end)) => write!(f, "nil - {end}"),
        }
    }
}

impl From<NaiveDate> for Date {
    fn from(value: NaiveDate) -> Self {
        Self::Single(Some(value))
    }
}
impl From<(NaiveDate, NaiveDate)> for Date {
    fn from((start, end): (NaiveDate, NaiveDate)) -> Self {
        Self::Range(Some(start), Some(end))
    }
}

impl Date {
    pub fn is_some(&self) -> bool {
        matches!(self, Self::Single(Some(_)) | Self::Range(Some(_), _))
    }
    pub fn is_complete(&self) -> bool {
        matches!(self, Self::Single(Some(_)) | Self::Range(Some(_), Some(_)))
    }
    pub fn start(&self) -> Option<NaiveDate> {
        match self {
            Self::Single(Some(v)) | Self::Range(Some(v), _) => Some(*v),
            _ => None,
        }
    }
    pub fn end(&self) -> Option<NaiveDate> {
        match self {
            Self::Range(_, Some(v)) => Some(*v),
            _ => None,
        }
    }
    pub fn format(&self, format: &str) -> Option<SharedString> {
        match self {
            Self::Single(Some(v)) => Some(v.format(format).to_string().into()),
            Self::Range(Some(a), Some(b)) => {
                Some(format!("{} - {}", a.format(format), b.format(format)).into())
            }
            _ => None,
        }
    }
    pub fn is_active(&self, value: &NaiveDate) -> bool {
        match self {
            Self::Single(v) => *v == Some(*value),
            Self::Range(a, b) => *a == Some(*value) || *b == Some(*value),
        }
    }
    pub fn is_single(&self) -> bool {
        matches!(self, Self::Single(_))
    }
    pub fn is_in_range(&self, value: &NaiveDate) -> bool {
        matches!(self, Self::Range(Some(a), Some(b)) if value >= a && value <= b)
    }
}

pub struct IntervalMatcher {
    before: Option<NaiveDate>,
    after: Option<NaiveDate>,
}
pub struct RangeMatcher {
    from: Option<NaiveDate>,
    to: Option<NaiveDate>,
}
pub enum Matcher {
    DayOfWeek(Vec<u32>),
    Interval(IntervalMatcher),
    Range(RangeMatcher),
    Custom(Box<dyn Fn(&NaiveDate) -> bool + Send + Sync>),
}
impl From<Vec<u32>> for Matcher {
    fn from(v: Vec<u32>) -> Self {
        Self::DayOfWeek(v)
    }
}
impl<F: Fn(&NaiveDate) -> bool + Send + Sync + 'static> From<F> for Matcher {
    fn from(v: F) -> Self {
        Self::Custom(Box::new(v))
    }
}
impl Matcher {
    pub fn interval(before: Option<NaiveDate>, after: Option<NaiveDate>) -> Self {
        Self::Interval(IntervalMatcher { before, after })
    }
    pub fn range(from: Option<NaiveDate>, to: Option<NaiveDate>) -> Self {
        Self::Range(RangeMatcher { from, to })
    }
    pub fn custom<F: Fn(&NaiveDate) -> bool + Send + Sync + 'static>(f: F) -> Self {
        Self::Custom(Box::new(f))
    }
    pub fn is_match(&self, date: &Date) -> bool {
        match date {
            Date::Single(Some(v)) => self.matched(v),
            Date::Range(Some(a), Some(b)) => self.matched(a) || self.matched(b),
            _ => false,
        }
    }
    pub fn matched(&self, date: &NaiveDate) -> bool {
        match self {
            Self::DayOfWeek(days) => days.contains(&date.weekday().num_days_from_sunday()),
            Self::Interval(v) => {
                v.before.is_some_and(|x| date < &x) || v.after.is_some_and(|x| date > &x)
            }
            Self::Range(v) => {
                !v.from.is_some_and(|x| date < &x) && !v.to.is_some_and(|x| date > &x)
            }
            Self::Custom(f) => f(date),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CalendarView {
    Day,
    Month,
    Year,
}
impl CalendarView {
    pub fn is_day(self) -> bool {
        self == Self::Day
    }
    pub fn is_month(self) -> bool {
        self == Self::Month
    }
    pub fn is_year(self) -> bool {
        self == Self::Year
    }
}

fn picker_grid_layout(view: CalendarView) -> Option<(u16, f32)> {
    match view {
        CalendarView::Day => None,
        CalendarView::Month => Some((3, 4.)),
        CalendarView::Year => Some((5, 4.)),
    }
}

pub enum CalendarEvent {
    Selected(Date),
}

pub struct CalendarState {
    pub focus_handle: FocusHandle,
    view: CalendarView,
    date: Date,
    current_year: i32,
    current_month: u8,
    years: Vec<Vec<i32>>,
    year_page: i32,
    today: NaiveDate,
    number_of_months: usize,
    disabled_matcher: Option<Rc<Matcher>>,
}

impl CalendarState {
    pub fn new(_: &mut Window, cx: &mut Context<Self>) -> Self {
        let today = Local::now().date_naive();
        Self {
            focus_handle: cx.focus_handle(),
            view: CalendarView::Day,
            date: Date::Single(None),
            current_year: today.year(),
            current_month: today.month() as u8,
            years: vec![],
            year_page: 0,
            today,
            number_of_months: 1,
            disabled_matcher: None,
        }
        .year_range((today.year() - 50, today.year() + 50))
    }
    pub fn disabled_matcher(mut self, matcher: impl Into<Matcher>) -> Self {
        self.disabled_matcher = Some(Rc::new(matcher.into()));
        self
    }
    pub fn set_disabled_matcher(
        &mut self,
        matcher: impl Into<Matcher>,
        _: &mut Window,
        _: &mut Context<Self>,
    ) {
        self.disabled_matcher = Some(Rc::new(matcher.into()));
    }
    pub fn set_disabled_matcher_shared(&mut self, matcher: Option<Rc<Matcher>>) {
        self.disabled_matcher = matcher;
    }
    pub fn disabled_matcher_ref(&self) -> Option<&Matcher> {
        self.disabled_matcher.as_deref()
    }
    pub fn set_date(&mut self, date: impl Into<Date>, _: &mut Window, cx: &mut Context<Self>) {
        if self.apply_date(date.into()) {
            cx.notify();
        }
    }
    pub fn apply_date(&mut self, date: Date) -> bool {
        if self
            .disabled_matcher
            .as_ref()
            .is_some_and(|m| m.is_match(&date))
        {
            return false;
        }
        self.date = date;
        if let Some(v) = date.start() {
            self.current_month = v.month() as u8;
            self.current_year = v.year();
        }
        true
    }
    pub fn select_date(&mut self, value: NaiveDate) -> bool {
        if self
            .disabled_matcher
            .as_ref()
            .is_some_and(|m| m.matched(&value))
        {
            return false;
        }
        let next = match self.date {
            Date::Single(_) => Date::Single(Some(value)),
            Date::Range(None, None) | Date::Range(None, Some(_)) => Date::Range(Some(value), None),
            Date::Range(Some(start), None) if value >= start => {
                Date::Range(Some(start), Some(value))
            }
            Date::Range(Some(_), None) | Date::Range(Some(_), Some(_)) => {
                Date::Range(Some(value), None)
            }
        };
        self.apply_date(next);
        self.date.is_complete()
    }
    /// Activates a day item and emits [`CalendarEvent::Selected`] once the
    /// controlled value is complete. This is the single pointer/keyboard
    /// activation path used by the calendar root.
    pub fn activate_date(&mut self, value: NaiveDate, cx: &mut Context<Self>) -> bool {
        let complete = self.select_date(value);
        if complete {
            cx.emit(CalendarEvent::Selected(self.date()));
        }
        cx.notify();
        complete
    }
    pub fn date(&self) -> Date {
        self.date
    }
    pub fn set_number_of_months(&mut self, n: usize, _: &mut Window, cx: &mut Context<Self>) {
        self.number_of_months = n;
        cx.notify();
    }
    pub fn number_of_months(&self) -> usize {
        self.number_of_months
    }
    pub fn year_range(mut self, range: (i32, i32)) -> Self {
        self.apply_year_range(range);
        self
    }
    pub fn set_year_range(&mut self, range: (i32, i32), cx: &mut Context<Self>) {
        self.apply_year_range(range);
        cx.notify();
    }
    fn apply_year_range(&mut self, range: (i32, i32)) {
        self.years = (range.0..range.1)
            .collect::<Vec<_>>()
            .chunks(20)
            .map(<[_]>::to_vec)
            .collect();
        self.year_page = self
            .years
            .iter()
            .position(|v| v.contains(&self.current_year))
            .unwrap_or(0) as i32;
    }
    pub fn offset_year_month(&self, offset: usize) -> (i32, u32) {
        let n = self.current_month as i64 - 1 + offset as i64;
        (
            self.current_year + n.div_euclid(12) as i32,
            n.rem_euclid(12) as u32 + 1,
        )
    }
    pub fn days(&self) -> Vec<Vec<NaiveDate>> {
        self.month_days().into_iter().flatten().collect()
    }
    /// Calendar weeks grouped by visible month. This preserves six-week
    /// months and is the preferred rendering API.
    pub fn month_days(&self) -> Vec<Vec<Vec<NaiveDate>>> {
        (0..self.number_of_months)
            .map(|n| {
                days_in_month(
                    self.current_year,
                    self.current_month as u32 + n as u32,
                    Weekday::Sun,
                )
            })
            .collect()
    }
    pub fn has_prev_year_page(&self) -> bool {
        self.year_page > 0
    }
    pub fn has_next_year_page(&self) -> bool {
        self.year_page < self.years.len() as i32 - 1
    }
    pub fn prev_year_page(&mut self) -> bool {
        if !self.has_prev_year_page() {
            false
        } else {
            self.year_page -= 1;
            true
        }
    }
    pub fn next_year_page(&mut self) -> bool {
        if !self.has_next_year_page() {
            false
        } else {
            self.year_page += 1;
            true
        }
    }
    pub fn prev_month(&mut self) {
        if self.current_month == 1 {
            self.current_year -= 1;
            self.current_month = 12;
        } else {
            self.current_month -= 1;
        }
    }
    pub fn next_month(&mut self) {
        if self.current_month == 12 {
            self.current_year += 1;
            self.current_month = 1;
        } else {
            self.current_month += 1;
        }
    }
    pub fn view(&self) -> CalendarView {
        self.view
    }
    pub fn set_view(&mut self, view: CalendarView) {
        self.view = view;
    }
    pub fn current_year(&self) -> i32 {
        self.current_year
    }
    pub fn current_month(&self) -> u8 {
        self.current_month
    }
    pub fn today(&self) -> NaiveDate {
        self.today
    }
    pub fn years_on_page(&self) -> &[i32] {
        self.years
            .get(self.year_page as usize)
            .map(Vec::as_slice)
            .unwrap_or_default()
    }
    pub fn select_month(&mut self, month: u8) {
        self.current_month = month;
        self.view = CalendarView::Day;
    }
    pub fn select_year(&mut self, year: i32) {
        self.current_year = year;
        self.view = CalendarView::Day;
    }
}
impl EventEmitter<CalendarEvent> for CalendarState {}
impl Render for CalendarState {
    fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
        Empty
    }
}

/// The semantic kind of a calendar control rendered by [`Calendar`].
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CalendarItemKind {
    Previous,
    MonthToggle,
    YearToggle,
    Next,
    Weekday,
    Day,
    Month,
    Year,
}

/// State exposed to a calendar item slot. Applications may use it solely to
/// decorate the unstyled primitive; all interaction remains owned by base.
///
/// The fields are private and reached through the methods below, so that a new
/// one can be added without breaking the item slots.
#[derive(Clone, Copy, Debug)]
pub struct CalendarItemState {
    kind: CalendarItemKind,
    active: bool,
    in_range: bool,
    muted: bool,
    disabled: bool,
    today: bool,
}

impl CalendarItemState {
    /// Create a state for `kind`, with every flag off.
    pub fn new(kind: CalendarItemKind) -> Self {
        Self {
            kind,
            active: false,
            in_range: false,
            muted: false,
            disabled: false,
            today: false,
        }
    }

    pub fn active(mut self, active: bool) -> Self {
        self.active = active;
        self
    }

    /// Set whether the item is between the two ends of a range selection.
    pub fn in_range(mut self, in_range: bool) -> Self {
        self.in_range = in_range;
        self
    }

    /// Set whether the item is shown as secondary, e.g.: a weekday header or a
    /// day that belongs to the neighboring month.
    pub fn muted(mut self, muted: bool) -> Self {
        self.muted = muted;
        self
    }

    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    pub fn today(mut self, today: bool) -> Self {
        self.today = today;
        self
    }

    pub fn kind(&self) -> CalendarItemKind {
        self.kind
    }

    pub fn is_active(&self) -> bool {
        self.active
    }

    pub fn is_in_range(&self) -> bool {
        self.in_range
    }

    pub fn is_muted(&self) -> bool {
        self.muted
    }

    pub fn is_disabled(&self) -> bool {
        self.disabled
    }

    pub fn is_today(&self) -> bool {
        self.today
    }
}

/// An unstyled, pre-wired calendar item passed to the item slot.
#[derive(IntoElement)]
pub struct CalendarItem {
    base: crate::ObservedElement<gpui::Stateful<gpui::Div>>,
    state: CalendarItemState,
    style: StyleRefinement,
    children: Vec<AnyElement>,
}

impl CalendarItem {
    fn new(id: impl Into<ElementId>, state: CalendarItemState) -> Self {
        Self {
            base: div().id(id.into()).test_support(),
            state,
            style: StyleRefinement::default(),
            children: vec![],
        }
    }
    // Keep the default visible label available to assistive technology even
    // when a presentation assigns a role that does not derive a name from children.
    fn with_label(self, label: SharedString) -> Self {
        self.aria_label(label.clone()).child(label)
    }

    pub fn item_state(&self) -> CalendarItemState {
        self.state
    }

    /// Remove the default label so a styled facade can provide custom content.
    pub fn clear_children(mut self) -> Self {
        self.children.clear();
        self
    }
}
impl ParentElement for CalendarItem {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}
impl Styled for CalendarItem {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}
impl InteractiveElement for CalendarItem {
    fn interactivity(&mut self) -> &mut gpui::Interactivity {
        self.base.interactivity()
    }

    fn track_focus(mut self, handle: &gpui::FocusHandle) -> Self {
        self.base = self.base.track_focus(handle);
        self
    }
}
impl StatefulInteractiveElement for CalendarItem {}
impl RenderOnce for CalendarItem {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        self.base.children(self.children).refine_style(&self.style)
    }
}

type ItemRenderer =
    Rc<dyn Fn(CalendarItem, CalendarItemState, &mut Window, &mut App) -> AnyElement>;
type Labeler = Rc<dyn Fn(CalendarItemKind, i32) -> SharedString>;

/// Complete unstyled calendar structure and behavior.
///
/// Base owns navigation, view switching, grids, disabled/selection state and
/// click handling. The UI crate only decorates the pre-wired item slot.
#[derive(IntoElement)]
pub struct Calendar {
    id: ElementId,
    state: Entity<CalendarState>,
    number_of_months: usize,
    first_day_of_week: Weekday,
    style: StyleRefinement,
    item: ItemRenderer,
    label: Labeler,
}

impl Calendar {
    pub fn new(id: impl Into<ElementId>, state: &Entity<CalendarState>) -> Self {
        Self {
            id: id.into(),
            state: state.clone(),
            number_of_months: 1,
            first_day_of_week: Weekday::Sun,
            style: StyleRefinement::default(),
            item: Rc::new(|item, _, _, _| item.into_any_element()),
            label: Rc::new(|kind, value| match kind {
                CalendarItemKind::Previous => "‹".into(),
                CalendarItemKind::Next => "›".into(),
                CalendarItemKind::Weekday => value.to_string().into(),
                _ => value.to_string().into(),
            }),
        }
    }
    pub fn number_of_months(mut self, count: usize) -> Self {
        self.number_of_months = count.max(1);
        self
    }
    pub fn first_day_of_week(mut self, day: Weekday) -> Self {
        self.first_day_of_week = day;
        self
    }
    pub fn item(
        mut self,
        render: impl Fn(CalendarItem, CalendarItemState, &mut Window, &mut App) -> AnyElement + 'static,
    ) -> Self {
        self.item = Rc::new(render);
        self
    }
    pub fn label(
        mut self,
        label: impl Fn(CalendarItemKind, i32) -> SharedString + 'static,
    ) -> Self {
        self.label = Rc::new(label);
        self
    }

    fn render_item(
        &self,
        id: impl Into<ElementId>,
        state: CalendarItemState,
        value: i32,
        window: &mut Window,
        cx: &mut App,
    ) -> AnyElement {
        let label = (self.label)(state.kind(), value);
        (self.item)(
            CalendarItem::new(id, state).with_label(label),
            state,
            window,
            cx,
        )
    }
}
impl Styled for Calendar {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for Calendar {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let count = self.number_of_months;
        self.state
            .update(cx, |s, cx| s.set_number_of_months(count, window, cx));
        let view = self.state.read(cx).view();
        let mut header = h_flex().items_center().justify_between().child({
            let st = CalendarItemState::new(CalendarItemKind::Previous).disabled(
                view.is_month() || (view.is_year() && !self.state.read(cx).has_prev_year_page()),
            );
            let mut item =
                CalendarItem::new("calendar-prev", st).with_label((self.label)(st.kind(), 0));
            if !st.is_disabled() {
                let entity = self.state.clone();
                item = item.on_click(move |_, _window, cx| {
                    entity.update(cx, |s, cx| {
                        if s.view().is_day() {
                            s.prev_month();
                        } else {
                            s.prev_year_page();
                        }
                        cx.notify();
                    })
                });
            }
            (self.item)(item, st, window, cx)
        });
        if count == 1 {
            let (month, year) = {
                let s = self.state.read(cx);
                (s.current_month() as i32, s.current_year())
            };
            for (kind, value, active) in [
                (CalendarItemKind::MonthToggle, month, view.is_month()),
                (CalendarItemKind::YearToggle, year, view.is_year()),
            ] {
                let st = CalendarItemState::new(kind).active(active);
                let entity = self.state.clone();
                let mut item = CalendarItem::new(format!("calendar-{kind:?}"), st)
                    .with_label((self.label)(kind, value));
                item = item.on_click(move |_, _, cx| {
                    entity.update(cx, |s, cx| {
                        s.set_view(
                            if s.view()
                                == match kind {
                                    CalendarItemKind::MonthToggle => CalendarView::Month,
                                    _ => CalendarView::Year,
                                }
                            {
                                CalendarView::Day
                            } else {
                                match kind {
                                    CalendarItemKind::MonthToggle => CalendarView::Month,
                                    _ => CalendarView::Year,
                                }
                            },
                        );
                        cx.notify();
                    })
                });
                header = header.child((self.item)(item, st, window, cx));
            }
        } else {
            for offset in 0..count {
                let (y, m) = self.state.read(cx).offset_year_month(offset);
                header = header.child(
                    div().text_sm().font_medium().child(
                        v_flex()
                            .items_center()
                            .child((self.label)(CalendarItemKind::MonthToggle, m as i32))
                            .child(y.to_string()),
                    ),
                );
            }
        }
        header = header.child({
            let st = CalendarItemState::new(CalendarItemKind::Next).disabled(
                view.is_month() || (view.is_year() && !self.state.read(cx).has_next_year_page()),
            );
            let mut item =
                CalendarItem::new("calendar-next", st).with_label((self.label)(st.kind(), 0));
            if !st.is_disabled() {
                let entity = self.state.clone();
                item = item.on_click(move |_, _, cx| {
                    entity.update(cx, |s, cx| {
                        if s.view().is_day() {
                            s.next_month()
                        } else {
                            s.next_year_page();
                        }
                        cx.notify();
                    })
                });
            }
            (self.item)(item, st, window, cx)
        });

        let mut body = match picker_grid_layout(view) {
            None => h_flex().justify_around(),
            Some((columns, horizontal_gap)) => {
                div().grid().grid_cols(columns).gap_x(px(horizontal_gap))
            }
        };
        if view.is_day() {
            for offset in 0..count {
                let (year, month_number) = self.state.read(cx).offset_year_month(offset);
                let weeks = days_in_month(year, month_number, self.first_day_of_week);
                let mut month = v_flex();
                let mut header_row = h_flex();
                for weekday in 0..7 {
                    let st = CalendarItemState::new(CalendarItemKind::Weekday)
                        .muted(true)
                        .disabled(true);
                    header_row = header_row.child(self.render_item(
                        format!("weekday-{offset}-{weekday}"),
                        st,
                        (weekday + self.first_day_of_week.num_days_from_sunday() as i32) % 7,
                        window,
                        cx,
                    ));
                }
                month = month.child(header_row);
                for (week_index, week) in weeks.iter().enumerate() {
                    let mut week_row = h_flex();
                    for date in week {
                        let date = *date;
                        let st = {
                            let s = self.state.read(cx);
                            let (_, m) = s.offset_year_month(offset);
                            let disabled =
                                s.disabled_matcher_ref().is_some_and(|x| x.matched(&date));
                            CalendarItemState::new(CalendarItemKind::Day)
                                .active(s.date().is_active(&date))
                                .in_range(s.date().is_in_range(&date))
                                .muted(date.month() != m || disabled)
                                .disabled(disabled)
                                .today(date == s.today())
                        };
                        let mut item =
                            CalendarItem::new(format!("calendar-{date}-{offset}-{week_index}"), st)
                                .with_label((self.label)(st.kind(), date.day() as i32))
                                .aria_label(date.to_string());
                        if !st.is_disabled() {
                            let entity = self.state.clone();
                            item = item.on_click(move |_, _, cx| {
                                entity.update(cx, |s, cx| {
                                    s.activate_date(date, cx);
                                })
                            });
                        }
                        week_row = week_row.child((self.item)(item, st, window, cx));
                    }
                    month = month.child(week_row);
                }
                body = body.child(month);
            }
        } else if view.is_month() {
            let current = self.state.read(cx).current_month();
            for month in 1..=12u8 {
                let st = CalendarItemState::new(CalendarItemKind::Month).active(month == current);
                let entity = self.state.clone();
                let item = CalendarItem::new(format!("calendar-month-{month}"), st)
                    .with_label((self.label)(st.kind(), month as i32))
                    .on_click(move |_, _, cx| {
                        entity.update(cx, |s, cx| {
                            s.select_month(month);
                            cx.notify();
                        })
                    });
                body = body.child((self.item)(item, st, window, cx));
            }
        } else {
            let current = self.state.read(cx).current_year();
            let years = self.state.read(cx).years_on_page().to_vec();
            for year in years {
                let st = CalendarItemState::new(CalendarItemKind::Year).active(year == current);
                let entity = self.state.clone();
                let item = CalendarItem::new(format!("calendar-year-{year}"), st)
                    .with_label((self.label)(st.kind(), year))
                    .on_click(move |_, _, cx| {
                        entity.update(cx, |s, cx| {
                            s.select_year(year);
                            cx.notify();
                        })
                    });
                body = body.child((self.item)(item, st, window, cx));
            }
        }
        v_flex()
            .id(self.id)
            .track_focus(&self.state.read(cx).focus_handle)
            .child(header)
            .child(body)
            .refine_style(&self.style)
    }
}

fn days_in_month(year: i32, month: u32, first_day: Weekday) -> Vec<Vec<NaiveDate>> {
    let total = year as i64 * 12 + month as i64 - 1;
    let year = total.div_euclid(12) as i32;
    let month = total.rem_euclid(12) as u32 + 1;
    let first = NaiveDate::from_ymd_opt(year, month, 1).unwrap();
    let next = if month == 12 {
        NaiveDate::from_ymd_opt(year + 1, 1, 1).unwrap()
    } else {
        NaiveDate::from_ymd_opt(year, month + 1, 1).unwrap()
    };
    let offset =
        (first.weekday().num_days_from_sunday() + 7 - first_day.num_days_from_sunday()) % 7;
    let start = first - chrono::Duration::days(offset as i64);
    let count = ((next - start).num_days() as usize).div_ceil(7) * 7;
    (0..count)
        .map(|n| start + chrono::Duration::days(n as i64))
        .collect::<Vec<_>>()
        .chunks(7)
        .map(<[_]>::to_vec)
        .collect()
}

#[cfg(test)]
mod tests {
    use std::{cell::RefCell, rc::Rc};

    use gpui::{AppContext as _, Context, Entity, IntoElement, Render, Subscription, Window};

    use super::*;

    #[gpui::test]
    fn calendar_items_expose_names_in_every_view(cx: &mut gpui::TestAppContext) {
        use gpui::{Element as _, accesskit};
        struct Names {
            calendar: Entity<CalendarState>,
            labels: Rc<RefCell<Vec<(CalendarItemKind, String)>>>,
        }
        impl Render for Names {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                let labels = self.labels.clone();
                labels.borrow_mut().clear();
                Calendar::new("named-calendar", &self.calendar).item(move |item, state, _, _| {
                    let mut node = accesskit::Node::new(accesskit::Role::Button);
                    item.base.write_a11y_info(&mut node);
                    labels
                        .borrow_mut()
                        .push((state.kind(), node.label().unwrap_or("").to_string()));
                    item.into_any_element()
                })
            }
        }
        let (view, cx) = cx.add_window_view(|window, cx| Names {
            calendar: cx.new(|cx| CalendarState::new(window, cx)),
            labels: Rc::new(RefCell::new(Vec::new())),
        });
        for mode in [CalendarView::Day, CalendarView::Month, CalendarView::Year] {
            cx.update(|window, cx| {
                view.read(cx).calendar.clone().update(cx, |state, cx| {
                    state.apply_date(Date::Single(Some(
                        NaiveDate::from_ymd_opt(2026, 9, 7).unwrap(),
                    )));
                    state.set_view(mode);
                    cx.notify();
                });
                window.draw(cx).clear(cx);
                let labels = view.read(cx).labels.borrow();
                assert!(!labels.is_empty());
                for (kind, label) in labels.iter() {
                    assert!(!label.is_empty(), "missing name for {kind:?}");
                }
                if mode.is_day() {
                    assert!(labels.iter().any(
                        |(kind, label)| *kind == CalendarItemKind::Day && label == "2026-09-07"
                    ));
                }
            });
        }
    }

    struct EventHarness {
        calendar: Entity<CalendarState>,
        events: Rc<RefCell<Vec<Date>>>,
        _subscription: Option<Subscription>,
    }
    impl EventHarness {
        fn new(window: &mut Window, cx: &mut Context<Self>) -> Self {
            let calendar = cx.new(|cx| CalendarState::new(window, cx));
            let events = Rc::new(RefCell::new(Vec::new()));
            let mut this = Self {
                calendar: calendar.clone(),
                events: events.clone(),
                _subscription: None,
            };
            this._subscription = Some(cx.subscribe(&calendar, move |_, _, event, _| {
                let CalendarEvent::Selected(date) = event;
                events.borrow_mut().push(*date);
            }));
            this
        }
    }
    impl Render for EventHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            Empty
        }
    }
    fn state(cx: &mut gpui::TestAppContext, date: Date) -> gpui::Entity<CalendarState> {
        let (state, _) = cx.add_window_view(CalendarState::new);
        state.update(cx, |state, _| {
            state.date = date;
        });
        state
    }
    #[gpui::test]
    fn range_selection_restarts_and_completes(cx: &mut gpui::TestAppContext) {
        let s = state(cx, Date::Range(None, None));
        let a = NaiveDate::from_ymd_opt(2025, 2, 10).unwrap();
        let b = NaiveDate::from_ymd_opt(2025, 2, 12).unwrap();
        s.update(cx, |s, _| {
            assert!(!s.select_date(a));
            assert!(s.select_date(b));
        });
        assert_eq!(
            s.read_with(cx, |s, _| s.date()),
            Date::Range(Some(a), Some(b))
        );
        s.update(cx, |s, _| assert!(!s.select_date(a)));
        assert_eq!(s.read_with(cx, |s, _| s.date()), Date::Range(Some(a), None));
    }
    #[gpui::test]
    fn disabled_date_is_rejected(cx: &mut gpui::TestAppContext) {
        let s = state(cx, Date::Single(None));
        s.update(cx, |s, _| {
            s.disabled_matcher = Some(Rc::new(Matcher::range(
                Some(NaiveDate::from_ymd_opt(2025, 1, 1).unwrap()),
                Some(NaiveDate::from_ymd_opt(2025, 1, 31).unwrap()),
            )))
        });
        s.update(cx, |s, _| {
            assert!(!s.select_date(NaiveDate::from_ymd_opt(2025, 1, 2).unwrap()))
        });
    }
    #[gpui::test]
    fn month_navigation_crosses_year(cx: &mut gpui::TestAppContext) {
        let s = state(
            cx,
            Date::Single(Some(NaiveDate::from_ymd_opt(2025, 1, 1).unwrap())),
        );
        s.update(cx, |s, _| {
            s.apply_date(Date::Single(Some(
                NaiveDate::from_ymd_opt(2025, 1, 1).unwrap(),
            )));
            s.prev_month();
        });
        assert_eq!(
            s.read_with(cx, |s, _| (s.current_year(), s.current_month())),
            (2024, 12)
        );
        s.update(cx, |s, _| s.next_month());
        assert_eq!(
            s.read_with(cx, |s, _| (s.current_year(), s.current_month())),
            (2025, 1)
        );
    }

    #[gpui::test]
    fn six_week_month_is_not_truncated(cx: &mut gpui::TestAppContext) {
        let s = state(
            cx,
            Date::Single(Some(NaiveDate::from_ymd_opt(2025, 8, 1).unwrap())),
        );
        s.update(cx, |s, _| {
            s.apply_date(Date::Single(Some(
                NaiveDate::from_ymd_opt(2025, 8, 1).unwrap(),
            )));
            assert_eq!(s.month_days().len(), 1);
            assert_eq!(s.month_days()[0].len(), 6);
            assert_eq!(s.days().len(), 6);
            assert_eq!(s.month_days()[0][5][0].day(), 31);
        });
    }

    #[gpui::test]
    fn day_month_and_year_views_have_complete_transitions(cx: &mut gpui::TestAppContext) {
        let s = state(cx, Date::Single(None));
        s.update(cx, |s, _| {
            assert_eq!(s.view(), CalendarView::Day);
            s.set_view(CalendarView::Month);
            s.select_month(11);
            assert_eq!((s.view(), s.current_month()), (CalendarView::Day, 11));
            s.set_view(CalendarView::Year);
            s.select_year(2032);
            assert_eq!((s.view(), s.current_year()), (CalendarView::Day, 2032));
        });
    }

    #[test]
    fn picker_views_use_stable_grid_layouts() {
        assert_eq!(picker_grid_layout(CalendarView::Month), Some((3, 4.)));
        assert_eq!(picker_grid_layout(CalendarView::Year), Some((5, 4.)));
        assert_eq!(picker_grid_layout(CalendarView::Day), None);
    }

    #[gpui::test]
    fn year_page_navigation_respects_both_bounds(cx: &mut gpui::TestAppContext) {
        let s = state(cx, Date::Single(None));
        s.update(cx, |s, _| {
            s.apply_year_range((2000, 2041));
            while s.prev_year_page() {}
            assert!(!s.has_prev_year_page());
            assert!(!s.prev_year_page());
            assert!(s.next_year_page());
            while s.next_year_page() {}
            assert!(!s.has_next_year_page());
            assert!(!s.next_year_page());
        });
    }

    #[gpui::test]
    fn activation_emits_only_for_complete_enabled_values(cx: &mut gpui::TestAppContext) {
        let (harness, _) = cx.add_window_view(EventHarness::new);
        let s = harness.read_with(cx, |h, _| h.calendar.clone());
        s.update(cx, |s, _| s.date = Date::Range(None, None));
        let start = NaiveDate::from_ymd_opt(2025, 4, 4).unwrap();
        let end = NaiveDate::from_ymd_opt(2025, 4, 8).unwrap();
        s.update(cx, |s, cx| {
            assert!(!s.activate_date(start, cx));
            assert!(s.activate_date(end, cx));
            assert_eq!(s.date(), Date::Range(Some(start), Some(end)));
            s.set_disabled_matcher_shared(Some(Rc::new(Matcher::custom(move |d| *d == start))));
            assert!(!s.activate_date(start, cx));
            assert_eq!(s.date(), Date::Range(Some(start), Some(end)));
        });
        assert_eq!(
            harness.read_with(cx, |h, _| h.events.borrow().clone()),
            vec![Date::Range(Some(start), Some(end))]
        );

        s.update(cx, |s, cx| {
            s.date = Date::Single(None);
            assert!(s.activate_date(end, cx));
            assert_eq!(s.date(), Date::Single(Some(end)));
        });
        assert_eq!(
            harness.read_with(cx, |h, _| h.events.borrow().clone()),
            vec![Date::Range(Some(start), Some(end)), Date::Single(Some(end))]
        );
    }
}
