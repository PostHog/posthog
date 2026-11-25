//! Render an agenda against a host-selected reader, using a fixture without accessing EventKit.
use anyhow::Result;
use chrono::{DateTime, Utc};
use meep_native_stores::{
    Access, Privacy,
    calendar::{Calendar, Event, Store},
};

struct Fixture;
impl Privacy for Fixture {
    fn access(&self) -> Result<Access> {
        Ok(Access::Full)
    }
    fn request(&self) -> Result<bool> {
        anyhow::bail!("The agenda never prompts for access")
    }
}
impl Store for Fixture {
    fn calendars(&self) -> Result<Vec<Calendar>> {
        Ok(vec![Calendar {
            id: "work".into(),
            title: "Work".into(),
            account: "Fixture".into(),
            writable: false,
        }])
    }
    fn events(
        &self,
        _: DateTime<Utc>,
        _: DateTime<Utc>,
        _: Option<&[String]>,
    ) -> Result<Vec<Event>> {
        Ok(Vec::new())
    }
}

fn show(reader: &dyn Store) -> Result<()> {
    anyhow::ensure!(reader.access()? == Access::Full, "Calendar access required");
    for calendar in reader.calendars()? {
        println!("{} ({})", calendar.title, calendar.account);
    }
    Ok(())
}

fn main() -> Result<()> {
    show(&Fixture)
}
