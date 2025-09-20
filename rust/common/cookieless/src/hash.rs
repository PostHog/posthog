use common_types::TeamId;
use siphasher::sip128::{Hasher128, SipHasher24};
use std::hash::Hasher;
use thiserror::Error;

#[derive(Debug, Error, PartialEq)]
pub enum HashError {
    #[error("Salt must be exactly 16 bytes, but got {0} bytes.")]
    InvalidSaltSize(usize),
}

/// Computes a hash using SipHash-2-4 with the given parameters
///
/// # Arguments
///
/// * `salt` - A 16-byte salt
/// * `team_id` - The team ID
/// * `ip` - The IP address
/// * `root_domain` - The root domain
/// * `user_agent` - The user agent
/// * `n` - A counter value
/// * `hash_extra` - Additional data to include in the hash
///
/// # Returns
///
/// A 16-byte hash value or an error if the salt is not 16 bytes
pub fn do_hash(
    salt: &[u8],
    team_id: TeamId,
    ip: &str,
    root_domain: &str,
    user_agent: &str,
    n: u64,
    hash_extra: &str,
) -> Result<Vec<u8>, HashError> {
    // Ensure the salt is 16 bytes, just like the TS function requires
    if salt.len() != 16 {
        return Err(HashError::InvalidSaltSize(salt.len()));
    }

    // Extract the two 64-bit keys from the salt
    let key0 = u64::from_le_bytes(salt[0..8].try_into().unwrap());
    let key1 = u64::from_le_bytes(salt[8..16].try_into().unwrap());

    // Truncate hash_extra to 100 chars (same as in the TS code: `hashExtra.slice(0, 100)`)
    let truncated_hash_extra: String = hash_extra.chars().take(100).collect();

    // Build the input string
    let input_str = build_input_str(
        team_id,
        ip,
        root_domain,
        user_agent,
        n,
        &truncated_hash_extra,
    );

    // Compute SipHash 2-4
    let mut hasher = SipHasher24::new_with_keys(key0, key1);
    hasher.write(input_str.as_bytes());
    let hash_value = hasher.finish128();

    // Rearrange the bytes to match the TS implementation
    let h1 = hash_value.h1.to_le_bytes().to_vec();
    let h2 = hash_value.h2.to_le_bytes().to_vec();
    let mut rearranged = Vec::with_capacity(16);
    rearranged.extend_from_slice(&h2[4..8]);
    rearranged.extend_from_slice(&h2[0..4]);
    rearranged.extend_from_slice(&h1[4..8]);
    rearranged.extend_from_slice(&h1[0..4]);

    Ok(rearranged)
}

/// Builds the input string for the hash function
fn build_input_str(
    team_id: TeamId,
    ip: &str,
    root_domain: &str,
    user_agent: &str,
    n: u64,
    truncated_hash_extra: &str,
) -> String {
    let mut input_str = String::with_capacity(
        20 + // Maximum team_id.len() for an u64
        ip.len() +
        root_domain.len() +
        user_agent.len() +
        20 + // Maximum n.len() for an u64
        truncated_hash_extra.len() +
        5, // 5 dashes/hyphens
    );

    // Use itoa for efficient integer formatting without allocations
    let mut team_id_buffer = itoa::Buffer::new();
    let mut n_buffer = itoa::Buffer::new();
    input_str.push_str(team_id_buffer.format(team_id));
    input_str.push('-');
    input_str.push_str(ip);
    input_str.push('-');
    input_str.push_str(root_domain);
    input_str.push('-');
    input_str.push_str(user_agent);
    input_str.push('-');
    input_str.push_str(n_buffer.format(n));
    input_str.push('-');
    input_str.push_str(truncated_hash_extra);

    input_str
}

#[cfg(test)]
mod tests {
    use super::*;
    use base64::{self, engine::general_purpose, Engine};
    use serde::Deserialize;
    use std::fs;
    use std::path::Path;

    // Match the JSON structure.
    #[derive(Deserialize)]
    struct TestCase {
        salt: String,
        team_id: TeamId,
        ip: String,
        root_domain: String,
        user_agent: String,
        n: u64,
        hash_extra: String,
        expected: String,
    }

    #[derive(Deserialize)]
    struct TestData {
        #[serde(rename = "//", default)]
        _comment: String,
        test_cases: Vec<TestCase>,
    }

    #[test]
    fn test_do_hash_from_json() {
        let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("src/test_cases.json");
        let data_str = fs::read_to_string(&path)
            .unwrap_or_else(|e| panic!("Failed to read file at {}: {}", path.display(), e));

        let test_data: TestData =
            serde_json::from_str(&data_str).expect("Failed to parse JSON test data");

        for (i, tc) in test_data.test_cases.iter().enumerate() {
            let salt_bytes = general_purpose::STANDARD
                .decode(&tc.salt)
                .unwrap_or_else(|_| panic!("Test case {i}: invalid base64 salt"));

            let expected_bytes = general_purpose::STANDARD
                .decode(&tc.expected)
                .unwrap_or_else(|_| panic!("Test case {i}: invalid base64 expected hash"));

            let actual = do_hash(
                &salt_bytes,
                tc.team_id,
                &tc.ip,
                &tc.root_domain,
                &tc.user_agent,
                tc.n,
                &tc.hash_extra,
            );

            assert_eq!(
                actual,
                Ok(expected_bytes.clone()),
                "Test case {i} failed. Expected {expected_bytes:?}, got {actual:?}"
            );
        }
    }

    #[test]
    fn test_invalid_salt_size() {
        // Provide a salt that is too short (8 bytes instead of 16)
        let short_salt = [0u8; 8];

        let result = do_hash(
            &short_salt,
            42,
            "127.0.0.1",
            "example.com",
            "Mozilla/5.0",
            0,
            "extra",
        );

        assert_eq!(result, Err(HashError::InvalidSaltSize(8)));
    }
}
