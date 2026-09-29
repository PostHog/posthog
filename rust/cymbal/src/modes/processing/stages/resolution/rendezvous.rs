use sha2::{Digest, Sha256};

/// Rendezvous (highest random weight) score of one endpoint for one routing key. Every client pod
/// computes the same score, so a key lands on the same endpoint from every pod.
pub fn rendezvous_score(routing_key: &str, addr_label: &str) -> u64 {
    // SHA-256 (no per-process seed) keeps the key->endpoint mapping identical
    // across every client pod. `addr_label` is the endpoint's pre-formatted
    // address string, so the hashed input matches the historical
    // `SocketAddr::to_string()` bytes exactly — the mapping is stable across a
    // rolling deploy — while the caller avoids re-allocating it per selection.
    let mut hasher = Sha256::new();
    hasher.update(routing_key.as_bytes());
    hasher.update(b"\0");
    hasher.update(addr_label.as_bytes());
    let digest = hasher.finalize();
    u64::from_be_bytes(digest[0..8].try_into().expect("sha256 digest has 8 bytes"))
}

#[cfg(test)]
mod tests {
    use std::net::SocketAddr;

    use super::*;

    fn addr(value: &str) -> SocketAddr {
        value.parse().unwrap()
    }

    #[test]
    fn rendezvous_score_is_deterministic_and_stable() {
        let key = "team:1:symbol:bundle-a";
        // Stable across calls (no per-process seed) and distinct per endpoint.
        assert_eq!(
            rendezvous_score(key, "10.0.0.1:50061"),
            rendezvous_score(key, "10.0.0.1:50061")
        );
        assert_ne!(
            rendezvous_score(key, "10.0.0.1:50061"),
            rendezvous_score(key, "10.0.0.2:50061")
        );
        // Port is part of the label, so two ports on one host differ.
        assert_ne!(
            rendezvous_score(key, "10.0.0.1:50061"),
            rendezvous_score(key, "10.0.0.1:50062")
        );
        // The hashed input is the SocketAddr's Display form, so scoring the
        // label matches scoring `addr.to_string()` byte-for-byte. This pins the
        // key->endpoint mapping so it survives a rolling deploy.
        let socket = addr("10.0.0.1:50061");
        assert_eq!(
            rendezvous_score(key, &socket.to_string()),
            rendezvous_score(key, "10.0.0.1:50061")
        );
    }
}
