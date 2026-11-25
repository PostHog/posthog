//! Public schedule semantics, independent of the execution backend.
use anyhow::{Context, Result, bail};
use chrono::{DateTime, Datelike, Duration, NaiveTime, TimeZone, Utc};
use chrono_tz::Tz;
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "camelCase", deny_unknown_fields)]
pub enum Schedule {
    After {
        #[serde(rename = "delayMs")]
        delay_ms: i64,
    },
    At {
        at: DateTime<Utc>,
    },
    Interval {
        #[serde(rename = "everyMs")]
        every_ms: i64,
    },
    Calendar {
        frequency: String,
        time: String,
        timezone: String,
        #[serde(default)]
        days: Vec<String>,
        #[serde(default, rename = "dayOfMonth")]
        day_of_month: Option<u32>,
    },
    Cron {
        expression: String,
        timezone: String,
    },
}
impl Schedule {
    pub fn recurring(&self) -> bool {
        matches!(
            self,
            Self::Interval { .. } | Self::Calendar { .. } | Self::Cron { .. }
        )
    }
    pub fn next(&self, after: DateTime<Utc>) -> Result<DateTime<Utc>> {
        match self {
            Self::After { delay_ms } => {
                if !(1..=31_536_000_000i64).contains(delay_ms) {
                    bail!("delayMs must be 1 ms through 365 days");
                }
                after
                    .checked_add_signed(Duration::milliseconds(*delay_ms))
                    .context("Date overflow")
            }
            Self::At { at } => {
                if *at <= after {
                    bail!("at must be in the future");
                }
                Ok(*at)
            }
            Self::Interval { every_ms } => {
                if !(60_000..=31_536_000_000i64).contains(every_ms) {
                    bail!("everyMs must be 1 minute through 365 days");
                }
                after
                    .checked_add_signed(Duration::milliseconds(*every_ms))
                    .context("Date overflow")
            }
            Self::Calendar {
                frequency,
                time,
                timezone,
                days,
                day_of_month,
            } => {
                let time =
                    NaiveTime::parse_from_str(time, "%H:%M").context("time must be HH:MM")?;
                let tz: Tz = timezone.parse().context("Use an IANA timezone")?;
                let weekdays = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
                if days.iter().any(|d| !weekdays.contains(&d.as_str())) {
                    bail!("Invalid weekday");
                }
                match frequency.as_str() {
                    "daily" if days.is_empty() && day_of_month.is_none() => {}
                    "weekly" if !days.is_empty() && day_of_month.is_none() => {}
                    "monthly"
                        if days.is_empty()
                            && day_of_month.is_some_and(|d| (1..=31).contains(&d)) => {}
                    _ => bail!("Use daily, weekly with days, or monthly with dayOfMonth"),
                }
                let start = after.with_timezone(&tz).date_naive();
                for offset in 0..=366 * 5 {
                    let date = start
                        .checked_add_signed(Duration::days(offset))
                        .context("Date overflow")?;
                    if frequency == "weekly"
                        && !days
                            .iter()
                            .any(|d| d == weekdays[date.weekday().num_days_from_sunday() as usize])
                    {
                        continue;
                    }
                    if frequency == "monthly" && Some(date.day()) != *day_of_month {
                        continue;
                    }
                    // Nonexistent local times are skipped; repeated times fire once,
                    // at the earlier occurrence.
                    if let Some(dt) = tz.from_local_datetime(&date.and_time(time)).earliest()
                        && dt.with_timezone(&Utc) > after
                    {
                        return Ok(dt.with_timezone(&Utc));
                    }
                }
                bail!("No occurrence within five years")
            }
            Self::Cron {
                expression,
                timezone,
            } => cron_next(expression, timezone, after),
        }
    }
}
// Five-field numeric cron. Sunday is 0 or 7; day-of-month/day-of-week use OR
// when both are restricted, matching traditional Unix cron.
fn field(text: &str, min: u32, max: u32) -> Result<Vec<u32>> {
    let mut values = Vec::new();
    for part in text.split(',') {
        let (range, step) = match part.split_once('/') {
            Some((r, s)) => (r, s.parse::<u32>().context("Invalid cron step")?),
            None => (part, 1),
        };
        if step == 0 || step > max + 1 {
            bail!("Invalid cron step");
        }
        let (lo, hi) = if range == "*" {
            (min, max)
        } else if let Some((a, b)) = range.split_once('-') {
            (a.parse()?, b.parse()?)
        } else {
            let n = range.parse()?;
            (n, if part.contains('/') { max } else { n })
        };
        if lo < min || hi > max || lo > hi {
            bail!("Cron field out of range");
        }
        values.extend((lo..=hi).step_by(step as usize));
    }
    values.sort_unstable();
    values.dedup();
    Ok(values)
}
fn cron_next(expression: &str, timezone: &str, after: DateTime<Utc>) -> Result<DateTime<Utc>> {
    if expression.len() > 256 {
        bail!("Cron expression too long");
    }
    let f: Vec<_> = expression.split_whitespace().collect();
    if f.len() != 5 {
        bail!("Cron needs five fields: minute hour day month weekday");
    }
    let minutes = field(f[0], 0, 59)?;
    let hours = field(f[1], 0, 23)?;
    let days = field(f[2], 1, 31)?;
    let months = field(f[3], 1, 12)?;
    let weekdays = field(f[4], 0, 7)?;
    let tz: Tz = timezone.parse().context("Use an IANA timezone")?;
    let start = after.with_timezone(&tz).date_naive();
    for offset in 0..=366 * 5 {
        let date = start
            .checked_add_signed(Duration::days(offset))
            .context("Date overflow")?;
        if !months.contains(&date.month()) {
            continue;
        }
        let dom = days.contains(&date.day());
        let w = date.weekday().num_days_from_sunday();
        let dow = weekdays.contains(&w) || (w == 0 && weekdays.contains(&7));
        let matches = match (f[2] == "*", f[4] == "*") {
            (true, _) => dow,
            (_, true) => dom,
            _ => dom || dow,
        };
        if !matches {
            continue;
        }
        for h in &hours {
            for m in &minutes {
                if let Some(dt) = tz
                    .from_local_datetime(&date.and_hms_opt(*h, *m, 0).unwrap())
                    .earliest()
                    && dt.with_timezone(&Utc) > after
                {
                    return Ok(dt.with_timezone(&Utc));
                }
            }
        }
    }
    bail!("No occurrence within five years")
}
#[cfg(test)]
mod tests {
    use super::*;
    fn dt(s: &str) -> DateTime<Utc> {
        s.parse().unwrap()
    }
    #[test]
    fn calendar_dst_and_month_end() {
        let s = Schedule::Calendar {
            frequency: "daily".into(),
            time: "02:30".into(),
            timezone: "Europe/Madrid".into(),
            days: vec![],
            day_of_month: None,
        };
        assert_eq!(
            s.next(dt("2026-03-28T03:00:00Z")).unwrap(),
            dt("2026-03-30T00:30:00Z")
        );
        assert_eq!(
            s.next(dt("2026-10-25T00:30:00Z")).unwrap(),
            dt("2026-10-26T01:30:00Z")
        );
        let s = Schedule::Calendar {
            frequency: "monthly".into(),
            time: "09:00".into(),
            timezone: "UTC".into(),
            days: vec![],
            day_of_month: Some(31),
        };
        assert_eq!(
            s.next(dt("2026-04-01T00:00:00Z")).unwrap(),
            dt("2026-05-31T09:00:00Z")
        );
    }
    #[test]
    fn cron_and_validation() {
        assert_eq!(
            cron_next("0 9 * * 1-5", "Europe/Madrid", dt("2026-11-06T09:00:00Z")).unwrap(),
            dt("2026-11-09T08:00:00Z")
        );
        assert_eq!(
            cron_next("*/15 * * * *", "UTC", dt("2026-01-01T00:01:00Z")).unwrap(),
            dt("2026-01-01T00:15:00Z")
        );
        for expr in ["* * *", "*/0 * * * *", "60 * * * *", "0 0 31 2 *"] {
            assert!(cron_next(expr, "UTC", Utc::now()).is_err());
        }
        assert!(cron_next("0 9 * * *", "invalid", Utc::now()).is_err());
    }
}
