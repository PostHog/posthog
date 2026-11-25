use chrono::Weekday;
use gpui::{
    App, ElementId, Entity, InteractiveElement, IntoElement, ParentElement, RenderOnce,
    SharedString, StyleRefinement, Styled, Window, prelude::FluentBuilder as _, px,
};
use rust_i18n::t;

use crate::{ActiveTheme, Icon, IconName, Sizable, Size, StyledExt as _};

use gpui_base::{Calendar as BaseCalendar, CalendarItemKind};
pub use gpui_base::{CalendarEvent, CalendarState, Date, Matcher};

fn month_name(month: i32) -> SharedString {
    match month {
        1 => t!("Calendar.month.January"),
        2 => t!("Calendar.month.February"),
        3 => t!("Calendar.month.March"),
        4 => t!("Calendar.month.April"),
        5 => t!("Calendar.month.May"),
        6 => t!("Calendar.month.June"),
        7 => t!("Calendar.month.July"),
        8 => t!("Calendar.month.August"),
        9 => t!("Calendar.month.September"),
        10 => t!("Calendar.month.October"),
        11 => t!("Calendar.month.November"),
        12 => t!("Calendar.month.December"),
        _ => "".into(),
    }
    .into()
}

fn uses_compact_text(kind: CalendarItemKind) -> bool {
    kind == CalendarItemKind::Month
}

/// Styled facade for the complete behavior and structure in `gpui-base`.
#[derive(IntoElement)]
pub struct Calendar {
    id: ElementId,
    size: Size,
    state: Entity<CalendarState>,
    style: StyleRefinement,
    number_of_months: usize,
    first_day_of_week: Weekday,
}

impl Calendar {
    pub fn new(state: &Entity<CalendarState>) -> Self {
        Self {
            id: ("calendar", state.entity_id()).into(),
            size: Size::default(),
            state: state.clone(),
            style: StyleRefinement::default(),
            number_of_months: 1,
            first_day_of_week: Weekday::Sun,
        }
    }
    pub fn number_of_months(mut self, count: usize) -> Self {
        self.number_of_months = count;
        self
    }
    /// Set the first day of the week for the calendar.
    pub fn first_day_of_week(mut self, day: Weekday) -> Self {
        self.first_day_of_week = day;
        self
    }
}
impl Sizable for Calendar {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}
impl Styled for Calendar {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for Calendar {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let size = self.size;
        let month_count = self.number_of_months.max(1) as f32;
        BaseCalendar::new(self.id, &self.state)
            .number_of_months(self.number_of_months)
            .first_day_of_week(self.first_day_of_week)
            .label(|kind, value| match kind {
                CalendarItemKind::Previous => "‹".into(),
                CalendarItemKind::Next => "›".into(),
                CalendarItemKind::MonthToggle | CalendarItemKind::Month => month_name(value),
                CalendarItemKind::Weekday => match value {
                    0 => t!("Calendar.week.0"),
                    1 => t!("Calendar.week.1"),
                    2 => t!("Calendar.week.2"),
                    3 => t!("Calendar.week.3"),
                    4 => t!("Calendar.week.4"),
                    5 => t!("Calendar.week.5"),
                    _ => t!("Calendar.week.6"),
                }
                .into(),
                _ => value.to_string().into(),
            })
            .item(move |item, state, _, cx| {
                let item = match state.kind() {
                    CalendarItemKind::Previous => item
                        .clear_children()
                        .child(Icon::new(IconName::ChevronLeft).size_4()),
                    CalendarItemKind::Next => item
                        .clear_children()
                        .child(Icon::new(IconName::ChevronRight).size_4()),
                    _ => item,
                };
                item.map(|this| match size {
                    Size::Small => this.size_7().rounded(cx.theme().radius / 2.),
                    Size::Large => this.size_10().rounded(cx.theme().radius * 2.),
                    _ => this.size_8().rounded(cx.theme().radius),
                })
                .flex()
                .items_center()
                .justify_center()
                .when(
                    state.kind() != CalendarItemKind::Weekday,
                    |this| match size {
                        Size::Small => this.text_xs(),
                        _ => this.text_sm(),
                    },
                )
                .when(state.kind() == CalendarItemKind::Weekday, |this| {
                    this.text_xs()
                        .font_normal()
                        .text_color(cx.theme().muted_foreground)
                })
                .when(uses_compact_text(state.kind()), |this| this.text_xs())
                .when(
                    matches!(
                        state.kind(),
                        CalendarItemKind::MonthToggle | CalendarItemKind::YearToggle
                    ),
                    |this| this.text_sm().font_medium(),
                )
                .when(
                    matches!(
                        state.kind(),
                        CalendarItemKind::Month | CalendarItemKind::MonthToggle
                    ),
                    |this| {
                        this.when(state.kind() == CalendarItemKind::Month, |this| {
                            this.w_full().my_1()
                        })
                        .when(state.kind() == CalendarItemKind::MonthToggle, |this| {
                            this.w_auto().px_2()
                        })
                    },
                )
                .when(
                    matches!(
                        state.kind(),
                        CalendarItemKind::Year | CalendarItemKind::YearToggle
                    ),
                    |this| {
                        this.when(state.kind() == CalendarItemKind::Year, |this| {
                            this.w_full().my_1()
                        })
                        .when(state.kind() == CalendarItemKind::YearToggle, |this| {
                            this.w_auto().px_2()
                        })
                    },
                )
                .when(state.is_muted(), |this| {
                    this.text_color(cx.theme().muted_foreground)
                        .when(state.is_disabled(), |this| this.opacity(0.5))
                })
                .when(state.is_in_range(), |this| {
                    this.bg(cx.theme().accent)
                        .text_color(cx.theme().accent_foreground)
                })
                .when(
                    !state.is_active()
                        && !state.is_disabled()
                        && state.kind() != CalendarItemKind::Weekday,
                    |this| {
                        this.hover(|this| {
                            this.bg(cx.theme().tokens.secondary_hover)
                                .text_color(cx.theme().foreground)
                        })
                    },
                )
                .when(state.is_active(), |this| {
                    this.bg(cx.theme().tokens.primary)
                        .text_color(cx.theme().primary_foreground)
                })
                .when(state.is_today() && !state.is_active(), |this| {
                    this.bg(cx.theme().accent)
                        .text_color(cx.theme().accent_foreground)
                })
                .into_any_element()
            })
            .border_1()
            .border_color(cx.theme().border)
            .rounded(cx.theme().radius_lg)
            .p_3()
            .gap_0p5()
            .map(|this| match size {
                Size::Small => this.w(px(220.) * month_count),
                Size::Large => this.w(px(304.) * month_count),
                _ => this.w(px(248.) * month_count),
            })
            .refine_style(&self.style)
    }
}

#[cfg(test)]
mod tests {
    use super::{CalendarItemKind, Date, uses_compact_text};
    use chrono::NaiveDate;

    #[test]
    fn date_display_is_stable() {
        assert_eq!(
            Date::Single(Some(NaiveDate::from_ymd_opt(2024, 8, 3).unwrap())).to_string(),
            "2024-08-03"
        );
        assert_eq!(Date::Single(None).to_string(), "nil");
    }

    #[test]
    fn only_month_options_use_compact_text() {
        assert!(uses_compact_text(CalendarItemKind::Month));
        assert!(!uses_compact_text(CalendarItemKind::MonthToggle));
        assert!(!uses_compact_text(CalendarItemKind::Day));
    }
}
