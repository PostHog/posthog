use siphasher::sip128::{Hasher128, SipHasher24};
use std::hash::Hasher;

pub fn do_hash(
    salt: &[u8],
    team_id: u64,
    ip: &str,
    root_domain: &str,
    user_agent: &str,
    n: u64,
    hash_extra: &str,
) -> Vec<u8> {
    // Ensure the salt is 16 bytes, just like the TS function requires
    if salt.len() != 16 {
        panic!("Salt must be 16 bytes");
    }

    // Extract the two 64-bit keys from the salt
    let key0 = u64::from_le_bytes(salt[0..8].try_into().unwrap());
    let key1 = u64::from_le_bytes(salt[8..16].try_into().unwrap());

    // Truncate hash_extra to 100 chars (same as in the TS code: `hashExtra.slice(0, 100)`)
    let truncated_hash_extra: String = hash_extra.chars().take(100).collect();

    // Build the input string
    let input_str = format!(
        "{}-{}-{}-{}-{}-{}",
        team_id, ip, root_domain, user_agent, n, truncated_hash_extra
    );

    // Compute SipHash 2-4
    let mut hasher = SipHasher24::new_with_keys(key0, key1);
    hasher.write(input_str.as_bytes());
    let hash_value = hasher.finish128();

    let h1 = hash_value.h1.to_le_bytes().to_vec();
    let h2 = hash_value.h2.to_le_bytes().to_vec();

    // rearrange the bytes to match the TS implementation
    let mut rearranged = Vec::with_capacity(16);
    rearranged.extend_from_slice(&h2[4..8]);
    rearranged.extend_from_slice(&h2[0..4]);
    rearranged.extend_from_slice(&h1[4..8]);
    rearranged.extend_from_slice(&h1[0..4]);
    rearranged
}

#[cfg(test)]
mod do_hash_tests {
    use super::*; // Only if do_hash() is in the same crate and is public.
                  // Otherwise `use <your_crate_name>::do_hash;`

    use serde::Deserialize;
    use std::fs;
    use std::path::Path;
    use base64::{self, Engine, engine::general_purpose};

    // Match the JSON structure.
    #[derive(Deserialize)]
    struct TestCase {
        salt: String,
        team_id: u64,
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

    // If your do_hash function is in a separate crate or module,
    // import it: use your_crate::do_hash;

    #[test]
    fn test_do_hash_from_json() {
        // Load the test cases from the json file. This file should be identical across this
        // Rust implementation and the TypeScript implementation
        let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("src/test_cases.json");
        let data_str = fs::read_to_string(&path)
        .expect(&format!("Failed to read file at: {}", &path.display()));
        let test_data: TestData = serde_json::from_str(&data_str)
            .expect("Failed to parse JSON test data");

        // For each test case, decode the salt and expected result from base64,
        // run do_hash, and compare.
        for (i, tc) in test_data.test_cases.iter().enumerate() {
            let salt_bytes = general_purpose::STANDARD.decode(&tc.salt)                
                .unwrap_or_else(|_| panic!("Test case {}: invalid base64 salt", i));
            let expected_bytes = general_purpose::STANDARD.decode(&tc.expected)
                .unwrap_or_else(|_| panic!("Test case {}: invalid base64 expected hash", i));

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
                actual, expected_bytes,
                "Test case {} failed. Expected {:?}, got {:?}",
                i, expected_bytes, actual
            );
        }
    }
}