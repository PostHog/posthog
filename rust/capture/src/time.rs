pub trait TimeSource {
    // Return an ISO timestamp
    fn current_time(&self) -> String;
}

#[derive(Clone)]
pub struct SystemTime {}

impl TimeSource for SystemTime {
    fn current_time(&self) -> String {
        let time = time::OffsetDateTime::now_utc();

        time.format(&time::format_description::well_known::Rfc3339)
            .expect("failed to format timestamp")
    }
}
