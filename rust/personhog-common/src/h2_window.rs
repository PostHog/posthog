use std::fmt;
use std::str::FromStr;

use tonic::transport::server::Server;
use tonic::transport::Endpoint;

pub const MAX_WINDOW_BYTES: u32 = (1 << 31) - 1;

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct WindowSize(Option<u32>);

impl WindowSize {
    pub const DEFAULT: WindowSize = WindowSize(None);

    pub fn bytes(bytes: u32) -> Result<Self, WindowSizeError> {
        if bytes > MAX_WINDOW_BYTES {
            return Err(WindowSizeError::TooLarge(bytes));
        }
        Ok(Self(if bytes == 0 { None } else { Some(bytes) }))
    }

    pub fn get(self) -> Option<u32> {
        self.0
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WindowSizeError {
    NotANumber(String),
    TooLarge(u32),
}

impl fmt::Display for WindowSizeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            WindowSizeError::NotANumber(raw) => {
                write!(f, "window size must be a byte count, got {raw:?}")
            }
            WindowSizeError::TooLarge(bytes) => write!(
                f,
                "window size {bytes} exceeds the HTTP/2 maximum of {MAX_WINDOW_BYTES} bytes"
            ),
        }
    }
}

impl std::error::Error for WindowSizeError {}

impl FromStr for WindowSize {
    type Err = WindowSizeError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let bytes: u32 = s
            .trim()
            .parse()
            .map_err(|_| WindowSizeError::NotANumber(s.to_string()))?;
        Self::bytes(bytes)
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Http2Windows {
    pub stream: WindowSize,
    pub connection: WindowSize,
}

impl Http2Windows {
    pub fn new(stream: WindowSize, connection: WindowSize) -> Self {
        Self { stream, connection }
    }

    pub fn is_default(self) -> bool {
        self == Self::default()
    }

    pub fn apply_to_server<L>(self, server: Server<L>) -> Server<L> {
        server
            .initial_stream_window_size(self.stream.get())
            .initial_connection_window_size(self.connection.get())
    }

    pub fn apply_to_endpoint(self, endpoint: Endpoint) -> Endpoint {
        endpoint
            .initial_stream_window_size(self.stream.get())
            .initial_connection_window_size(self.connection.get())
    }
}

#[cfg(test)]
mod tests {
    use rstest::rstest;

    use super::*;

    #[rstest]
    #[case::unset("0", Ok(None))]
    #[case::four_mib("4194304", Ok(Some(4 << 20)))]
    #[case::padded(" 65535 ", Ok(Some(65535)))]
    #[case::max("2147483647", Ok(Some(MAX_WINDOW_BYTES)))]
    #[case::over_max("2147483648", Err(WindowSizeError::TooLarge(1 << 31)))]
    #[case::negative("-1", Err(WindowSizeError::NotANumber("-1".to_string())))]
    #[case::unit_suffix("4MiB", Err(WindowSizeError::NotANumber("4MiB".to_string())))]
    fn window_size_parses_bytes_and_refuses_what_h2_would(
        #[case] raw: &str,
        #[case] expected: Result<Option<u32>, WindowSizeError>,
    ) {
        assert_eq!(raw.parse::<WindowSize>().map(WindowSize::get), expected);
    }
}
