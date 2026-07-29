use std::error::Error as StdError;
use std::net::{IpAddr, Ipv4Addr, SocketAddr, ToSocketAddrs};
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
/// Covers every range the still-unstable `Ipv4Addr::is_global` rejects, and is deliberately
/// *stricter*: we also reject multicast, which std considers globally reachable. So don't
/// swap in `Ipv4Addr::is_global` when it stabilizes without re-adding that check - this
/// gates outbound fetches, and loosening it widens our SSRF surface.
///
/// IPv6 is rejected wholesale for now, as our infra does not route it.
pub fn is_global_ip(ip: &IpAddr) -> bool {
    match ip {
        IpAddr::V4(ip) => is_global_ipv4_addr(ip),
        IpAddr::V6(_) => false, // Our network does not currently support ipv6, let's ignore for now
    }
}

fn is_global_ipv4_addr(ip: &Ipv4Addr) -> bool {
    let [a, b, c, d] = ip.octets();

    // Shared address space (100.64.0.0/10) — carrier-grade NAT, routinely internal.
    let is_shared = a == 100 && (b & 0b1100_0000) == 0b0100_0000;
    // IETF protocol assignments (192.0.0.0/24); only .9 and .10 are globally reachable.
    let is_ietf_protocol = a == 192 && b == 0 && c == 0 && d != 9 && d != 10;
    // Benchmarking range (198.18.0.0/15).
    let is_benchmarking = a == 198 && (b & 0xfe) == 18;
    // Reserved for future use (240.0.0.0/4); also covers the 255.255.255.255 broadcast address.
    let is_reserved = (a & 0xf0) == 0xf0;

    !(a == 0 // "This network" (0.0.0.0/8)
        || ip.is_private() // 10/8, 172.16/12, 192.168/16
        || is_shared
        || ip.is_loopback() // 127/8
        || ip.is_link_local() // 169.254/16, includes the cloud metadata IP
        || is_ietf_protocol
        || ip.is_documentation() // 192.0.2/24, 198.51.100/24, 203.0.113/24
        || is_benchmarking
        || ip.is_multicast() // 224.0.0.0/4
        || is_reserved)
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
    use crate::{is_global_ip, NoPublicIPv4Error, PublicIPv4Resolver};
    use reqwest::dns::{Name, Resolve};
    use std::net::IpAddr;
    use std::str::FromStr;

    fn is_global(ip: &str) -> bool {
        is_global_ip(&ip.parse::<IpAddr>().unwrap())
    }

    #[test]
    fn is_global_ip_allows_public_ipv4() {
        for ip in [
            "8.8.8.8",
            "1.1.1.1",
            "93.184.216.34", // example.com
            // The addresses immediately outside each blocked range. These pin the masks down:
            // a check that was one bit too wide would swallow these and go unnoticed.
            "100.63.255.255",  // just below shared 100.64.0.0/10
            "100.128.0.0",     // just above it
            "192.0.0.9",       // carved out of 192.0.0.0/24 as globally reachable
            "192.0.0.10",      // ditto
            "192.0.1.1",       // just above 192.0.0.0/24
            "198.17.255.255",  // just below benchmarking 198.18.0.0/15
            "198.20.0.0",      // just above it
            "223.255.255.255", // just below multicast 224.0.0.0/4
        ] {
            assert!(is_global(ip), "expected {ip} to be treated as public");
        }
    }

    #[test]
    fn is_global_ip_rejects_internal_ranges() {
        for ip in [
            "127.0.0.1",   // loopback / localhost
            "0.0.0.0",     // unspecified / "this network"
            "10.0.0.1",    // private
            "172.16.5.4",  // private
            "192.168.1.1", // private
            "100.64.0.1",  // shared / carrier-grade NAT
            "100.127.255.255",
            "169.254.0.1",     // link-local
            "169.254.169.254", // the cloud metadata endpoint
            "192.0.0.1",       // IETF protocol assignments
            "192.0.0.255",
            "192.0.2.1",    // documentation
            "198.51.100.1", // documentation
            "203.0.113.1",  // documentation
            "198.18.0.1",   // benchmarking
            "198.19.255.255",
            "224.0.0.1",       // multicast
            "239.255.255.255", // top of multicast
            "240.0.0.1",       // reserved
            "255.255.255.255", // broadcast
        ] {
            assert!(!is_global(ip), "expected {ip} to be rejected");
        }
    }

    #[test]
    fn is_global_ip_rejects_all_ipv6() {
        // We do not route IPv6, so nothing resolves to a fetchable address, including
        // the IPv6 loopback which must never be reachable.
        assert!(!is_global("::1"));
        assert!(!is_global("2606:4700:4700::1111"));
    }

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
