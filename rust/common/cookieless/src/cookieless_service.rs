use std::collections::HashMap;
use std::sync::Arc;

use tokio::sync::Mutex;

// Replace this with whatever your salt data actually is.
// If you use a `Uint32Array` in TypeScript, you might represent it
// in Rust as a `Vec<u32>`, a [u32; 4], or similar.
#[derive(Clone, Debug)]
struct Salt {
    data: Vec<u32>,
}

// Placeholder for your Redis client helpers.
struct RedisClient;

impl RedisClient {
    async fn get_salt_base64(&self, _key: &str) -> Option<String> {
        // TODO: implement a real Redis GET
        None
    }

    async fn set_salt_if_not_exists(&self, _key: &str, _value: &str, _ttl_seconds: u64) -> bool {
        // TODO: implement a real Redis SETNX (return true if successful)
        false
    }
}

// Convert base64 <-> salt type. (Stubs)
fn base64_to_salt(_b64: &str) -> MySalt {
    // 1) Decode the base64 string into a Vec<u8>
    let bytes = decode(encoded)?;

    // Ensure the byte length is divisible by 4
    if bytes.len() % 4 != 0 {
        return Err("Decoded data length is not a multiple of 4 bytes.".into());
    }

    // 2) Convert 4 bytes at a time into u32
    // Adjust endianness to match your data expectations:
    //  - `from_be_bytes` for big-endian,
    //  - `from_le_bytes` for little-endian
    let mut result = Vec::with_capacity(bytes.len() / 4);
    for chunk in bytes.chunks_exact(4) {
        let number = u32::from_be_bytes(chunk.try_into().unwrap());
        result.push(number);
    }

    Salt { data: result }
}
fn salt_to_base64(_salt: &Salt) -> String {
    "someBase64String".to_string()
}

// Helper to create random salt.
fn create_random_salt() -> Salt {
    // In practice, generate cryptographically random data:
    Salt { data: vec![1234, 5678, 91011, 121314] }
}

// The shared state that holds our in-memory salt map.
#[derive(Default)]
struct SaltCache {
    // Maps YYYYMMDD -> MySalt
    local_salt_map: HashMap<String, MySalt>,
}

// Our main struct that has a Redis client and an in-memory salt cache.
#[derive(Clone)]
struct SaltLoader {
    redis_client: Arc<RedisClient>,
    // We protect the entire HashMap with a single async Mutex.
    cache: Arc<Mutex<SaltCache>>,
}

impl SaltLoader {
    // Create a new loader.
    fn new(redis_client: RedisClient) -> Self {
        SaltLoader {
            redis_client: Arc::new(redis_client),
            cache: Arc::new(Mutex::new(SaltCache {
                local_salt_map: HashMap::new(),
            })),
        }
    }

    // Equivalent to your getSaltForDay
    // (ignoring validity checks and metrics for brevity).
    async fn get_salt_for_day(&self, yyyymmdd: &str, ttl_seconds: u64) -> MySalt {
        // First, do a quick read-only check. If we find it, return immediately.
        {
            let cache_guard = self.cache.lock().await;
            if let Some(salt) = cache_guard.local_salt_map.get(yyyymmdd) {
                // Found it in-memory
                return salt.clone();
            }
        }

        // If not found, we need to do the full "load or set" logic under the lock.
        let mut cache_guard = self.cache.lock().await;

        // Double-check after acquiring the lock in case another task got here first.
        if let Some(salt) = cache_guard.local_salt_map.get(yyyymmdd) {
            return salt.clone();
        }

        // Not in local map -> try from Redis
        let key = format!("cookieless_salt:{}", yyyymmdd);
        if let Some(salt_base64) = self.redis_client.get_salt_base64(&key).await {
            // Found in Redis
            let salt = base64_to_salt(&salt_base64);
            cache_guard.local_salt_map.insert(yyyymmdd.to_owned(), salt.clone());
            return salt;
        }

        // Not in Redis -> generate a new salt and attempt SETNX
        let new_salt = create_random_salt();
        let new_salt_b64 = salt_to_base64(&new_salt);

        let setnx_ok = self.redis_client
            .set_salt_if_not_exists(&key, &new_salt_b64, ttl_seconds)
            .await;

        if setnx_ok {
            // We successfully wrote it, so store locally and return.
            cache_guard.local_salt_map.insert(yyyymmdd.to_owned(), new_salt.clone());
            return new_salt;
        }

        // If we couldn't do SETNX, it means another process or node already set it.
        // Try reading from Redis again.
        if let Some(salt_base64_retry) = self.redis_client.get_salt_base64(&key).await {
            let salt = base64_to_salt(&salt_base64_retry);
            cache_guard.local_salt_map.insert(yyyymmdd.to_owned(), salt.clone());
            return salt;
        }

        // If we still don't have it, something is wrong.
        panic!("Failed to load salt from Redis");
    }
}

#[tokio::main]
async fn main() {
    // Create our SaltLoader with a RedisClient (both stubs in this example).
    let loader = SaltLoader::new(RedisClient);

    // Suppose we call get_salt_for_day many times concurrently.
    let mut tasks = vec![];
    for i in 0..5 {
        let loader_clone = loader.clone();
        let day = "20250101".to_string();
        tasks.push(tokio::spawn(async move {
            let salt = loader_clone.get_salt_for_day(&day, 24 * 3600).await;
            println!("Task {} got salt: {:?}", i, salt);
        }));
    }

    // Await all tasks
    for t in tasks {
        let _ = t.await;
    }
}
