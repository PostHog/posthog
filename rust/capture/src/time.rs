use chrono::{DateTime, Utc};

pub trait TimeSource {
    // Return a UTC timestamp
    fn current_time(&self) -> DateTime<Utc>;
}

#[derive(Clone)]
pub struct SystemTime {}

impl TimeSource for SystemTime {
    fn current_time(&self) -> DateTime<Utc> {
        Utc::now()
    }
}
