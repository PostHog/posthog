use std::io::{self, Write};

use tracing_subscriber::fmt::MakeWriter;

/// prepends a custom tag " log_service_name=VALUE " to each stdout log line
/// where VALUE is set to the app's config.otel_service_name. This allows us
/// to override the default production behavior from deployed services that
/// share the capture-rs codebase.
pub struct ServiceNameWriter<W> {
    inner: W,
    tag_bytes: Vec<u8>,
    at_line_start: bool,
}

impl<W: Write> Write for ServiceNameWriter<W> {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        let mut remaining = buf;

        while !remaining.is_empty() {
            if self.at_line_start {
                // Pre-formatted tag bytes, no allocation
                self.inner.write_all(&self.tag_bytes)?;
                self.at_line_start = false;
            }

            // Find the next newline in the remaining buffer so
            // we can prepend the custom tag to each line
            if let Some(newline_pos) = remaining.iter().position(|&b| b == b'\n') {
                // Write up to and including the newline
                self.inner.write_all(&remaining[..=newline_pos])?;
                self.at_line_start = true;
                remaining = &remaining[newline_pos + 1..];
            } else {
                // No newline in this chunk, write everything
                self.inner.write_all(remaining)?;
                break;
            }
        }

        Ok(buf.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        self.inner.flush()
    }
}

pub struct ServiceNameMakeWriter {
    service_name: String,
}

impl ServiceNameMakeWriter {
    pub fn new(service_name: String) -> Self {
        Self { service_name }
    }
}

impl<'a> MakeWriter<'a> for ServiceNameMakeWriter {
    type Writer = ServiceNameWriter<io::Stdout>;

    fn make_writer(&'a self) -> Self::Writer {
        // Pre-format the tag bytes once to avoid allocation on every line
        let tag_bytes = format!(" log_service_name={} ", self.service_name).into_bytes();
        ServiceNameWriter {
            inner: io::stdout(),
            tag_bytes,
            at_line_start: true,
        }
    }
}
