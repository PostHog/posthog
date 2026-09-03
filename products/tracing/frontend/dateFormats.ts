// Tracing shows timestamps the way Logs does: an ISO-ordered date and a 24-hour clock. A
// month-first date is ambiguous outside the US.
export const TRACING_DATE_FORMAT = 'YYYY-MM-DD'
export const TRACING_TIME_FORMAT = 'HH:mm:ss.SSS'

// Charts and range pills drop the milliseconds. A bucket edge is never sub-second.
export const TRACING_DATE_TIME_FORMAT = 'YYYY-MM-DD HH:mm:ss'

// Every chart, axis, and timestamp in the product reads in UTC, so a span lines up with the
// sparkline above it. TZLabel converts to the reader's own timezone on hover.
export const TRACING_DISPLAY_TIMEZONE = 'UTC'
