#[derive(Debug, Clone, Eq, PartialEq)]
pub struct SymbolStoreConfig {
    pub allow_internal_ips: bool,
    pub sourcemap_timeout_seconds: u64,
    pub sourcemap_connect_timeout_seconds: u64,
    pub cache_max_bytes: usize,
    pub object_storage_bucket: String,
    pub object_storage_prefix: String,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_config() -> SymbolStoreConfig {
        SymbolStoreConfig {
            allow_internal_ips: true,
            sourcemap_timeout_seconds: 30,
            sourcemap_connect_timeout_seconds: 10,
            cache_max_bytes: 64 * 1024 * 1024,
            object_storage_bucket: "my-bucket".to_string(),
            object_storage_prefix: "my-prefix".to_string(),
        }
    }

    #[test]
    fn config_clone_is_equal() {
        let cfg = sample_config();
        let cloned = cfg.clone();
        assert_eq!(cfg, cloned);
    }

    #[test]
    fn config_equality_differs_on_timeout() {
        let mut a = sample_config();
        let mut b = sample_config();
        a.sourcemap_timeout_seconds = 30;
        b.sourcemap_timeout_seconds = 60;
        assert_ne!(a, b);
    }

    #[test]
    fn config_equality_differs_on_connect_timeout() {
        let mut a = sample_config();
        let b = sample_config();
        a.sourcemap_connect_timeout_seconds = 99;
        assert_ne!(a, b);
    }

    #[test]
    fn config_equality_differs_on_bucket() {
        let mut a = sample_config();
        let b = sample_config();
        a.object_storage_bucket = "other-bucket".to_string();
        assert_ne!(a, b);
    }

    #[test]
    fn config_equality_differs_on_allow_internal_ips() {
        let mut a = sample_config();
        let b = sample_config();
        a.allow_internal_ips = !b.allow_internal_ips;
        assert_ne!(a, b);
    }
}
