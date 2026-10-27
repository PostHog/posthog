use std::net::IpAddr;

/// An inclusive `[start, end]` range. IPv4 ranges widen to `u128` so both families share
/// one representation.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct ParsedCidr {
    pub(crate) start: u128,
    pub(crate) end: u128,
    pub(crate) is_v4: bool,
}

impl ParsedCidr {
    pub(crate) fn single(ip: IpAddr) -> Self {
        match ip {
            IpAddr::V4(v4) => {
                let value = u128::from(u32::from(v4));
                Self {
                    start: value,
                    end: value,
                    is_v4: true,
                }
            }
            IpAddr::V6(v6) => {
                let value = u128::from(v6);
                Self {
                    start: value,
                    end: value,
                    is_v4: false,
                }
            }
        }
    }

    /// IPv4-mapped IPv6 addresses match IPv4 ranges, the same as the bot lookup.
    pub(crate) fn contains(&self, ip: IpAddr) -> bool {
        let value = match normalize(ip) {
            IpAddr::V4(v4) if self.is_v4 => u128::from(u32::from(v4)),
            IpAddr::V6(v6) if !self.is_v4 => u128::from(v6),
            _ => return false,
        };
        self.start <= value && value <= self.end
    }
}

pub(crate) fn parse_cidr(cidr: &str) -> Option<ParsedCidr> {
    let (addr_str, prefix_str) = cidr.split_once('/')?;
    let prefix: u8 = prefix_str.parse().ok()?;
    let addr: IpAddr = addr_str.parse().ok()?;
    match addr {
        IpAddr::V4(v4) => {
            if prefix > 32 {
                return None;
            }
            let base = u32::from(v4);
            let mask = if prefix == 0 {
                0
            } else {
                !0u32 << (32 - prefix)
            };
            let start = base & mask;
            let end = start | !mask;
            Some(ParsedCidr {
                start: u128::from(start),
                end: u128::from(end),
                is_v4: true,
            })
        }
        IpAddr::V6(v6) => {
            if prefix > 128 {
                return None;
            }
            let base = u128::from(v6);
            let mask = if prefix == 0 {
                0
            } else {
                !0u128 << (128 - prefix)
            };
            let start = base & mask;
            let end = start | !mask;
            Some(ParsedCidr {
                start,
                end,
                is_v4: false,
            })
        }
    }
}

/// Collapse IPv4-mapped IPv6 (`::ffff:1.2.3.4`) to IPv4 so reverse proxies
/// that hand us mapped form still hit the v4 ranges.
pub(crate) fn normalize(ip: IpAddr) -> IpAddr {
    match ip {
        IpAddr::V6(v6) => v6
            .to_ipv4_mapped()
            .map(IpAddr::V4)
            .unwrap_or(IpAddr::V6(v6)),
        v4 => v4,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    #[rstest]
    #[case("0.0.0.0/0", 0u32, u32::MAX)]
    #[case("10.0.0.0/8", 10u32 << 24, (10u32 << 24) | 0x00_FF_FF_FF)]
    #[case("192.168.1.0/24", (192u32 << 24) | (168 << 16) | (1 << 8), (192u32 << 24) | (168 << 16) | (1 << 8) | 0xFF)]
    #[case("203.0.113.42/32", (203u32 << 24) | (113 << 8) | 42, (203u32 << 24) | (113 << 8) | 42)]
    fn parse_cidr_v4_boundaries(
        #[case] cidr: &str,
        #[case] expected_start: u32,
        #[case] expected_end: u32,
    ) {
        let p = parse_cidr(cidr).unwrap();
        assert!(p.is_v4);
        assert_eq!(p.start, u128::from(expected_start));
        assert_eq!(p.end, u128::from(expected_end));
    }

    #[rstest]
    #[case("not-an-ip/24")]
    #[case("10.0.0.0/33")]
    #[case("::/129")]
    #[case("missing-prefix")]
    fn parse_cidr_rejects_malformed(#[case] cidr: &str) {
        assert!(parse_cidr(cidr).is_none());
    }
}
