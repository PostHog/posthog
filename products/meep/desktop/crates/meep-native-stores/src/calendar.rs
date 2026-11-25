//! Read calendar occurrences and reminders using EventKit.
use crate::{Access, Privacy};
use anyhow::Result;
use chrono::{DateTime, Utc};
#[cfg(target_os = "macos")]
pub(crate) use eventkit::sonoma as full_access_api;
#[cfg(target_os = "macos")]
use {
    crate::{bundled, decision, text},
    anyhow::Context,
};
#[derive(Clone, Debug, PartialEq)]
pub struct Calendar {
    pub id: String,
    pub title: String,
    /// The account (EventKit source) title, such as "iCloud" or "Google".
    pub account: String,
    pub writable: bool,
}
#[derive(Clone, Debug, PartialEq)]
pub struct Person {
    pub name: Option<String>,
    pub email: Option<String>,
    pub status: &'static str,
}
/// One occurrence, untrimmed: the host can project it into its own output model.
#[derive(Clone, Debug, PartialEq)]
pub struct Event {
    /// Shared by every occurrence of a recurring event.
    pub id: String,
    pub title: String,
    pub start: DateTime<Utc>,
    pub end: DateTime<Utc>,
    pub all_day: bool,
    pub calendar: String,
    pub calendar_id: String,
    pub location: Option<String>,
    pub notes: Option<String>,
    pub url: Option<String>,
    pub status: &'static str,
    pub organizer: Option<Person>,
    pub attendees: Vec<Person>,
    pub recurring: bool,
}
pub trait Store: Privacy {
    fn calendars(&self) -> Result<Vec<Calendar>>;
    /// Occurrences overlapping `[start, end)`, from `calendars` (IDs) or every calendar.
    fn events(
        &self,
        start: DateTime<Utc>,
        end: DateTime<Utc>,
        calendars: Option<&[String]>,
    ) -> Result<Vec<Event>>;
}
/// One reminder, untrimmed: the host can project it into its own output model.
#[derive(Clone, Debug, PartialEq)]
pub struct Reminder {
    pub id: String,
    pub title: String,
    pub notes: Option<String>,
    pub list: String,
    pub list_id: String,
    /// A date-only due date is local midnight, with `due_all_day`.
    pub due: Option<DateTime<Utc>>,
    pub due_all_day: bool,
    pub completed: bool,
    pub completed_at: Option<DateTime<Utc>>,
    /// EventKit's: 0 none, 1–4 high, 5 medium, 6–9 low.
    pub priority: usize,
    pub url: Option<String>,
}
pub trait Reminders: Privacy {
    /// Reminder lists are EventKit calendars of reminders.
    fn lists(&self) -> Result<Vec<Calendar>>;
    /// The completed or the incomplete reminders in `lists` (IDs) or every list.
    fn reminders(&self, lists: Option<&[String]>, completed: bool) -> Result<Vec<Reminder>>;
}

pub struct EventKit;
pub struct EventKitReminders;

#[cfg(target_os = "macos")]
mod eventkit {
    use super::*;
    use objc2::rc::Retained;
    use objc2_event_kit::*;
    use objc2_foundation::{
        NSArray, NSCalendar, NSDate, NSDateComponentUndefined, NSOperatingSystemVersion,
        NSProcessInfo,
    };
    use std::time::Duration;

    fn bundled() -> Result<()> {
        super::bundled("Calendar")
    }
    fn date(at: DateTime<Utc>) -> Retained<NSDate> {
        NSDate::dateWithTimeIntervalSince1970(at.timestamp_millis() as f64 / 1000.)
    }
    fn instant(date: &NSDate) -> DateTime<Utc> {
        let millis = (date.timeIntervalSince1970() * 1000.).round() as i64;
        DateTime::from_timestamp_millis(millis).unwrap_or_default()
    }
    fn person(p: &EKParticipant) -> Person {
        unsafe {
            let url = text(p.URL().absoluteString());
            let email = url.and_then(|u| {
                u.get(..7)
                    .filter(|scheme| scheme.eq_ignore_ascii_case("mailto:"))
                    .map(|_| u[7..].to_owned())
            });
            let status = match p.participantStatus() {
                EKParticipantStatus::Accepted => "accepted",
                EKParticipantStatus::Declined => "declined",
                EKParticipantStatus::Tentative => "tentative",
                EKParticipantStatus::Pending => "pending",
                EKParticipantStatus::Delegated => "delegated",
                EKParticipantStatus::Completed => "completed",
                EKParticipantStatus::InProcess => "inProcess",
                _ => "unknown",
            };
            Person {
                name: text(p.name()),
                email,
                status,
            }
        }
    }
    fn calendar(c: &EKCalendar) -> Calendar {
        unsafe {
            Calendar {
                id: c.calendarIdentifier().to_string(),
                title: c.title().to_string(),
                account: c
                    .source()
                    .map(|s| s.title().to_string())
                    .unwrap_or_default(),
                writable: c.allowsContentModifications(),
            }
        }
    }
    fn event(e: &EKEvent) -> Event {
        unsafe {
            let cal = e.calendar();
            Event {
                id: text(e.eventIdentifier())
                    .unwrap_or_else(|| e.calendarItemIdentifier().to_string()),
                title: e.title().to_string(),
                start: instant(&e.startDate()),
                end: instant(&e.endDate()),
                all_day: e.isAllDay(),
                calendar: cal
                    .as_ref()
                    .map(|c| c.title().to_string())
                    .unwrap_or_default(),
                calendar_id: cal
                    .as_ref()
                    .map(|c| c.calendarIdentifier().to_string())
                    .unwrap_or_default(),
                location: text(e.location()),
                notes: text(e.notes()),
                url: e.URL().and_then(|u| text(u.absoluteString())),
                status: match e.status() {
                    EKEventStatus::Confirmed => "confirmed",
                    EKEventStatus::Tentative => "tentative",
                    EKEventStatus::Canceled => "canceled",
                    _ => "none",
                },
                organizer: e.organizer().map(|p| person(&p)),
                attendees: e
                    .attendees()
                    .map(|a| a.iter().map(|p| person(&p)).collect())
                    .unwrap_or_default(),
                recurring: e.hasRecurrenceRules(),
            }
        }
    }

    pub(crate) fn sonoma() -> bool {
        NSProcessInfo::processInfo().isOperatingSystemAtLeastVersion(NSOperatingSystemVersion {
            majorVersion: 14,
            minorVersion: 0,
            patchVersion: 0,
        })
    }
    fn access(entity: EKEntityType) -> Access {
        // macOS 13's "authorized" has the same value as macOS 14's full access.
        match unsafe { EKEventStore::authorizationStatusForEntityType(entity) } {
            EKAuthorizationStatus::FullAccess => Access::Full,
            EKAuthorizationStatus::WriteOnly => Access::WriteOnly,
            EKAuthorizationStatus::Denied => Access::Denied,
            EKAuthorizationStatus::Restricted => Access::Restricted,
            _ => Access::NotDetermined,
        }
    }
    fn request(what: &str, entity: EKEntityType) -> Result<bool> {
        let store = unsafe { EKEventStore::new() };
        // EventKit copies the block; `store` stays alive until the decision.
        let granted = decision(what, |callback| unsafe {
            let callback = callback as *const _ as *mut _;
            match (sonoma(), entity) {
                (true, EKEntityType::Reminder) => {
                    store.requestFullAccessToRemindersWithCompletion(callback)
                }
                (true, _) => store.requestFullAccessToEventsWithCompletion(callback),
                (false, _) =>
                {
                    #[allow(deprecated)]
                    store.requestAccessToEntityType_completion(entity, callback)
                }
            }
        });
        drop(store);
        granted
    }
    /// The chosen calendars (or lists) of `entity`, or every one for `None`.
    fn chosen(
        store: &EKEventStore,
        entity: EKEntityType,
        ids: Option<&[String]>,
        noun: &str,
    ) -> Result<Option<Retained<NSArray<EKCalendar>>>> {
        let Some(ids) = ids else {
            return Ok(None);
        };
        let all = unsafe { store.calendarsForEntityType(entity) };
        let chosen = ids
            .iter()
            .map(|id| {
                all.iter()
                    .find(|c| unsafe { c.calendarIdentifier() }.to_string() == *id)
                    .with_context(|| format!("Unknown {noun}: {id}"))
            })
            .collect::<Result<Vec<_>>>()?;
        Ok(Some(NSArray::from_retained_slice(&chosen)))
    }

    impl Privacy for EventKit {
        fn access(&self) -> Result<Access> {
            bundled()?;
            Ok(access(EKEntityType::Event))
        }
        fn request(&self) -> Result<bool> {
            bundled()?;
            request("Calendar", EKEntityType::Event)
        }
    }
    impl Store for EventKit {
        fn calendars(&self) -> Result<Vec<Calendar>> {
            crate::require_read(self, "Calendar")?;
            Ok(objc2::rc::autoreleasepool(|_| unsafe {
                let store = EKEventStore::new();
                store
                    .calendarsForEntityType(EKEntityType::Event)
                    .iter()
                    .map(|c| calendar(&c))
                    .collect()
            }))
        }
        fn events(
            &self,
            start: DateTime<Utc>,
            end: DateTime<Utc>,
            ids: Option<&[String]>,
        ) -> Result<Vec<Event>> {
            anyhow::ensure!(start < end, "The event range must end after it starts");
            crate::require_read(self, "Calendar")?;
            objc2::rc::autoreleasepool(|_| unsafe {
                let store = EKEventStore::new();
                let selected = chosen(&store, EKEntityType::Event, ids, "calendar")?;
                let predicate = store.predicateForEventsWithStartDate_endDate_calendars(
                    &date(start),
                    &date(end),
                    selected.as_deref(),
                );
                Ok(store
                    .eventsMatchingPredicate(&predicate)
                    .iter()
                    .map(|e| event(&e))
                    .collect())
            })
        }
    }

    fn reminder(r: &EKReminder) -> Reminder {
        unsafe {
            let list = r.calendar();
            let due = r.dueDateComponents();
            Reminder {
                id: r.calendarItemIdentifier().to_string(),
                title: r.title().to_string(),
                notes: text(r.notes()),
                list: list
                    .as_ref()
                    .map(|c| c.title().to_string())
                    .unwrap_or_default(),
                list_id: list
                    .as_ref()
                    .map(|c| c.calendarIdentifier().to_string())
                    .unwrap_or_default(),
                // Components carry their own calendar and zone when set.
                due: due.as_ref().and_then(|d| {
                    d.calendar()
                        .unwrap_or_else(NSCalendar::currentCalendar)
                        .dateFromComponents(d)
                        .map(|date| instant(&date))
                }),
                due_all_day: due
                    .as_ref()
                    .is_some_and(|d| d.hour() == NSDateComponentUndefined),
                completed: r.isCompleted(),
                completed_at: r.completionDate().map(|d| instant(&d)),
                priority: r.priority(),
                url: r.URL().and_then(|u| text(u.absoluteString())),
            }
        }
    }

    impl Privacy for EventKitReminders {
        fn access(&self) -> Result<Access> {
            super::bundled("Reminders")?;
            Ok(access(EKEntityType::Reminder))
        }
        fn request(&self) -> Result<bool> {
            super::bundled("Reminders")?;
            request("Reminders", EKEntityType::Reminder)
        }
    }
    impl Reminders for EventKitReminders {
        fn lists(&self) -> Result<Vec<Calendar>> {
            crate::require_read(self, "Reminders")?;
            Ok(objc2::rc::autoreleasepool(|_| unsafe {
                EKEventStore::new()
                    .calendarsForEntityType(EKEntityType::Reminder)
                    .iter()
                    .map(|c| calendar(&c))
                    .collect()
            }))
        }
        /// EventKit only fetches reminders asynchronously. Call this on
        /// the blocking pool, which waits here for the completion block.
        fn reminders(&self, ids: Option<&[String]>, completed: bool) -> Result<Vec<Reminder>> {
            crate::require_read(self, "Reminders")?;
            let (tx, rx) = std::sync::mpsc::channel();
            let tx = std::sync::Mutex::new(Some(tx));
            let store = unsafe { EKEventStore::new() };
            let fetch = objc2::rc::autoreleasepool(|_| unsafe {
                let lists = chosen(&store, EKEntityType::Reminder, ids, "list")?;
                let predicate = if completed {
                    store.predicateForCompletedRemindersWithCompletionDateStarting_ending_calendars(
                        None,
                        None,
                        lists.as_deref(),
                    )
                } else {
                    store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars(
                        None,
                        None,
                        lists.as_deref(),
                    )
                };
                // Mapped inside the block, while EventKit's objects are valid.
                let callback = block2::RcBlock::new(move |found: *mut NSArray<EKReminder>| {
                    let mapped = objc2::rc::autoreleasepool(|_| {
                        found
                            .as_ref()
                            .map(|found| found.iter().map(|r| reminder(&r)).collect::<Vec<_>>())
                            .unwrap_or_default()
                    });
                    if let Some(tx) = tx.lock().unwrap().take() {
                        let _ = tx.send(mapped);
                    }
                });
                anyhow::Ok(store.fetchRemindersMatchingPredicate_completion(&predicate, &callback))
            })?;
            let found = rx.recv_timeout(Duration::from_secs(60));
            if found.is_err() {
                unsafe { store.cancelFetchRequest(&fetch) };
            }
            drop(store);
            found.context("Reading reminders timed out")
        }
    }
}

#[cfg(not(target_os = "macos"))]
use crate::UNAVAILABLE;

#[cfg(not(target_os = "macos"))]
macro_rules! unavailable_store {
    ($store:ty) => {
        impl Privacy for $store {
            fn access(&self) -> Result<Access> {
                anyhow::bail!("{UNAVAILABLE}");
            }
            fn request(&self) -> Result<bool> {
                anyhow::bail!("{UNAVAILABLE}");
            }
        }
    };
}

#[cfg(not(target_os = "macos"))]
unavailable_store!(EventKit);
#[cfg(not(target_os = "macos"))]
unavailable_store!(EventKitReminders);

#[cfg(not(target_os = "macos"))]
impl Store for EventKit {
    fn calendars(&self) -> Result<Vec<Calendar>> {
        anyhow::bail!("{UNAVAILABLE}");
    }
    fn events(
        &self,
        _: DateTime<Utc>,
        _: DateTime<Utc>,
        _: Option<&[String]>,
    ) -> Result<Vec<Event>> {
        anyhow::bail!("{UNAVAILABLE}");
    }
}

#[cfg(not(target_os = "macos"))]
impl Reminders for EventKitReminders {
    fn lists(&self) -> Result<Vec<Calendar>> {
        anyhow::bail!("{UNAVAILABLE}");
    }
    fn reminders(&self, _: Option<&[String]>, _: bool) -> Result<Vec<Reminder>> {
        anyhow::bail!("{UNAVAILABLE}");
    }
}
