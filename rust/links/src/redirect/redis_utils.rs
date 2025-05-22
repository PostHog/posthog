pub enum RedisRedirectKeyPrefix {
    Internal,
    External,
}

impl RedisRedirectKeyPrefix {
    fn get_prefix(self) -> String {
        match self {
            RedisRedirectKeyPrefix::Internal => "internal_".into(),
            RedisRedirectKeyPrefix::External => "external_".into(),
        }
    }

    pub fn get_redis_key_for_url(self, short_link_domain: &str, short_code: &str) -> String {
        let key = format!("{}{}/{}", self.get_prefix(), short_link_domain, short_code);
        key
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_get_redis_key_for_url_internal() {
        let short_link_domain = "example.com";
        let short_code = "abc123";
        let key =
            RedisRedirectKeyPrefix::Internal.get_redis_key_for_url(short_link_domain, short_code);
        assert_eq!(key, "internal_example.com/abc123");
    }

    #[test]
    fn test_get_redis_key_for_url_external() {
        let short_link_domain = "example.com";
        let short_code = "xyz789";
        let key =
            RedisRedirectKeyPrefix::External.get_redis_key_for_url(short_link_domain, short_code);
        assert_eq!(key, "external_example.com/xyz789");
    }
}
