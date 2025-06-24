use rand::Rng;

const BASE62_CHARS: &[u8] = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
const LENGTH: usize = 6;

/// Generates a random base62 string of length 6
pub fn generate_base62_string() -> String {
    let mut rng = rand::thread_rng();
    let mut result = String::with_capacity(LENGTH);

    for _ in 0..LENGTH {
        let idx = rng.gen_range(0..62);
        result.push(BASE62_CHARS[idx] as char);
    }

    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_generate_base62_string() {
        let result = generate_base62_string();
        assert_eq!(result.len(), 6);

        // Verify all characters are valid base62
        for c in result.chars() {
            assert!(BASE62_CHARS.contains(&(c as u8)));
        }
    }
}
