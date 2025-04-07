use redis::RedisError;

#[derive(Debug)]
pub enum CacheError {
    Redis(RedisError)
}

impl From<RedisError> for CacheError {
    fn from(err: RedisError) -> Self {
        CacheError::Redis(err)
    }
}

impl std::fmt::Display for CacheError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            CacheError::Redis(err) => write!(f, "Redis error: {}", err),
        }
    }
}

impl std::error::Error for CacheError {}
