use std::error::Error as StdError;
use std::net::{IpAddr, SocketAddr, ToSocketAddrs};
use std::{fmt, io};

use futures::FutureExt;
use reqwest::dns::{Addrs, Name, Resolve, Resolving};
use tokio::task::spawn_blocking;

pub struct NoPublicIPv4Error;

impl std::error::Error for NoPublicIPv4Error {}
impl fmt::Display for NoPublicIPv4Error {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "No public IPv4 found for specified host")
    }
}
impl fmt::Debug for NoPublicIPv4Error {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "No public IPv4 found for specified host")
    }
}

/// Internal reqwest type, copied here as part of Resolving
pub(crate) type BoxError = Box<dyn StdError + Send + Sync>;

/// Returns [`true`] if the IP appears to be a globally reachable IPv4.
///
/// Trimmed down version of the unstable IpAddr::is_global, move to it when it's stable.
pub fn is_global_ip(ip: &IpAddr) -> bool {
    match ip {
        IpAddr::V4(ip) => {
            !(ip.octets()[0] == 0 // "This network"
            || ip.is_private()
            || ip.is_loopback()
            || ip.is_link_local()
            || ip.is_broadcast())
        }
        IpAddr::V6(_) => false, // Our network does not currently support ipv6, let's ignore for now
    }
}

fn is_global_ipv4(addr: &SocketAddr) -> bool {
    is_global_ip(&addr.ip())
}

/// DNS resolver using the stdlib resolver, but filtering results to only pass public IPv4 results.
///
/// Private and broadcast addresses are filtered out, so are IPv6 results for now (as our infra
/// does not currently support IPv6 routing anyway).
/// This is adapted from the GaiResolver in hyper and reqwest.
pub struct PublicIPv4Resolver {}

impl Resolve for PublicIPv4Resolver {
    fn resolve(&self, name: Name) -> Resolving {
        // Closure to call the system's resolver (blocking call) through the ToSocketAddrs trait.
        let resolve_host = move || (name.as_str(), 0).to_socket_addrs();

        // Execute the blocking call in a separate worker thread then process its result asynchronously.
        // spawn_blocking returns a JoinHandle that implements Future<Result<(closure result), JoinError>>.
        let future_result = spawn_blocking(resolve_host).map(|result| match result {
            Ok(Ok(all_addrs)) => {
                // Resolution succeeded, filter the results
                let filtered_addr: Vec<SocketAddr> = all_addrs.filter(is_global_ipv4).collect();
                if filtered_addr.is_empty() {
                    // No public IPs found, error out with PermissionDenied
                    let err: BoxError = Box::new(NoPublicIPv4Error);
                    Err(err)
                } else {
                    // Pass remaining IPs in a boxed iterator for request to use.
                    let addrs: Addrs = Box::new(filtered_addr.into_iter());
                    Ok(addrs)
                }
            }
            Ok(Err(err)) => {
                // Resolution failed, pass error through in a Box
                let err: BoxError = Box::new(err);
                Err(err)
            }
            Err(join_err) => {
                // The tokio task failed, pass as io::Error in a Box
                let err: BoxError = Box::new(io::Error::from(join_err));
                Err(err)
            }
        });

        // Box the Future to satisfy the Resolving interface.
        Box::pin(future_result)
    }
}

/// DNS resolver for the AWS Smithy SDK, filtering to public IPv4 only.
///
/// Same logic as [`PublicIPv4Resolver`] (which targets reqwest), but implements
/// [`aws_smithy_runtime_api::client::dns::ResolveDns`] for use with the AWS SDK S3 client.
/// Gated behind the `smithy` feature to avoid pulling AWS SDK deps into unrelated consumers.
#[cfg(feature = "smithy")]
#[derive(Debug, Clone)]
pub struct PublicIPv4SmithyResolver;

#[cfg(feature = "smithy")]
impl aws_smithy_runtime_api::client::dns::ResolveDns for PublicIPv4SmithyResolver {
    fn resolve_dns<'a>(
        &'a self,
        name: &'a str,
    ) -> aws_smithy_runtime_api::client::dns::DnsFuture<'a> {
        use aws_smithy_runtime_api::client::dns::{DnsFuture, ResolveDnsError};

        let name = name.to_string();
        DnsFuture::new(async move {
            let resolve_host =
                move || std::net::ToSocketAddrs::to_socket_addrs(&(name.as_str(), 0));

            let result = tokio::task::spawn_blocking(resolve_host)
                .await
                .map_err(|e| ResolveDnsError::new(io::Error::from(e)))?;

            let all_addrs = result.map_err(ResolveDnsError::new)?;

            let filtered: Vec<std::net::IpAddr> =
                all_addrs.filter(is_global_ipv4).map(|sa| sa.ip()).collect();

            if filtered.is_empty() {
                Err(ResolveDnsError::new(NoPublicIPv4Error))
            } else {
                Ok(filtered)
            }
        })
    }
}

#[cfg(test)]
mod tests {
    use crate::{NoPublicIPv4Error, PublicIPv4Resolver};
    use reqwest::dns::{Name, Resolve};
    use std::str::FromStr;

    #[tokio::test]
    async fn it_resolves_google_com() {
        let resolver: PublicIPv4Resolver = PublicIPv4Resolver {};
        let addrs = resolver
            .resolve(Name::from_str("google.com").unwrap())
            .await
            .expect("lookup has failed");
        assert!(addrs.count() > 0, "empty address list")
    }

    #[tokio::test]
    async fn it_denies_ipv6_google_com() {
        let resolver: PublicIPv4Resolver = PublicIPv4Resolver {};
        match resolver
            .resolve(Name::from_str("ipv6.google.com").unwrap())
            .await
        {
            Ok(_) => panic!("should have failed"),
            Err(err) => assert!(err.is::<NoPublicIPv4Error>()),
        }
    }

    #[tokio::test]
    async fn it_denies_localhost() {
        let resolver: PublicIPv4Resolver = PublicIPv4Resolver {};
        match resolver.resolve(Name::from_str("localhost").unwrap()).await {
            Ok(_) => panic!("should have failed"),
            Err(err) => assert!(err.is::<NoPublicIPv4Error>()),
        }
    }

    #[tokio::test]
    async fn it_bubbles_up_resolution_error() {
        let resolver: PublicIPv4Resolver = PublicIPv4Resolver {};
        match resolver
            .resolve(Name::from_str("invalid.domain.unknown").unwrap())
            .await
        {
            Ok(_) => panic!("should have failed"),
            Err(err) => {
                assert!(!err.is::<NoPublicIPv4Error>());
                assert!(err
                    .to_string()
                    .contains("failed to lookup address information"))
            }
        }
    }
}

#[cfg(all(test, feature = "smithy"))]
mod smithy_tests {
    use crate::PublicIPv4SmithyResolver;
    use aws_smithy_runtime_api::client::dns::ResolveDns;

    #[tokio::test]
    async fn smithy_resolves_google_com() {
        let resolver = PublicIPv4SmithyResolver;
        let addrs = resolver
            .resolve_dns("google.com")
            .await
            .expect("lookup has failed");
        assert!(!addrs.is_empty(), "empty address list");
    }

    #[tokio::test]
    async fn smithy_denies_localhost() {
        let resolver = PublicIPv4SmithyResolver;
        let err = resolver
            .resolve_dns("localhost")
            .await
            .expect_err("should have rejected localhost");
        assert!(
            err.to_string().contains("DNS") || format!("{:?}", err).contains("NoPublicIPv4Error"),
            "unexpected error: {err:?}"
        );
    }

    #[tokio::test]
    async fn smithy_bubbles_up_resolution_error() {
        let resolver = PublicIPv4SmithyResolver;
        let err = resolver
            .resolve_dns("invalid.domain.unknown")
            .await
            .expect_err("should have failed");
        let debug = format!("{:?}", err);
        assert!(
            debug.contains("lookup address") || debug.contains("DNS"),
            "unexpected error: {debug}"
        );
    }
}
