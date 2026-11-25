use chrono::{Datelike, Duration, NaiveDate, Weekday};

trait NaiveDateExt {
    fn days_in_month(&self) -> i32;
    fn is_leap_year(&self) -> bool;
}

impl NaiveDateExt for chrono::NaiveDate {
    fn days_in_month(&self) -> i32 {
        let month = self.month();
        match month {
            1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
            4 | 6 | 9 | 11 => 30,
            2 => {
                if self.is_leap_year() {
                    29
                } else {
                    28
                }
            }
            _ => panic!("Invalid month: {}", month),
        }
    }

    fn is_leap_year(&self) -> bool {
        let year = self.year();
        return year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
    }
}

pub(crate) fn days_in_month(year: i32, month: u32, first_day: Weekday) -> Vec<Vec<NaiveDate>> {
    let mut year = year;
    let mut month = month;
    if month > 12 {
        year += 1;
        month = 1;
    }
    if month < 1 {
        year -= 1;
        month = 12;
    }

    let date = NaiveDate::from_ymd_opt(year, month, 1).unwrap();
    let num_days = date.days_in_month();
    let start_weekday =
        (date.weekday().num_days_from_sunday() + 7 - first_day.num_days_from_sunday()) % 7;

    // Get the days in the month, 2023-02 will returns
    // "29|30|31| 1| 2| 3| 4",
    // " 5| 6| 7| 8| 9|10|11",
    // "12|13|14|15|16|17|18",
    // "19|20|21|22|23|24|25",
    // "26|27|28| 1| 2| 3| 4",
    let mut days = vec![];
    for n in 0..5 {
        let mut week_days = vec![];
        for weekday in 0..7 {
            let (mut y, mut m) = (year, month);

            // If the day is less than the start weekday, we need to go back to the previous month.
            if n == 0 && weekday < start_weekday {
                m = if m == 1 { 12 } else { m - 1 };
                y = if m == 1 { year - 1 } else { y };
            }

            // If start_weekday is 3, and n is 0 and weekday is 3, then day is 1.
            // If start_weekday is 3, and n is 1 and weekday is 4, then day is 9.
            let day = n * 7 + weekday as i32 - start_weekday as i32;

            // If the day is greater than the number of days in the month, we need to go to the next month.
            if day > num_days {
                m = if m == 12 { 1 } else { m + 1 };
                y = if m == 1 { year + 1 } else { y };
            }

            #[allow(clippy::expect_fun_call)]
            let date = date
                .checked_add_signed(Duration::days(day as i64))
                .expect(&format!("invalid date {}-{} days {}", y, m, day));
            week_days.push(date);
        }

        days.push(week_days);
    }

    days
}

#[cfg(test)]
mod tests {
    use chrono::{Datelike, NaiveDate, Weekday};

    use super::{NaiveDateExt, days_in_month};

    #[test]
    fn test_days_in_month() {
        assert_eq!(
            NaiveDate::from_ymd_opt(2024, 2, 1).unwrap().days_in_month(),
            29
        );
        assert_eq!(
            NaiveDate::from_ymd_opt(2023, 2, 1).unwrap().days_in_month(),
            28
        );
        assert_eq!(
            NaiveDate::from_ymd_opt(2023, 1, 1).unwrap().days_in_month(),
            31
        );
        assert_eq!(
            NaiveDate::from_ymd_opt(2023, 4, 1).unwrap().days_in_month(),
            30
        );
    }

    #[test]
    fn test_days() {
        #[track_caller]
        fn assert_case(date: NaiveDate, first_day: Weekday, expected: Vec<&str>) {
            let out = days_in_month(date.year(), date.month(), first_day)
                .iter()
                .map(|week| {
                    week.iter()
                        .map(|d| {
                            if d.year() == date.year() && d.month() == date.month() {
                                format!("{:2}", d.day())
                            } else if d.year() == date.year() {
                                format!("{}-{}", d.month(), d.day())
                            } else {
                                format!("{}-{}-{}", d.year(), d.month(), d.day())
                            }
                        })
                        .collect::<Vec<_>>()
                        .join("|")
                })
                .collect::<Vec<_>>();

            assert_eq!(out, expected);
        }

        assert_case(
            NaiveDate::from_ymd_opt(2024, 8, 1).unwrap(),
            Weekday::Sun,
            vec![
                "7-28|7-29|7-30|7-31| 1| 2| 3",
                " 4| 5| 6| 7| 8| 9|10",
                "11|12|13|14|15|16|17",
                "18|19|20|21|22|23|24",
                "25|26|27|28|29|30|31",
            ],
        );
        assert_case(
            NaiveDate::from_ymd_opt(2025, 1, 1).unwrap(),
            Weekday::Sun,
            vec![
                "2024-12-29|2024-12-30|2024-12-31| 1| 2| 3| 4",
                " 5| 6| 7| 8| 9|10|11",
                "12|13|14|15|16|17|18",
                "19|20|21|22|23|24|25",
                "26|27|28|29|30|31|2-1",
            ],
        );

        assert_case(
            NaiveDate::from_ymd_opt(2024, 2, 1).unwrap(),
            Weekday::Sun,
            vec![
                "1-28|1-29|1-30|1-31| 1| 2| 3",
                " 4| 5| 6| 7| 8| 9|10",
                "11|12|13|14|15|16|17",
                "18|19|20|21|22|23|24",
                "25|26|27|28|29|3-1|3-2",
            ],
        );
        assert_case(
            NaiveDate::from_ymd_opt(2023, 2, 20).unwrap(),
            Weekday::Sun,
            vec![
                "1-29|1-30|1-31| 1| 2| 3| 4",
                " 5| 6| 7| 8| 9|10|11",
                "12|13|14|15|16|17|18",
                "19|20|21|22|23|24|25",
                "26|27|28|3-1|3-2|3-3|3-4",
            ],
        );

        // Monday-first week: Feb 2023 starts on a Wednesday, so the grid
        // shifts to start on Monday (column 0 = Mon 30 Jan).
        assert_case(
            NaiveDate::from_ymd_opt(2023, 2, 1).unwrap(),
            Weekday::Mon,
            vec![
                "1-30|1-31| 1| 2| 3| 4| 5",
                " 6| 7| 8| 9|10|11|12",
                "13|14|15|16|17|18|19",
                "20|21|22|23|24|25|26",
                "27|28|3-1|3-2|3-3|3-4|3-5",
            ],
        );
    }
}
