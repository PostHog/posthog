//! Test support for the out-of-band domain guards. Enabled by the `test-util` feature, so it is
//! built only by the crates that test a guard.

use std::sync::{Arc, Mutex};

use tracing_subscriber::fmt::MakeWriter;

#[derive(Clone)]
pub struct Sink(Arc<Mutex<Vec<u8>>>);

impl std::io::Write for Sink {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        self.0.lock().expect("sink lock").extend_from_slice(buf);
        Ok(buf.len())
    }

    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

impl<'a> MakeWriter<'a> for Sink {
    type Writer = Sink;

    fn make_writer(&'a self) -> Self::Writer {
        self.clone()
    }
}

/// Run `work` as cloud with the tracing output captured, and return that output.
///
/// `note_oob_domain` logs on cloud only, so a guard test has to look like cloud. The override is
/// set for the rest of the process rather than restored, because the tests in a binary run in
/// parallel and a restore would race one that is still inside `work`.
pub fn capture_oob_logs(work: impl FnOnce()) -> String {
    crate::oob_domains::force_cloud();
    // Each capture starts clean, so one case cannot dedupe away the next one's line.
    crate::oob_domains::reset_dedupe();

    let sink = Sink(Arc::new(Mutex::new(Vec::new())));
    let subscriber = tracing_subscriber::fmt()
        .with_writer(sink.clone())
        .with_ansi(false)
        .finish();
    tracing::subscriber::with_default(subscriber, work);
    let captured = sink.0.lock().expect("sink lock").clone();
    String::from_utf8(captured).expect("log output is utf-8")
}
