#![doc = include_str!("../README.md")]
#![deny(missing_docs)]

pub mod api;
#[cfg(feature = "chat")]
pub mod chat;
#[cfg(feature = "mcp")]
pub mod mcp;
#[cfg(feature = "oauth")]
pub mod oauth;
#[cfg(feature = "signals")]
pub mod signals;
#[cfg(feature = "tasks")]
pub mod tasks;
#[cfg(feature = "workflows")]
pub mod workflows;

// Native clients may reach local fixture servers over HTTP.
fn is_https_or_loopback(url: &url::Url) -> bool {
    url.scheme() == "https"
        || (url.scheme() == "http"
            && match url.host() {
                Some(url::Host::Ipv4(ip)) => ip.is_loopback(),
                Some(url::Host::Ipv6(ip)) => ip.is_loopback(),
                Some(url::Host::Domain("localhost")) => true,
                _ => false,
            })
}
