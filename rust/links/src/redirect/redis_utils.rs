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

    pub fn get_redis_key_for_url(self, origin_domain: &str, origin_key: &str) -> String {
        let key = format!("{}{}/{}", self.get_prefix(), origin_domain, origin_key);
        key
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_get_redis_key_for_url_internal() {
        let origin_domain = "example.com";
        let origin_key = "abc123";
        let key = RedisRedirectKeyPrefix::Internal.get_redis_key_for_url(origin_domain, origin_key);
        assert_eq!(key, "internal_example.com/abc123");
    }

    #[test]
    fn test_get_redis_key_for_url_external() {
        let origin_domain = "example.com";
        let origin_key = "xyz789";
        let key = RedisRedirectKeyPrefix::External.get_redis_key_for_url(origin_domain, origin_key);
        assert_eq!(key, "external_example.com/xyz789");
    }
}
