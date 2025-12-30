use async_trait::async_trait;
use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use crate::{Client, CustomRedisError, RedisValueFormat};

#[derive(Clone)]
pub struct MockRedisClient {
    zrangebyscore_ret: HashMap<String, Vec<String>>,
    hincrby_ret: HashMap<String, Result<(), CustomRedisError>>,
    get_ret: HashMap<String, Result<String, CustomRedisError>>,
    get_raw_bytes_ret: HashMap<String, Result<Vec<u8>, CustomRedisError>>,
    set_ret: HashMap<String, Result<(), CustomRedisError>>,
    set_nx_ex_ret: HashMap<String, Result<bool, CustomRedisError>>,
    batch_incr_by_expire_nx_ret: Option<Result<(), CustomRedisError>>,
    batch_incr_by_expire_ret: Option<Result<(), CustomRedisError>>,
    del_ret: HashMap<String, Result<(), CustomRedisError>>,
    hget_ret: HashMap<String, Result<String, CustomRedisError>>,
    scard_ret: HashMap<String, Result<u64, CustomRedisError>>,
    mget_ret: HashMap<String, Option<Vec<u8>>>,
    mget_error: Option<CustomRedisError>,
    calls: Arc<Mutex<Vec<MockRedisCall>>>,
}

impl Default for MockRedisClient {
    fn default() -> Self {
        Self {
            zrangebyscore_ret: HashMap::new(),
            hincrby_ret: HashMap::new(),
            get_ret: HashMap::new(),
            get_raw_bytes_ret: HashMap::new(),
            set_ret: HashMap::new(),
            set_nx_ex_ret: HashMap::new(),
            batch_incr_by_expire_nx_ret: None,
            batch_incr_by_expire_ret: None,
            del_ret: HashMap::new(),
            hget_ret: HashMap::new(),
            scard_ret: HashMap::new(),
            mget_ret: HashMap::new(),
            mget_error: None,
            calls: Arc::new(Mutex::new(Vec::new())),
        }
    }
}

impl MockRedisClient {
    pub fn new() -> Self {
        Self::default()
    }

    // Helper method to safely lock the calls mutex
    fn lock_calls(&self) -> std::sync::MutexGuard<'_, Vec<MockRedisCall>> {
        match self.calls.lock() {
            Ok(guard) => guard,
            Err(poisoned) => poisoned.into_inner(),
        }
    }

    pub fn zrangebyscore_ret(&mut self, key: &str, ret: Vec<String>) -> Self {
        self.zrangebyscore_ret.insert(key.to_owned(), ret);
        self.clone()
    }

    pub fn hincrby_ret(&mut self, key: &str, ret: Result<(), CustomRedisError>) -> Self {
        self.hincrby_ret.insert(key.to_owned(), ret);

        self.clone()
    }

    pub fn get_ret(&mut self, key: &str, ret: Result<String, CustomRedisError>) -> Self {
        self.get_ret.insert(key.to_owned(), ret);
        self.clone()
    }

    pub fn get_raw_bytes_ret(&mut self, key: &str, ret: Result<Vec<u8>, CustomRedisError>) -> Self {
        self.get_raw_bytes_ret.insert(key.to_owned(), ret);
        self.clone()
    }

    pub fn set_ret(&mut self, key: &str, ret: Result<(), CustomRedisError>) -> Self {
        self.set_ret.insert(key.to_owned(), ret);
        self.clone()
    }

    pub fn del_ret(&mut self, key: &str, ret: Result<(), CustomRedisError>) -> Self {
        self.del_ret.insert(key.to_owned(), ret);
        self.clone()
    }

    pub fn hget_ret(&mut self, key: &str, ret: Result<String, CustomRedisError>) -> Self {
        self.hget_ret.insert(key.to_owned(), ret);
        self.clone()
    }

    pub fn scard_ret(&mut self, key: &str, ret: Result<u64, CustomRedisError>) -> Self {
        self.scard_ret.insert(key.to_owned(), ret);
        self.clone()
    }

    pub fn get_calls(&self) -> Vec<MockRedisCall> {
        self.lock_calls().clone()
    }

    pub fn set_nx_ex_ret(&mut self, key: &str, ret: Result<bool, CustomRedisError>) -> Self {
        self.set_nx_ex_ret.insert(key.to_owned(), ret);
        self.clone()
    }

    pub fn batch_incr_by_expire_nx_ret(&mut self, ret: Result<(), CustomRedisError>) -> Self {
        self.batch_incr_by_expire_nx_ret = Some(ret);
        self.clone()
    }

    pub fn batch_incr_by_expire_ret(&mut self, ret: Result<(), CustomRedisError>) -> Self {
        self.batch_incr_by_expire_ret = Some(ret);
        self.clone()
    }

    pub fn mget_ret(&mut self, key: &str, ret: Option<Vec<u8>>) -> Self {
        self.mget_ret.insert(key.to_owned(), ret);
        self.clone()
    }

    pub fn mget_error(&mut self, err: CustomRedisError) -> Self {
        self.mget_error = Some(err);
        self.clone()
    }
}

#[derive(Debug, Clone)]
pub enum MockRedisValue {
    None,
    Error(CustomRedisError),
    String(String),
    StringWithTTL(String, u64),
    VecString(Vec<String>),
    I32(i32),
    I64(i64),
    MinMax(String, String),
    StringWithFormat(String, RedisValueFormat),
    StringWithTTLAndFormat(String, u64, RedisValueFormat),
}

#[derive(Debug, Clone)]
#[allow(dead_code)]
pub struct MockRedisCall {
    pub op: String,
    pub key: String,
    pub value: MockRedisValue,
}

#[async_trait]
impl Client for MockRedisClient {
    async fn zrangebyscore(
        &self,
        key: String,
        min: String,
        max: String,
    ) -> Result<Vec<String>, CustomRedisError> {
        let mut calls = self.lock_calls();
        calls.push(MockRedisCall {
            op: "zrangebyscore".to_string(),
            key: key.clone(),
            value: MockRedisValue::MinMax(min, max),
        });

        match self.zrangebyscore_ret.get(&key) {
            Some(val) => Ok(val.clone()),
            None => Err(CustomRedisError::NotFound),
        }
    }

    async fn hincrby(
        &self,
        key: String,
        field: String,
        count: Option<i32>,
    ) -> Result<(), CustomRedisError> {
        let mut calls = self.lock_calls();
        calls.push(MockRedisCall {
            op: "hincrby".to_string(),
            key: format!("{key}:{field}"),
            value: match count {
                None => MockRedisValue::None,
                Some(v) => MockRedisValue::I32(v),
            },
        });

        match self.hincrby_ret.get(&key) {
            Some(result) => result.clone(),
            None => Err(CustomRedisError::NotFound),
        }
    }

    async fn get(&self, key: String) -> Result<String, CustomRedisError> {
        let mut calls = self.lock_calls();
        calls.push(MockRedisCall {
            op: "get".to_string(),
            key: key.clone(),
            value: MockRedisValue::None,
        });

        match self.get_ret.get(&key) {
            Some(result) => result.clone(),
            None => Err(CustomRedisError::NotFound),
        }
    }

    async fn get_with_format(
        &self,
        key: String,
        format: RedisValueFormat,
    ) -> Result<String, CustomRedisError> {
        self.lock_calls().push(MockRedisCall {
            op: "get_with_format".to_string(),
            key: key.clone(),
            value: MockRedisValue::StringWithFormat("".to_string(), format),
        });

        self.get_ret
            .get(&key)
            .cloned()
            .unwrap_or(Err(CustomRedisError::NotFound))
    }

    async fn get_raw_bytes(&self, key: String) -> Result<Vec<u8>, CustomRedisError> {
        self.lock_calls().push(MockRedisCall {
            op: "get_raw_bytes".to_string(),
            key: key.clone(),
            value: MockRedisValue::String("".to_string()),
        });

        // First try the dedicated raw bytes storage
        if let Some(result) = self.get_raw_bytes_ret.get(&key) {
            return result.clone();
        }

        // Fall back to string conversion for backward compatibility
        match self
            .get_ret
            .get(&key)
            .cloned()
            .unwrap_or(Err(CustomRedisError::NotFound))
        {
            Ok(string_data) => Ok(string_data.into_bytes()),
            Err(e) => Err(e),
        }
    }

    async fn set(&self, key: String, value: String) -> Result<(), CustomRedisError> {
        let mut calls = self.lock_calls();
        calls.push(MockRedisCall {
            op: "set".to_string(),
            key: key.clone(),
            value: MockRedisValue::String(value.clone()),
        });

        match self.set_ret.get(&key) {
            Some(result) => result.clone(),
            None => Err(CustomRedisError::NotFound),
        }
    }

    async fn set_with_format(
        &self,
        key: String,
        value: String,
        format: RedisValueFormat,
    ) -> Result<(), CustomRedisError> {
        self.lock_calls().push(MockRedisCall {
            op: "set_with_format".to_string(),
            key: key.clone(),
            value: MockRedisValue::StringWithFormat(value.clone(), format),
        });

        self.set_ret.get(&key).cloned().unwrap_or(Ok(()))
    }

    async fn setex(
        &self,
        key: String,
        value: String,
        seconds: u64,
    ) -> Result<(), CustomRedisError> {
        self.lock_calls().push(MockRedisCall {
            op: "setex".to_string(),
            key: key.clone(),
            value: MockRedisValue::StringWithTTL(value.clone(), seconds),
        });

        self.set_ret.get(&key).cloned().unwrap_or(Ok(()))
    }

    async fn set_nx_ex(
        &self,
        key: String,
        value: String,
        seconds: u64,
    ) -> Result<bool, CustomRedisError> {
        let mut calls = self.lock_calls();
        calls.push(MockRedisCall {
            op: "set_nx_ex".to_string(),
            key: key.clone(),
            value: MockRedisValue::StringWithTTL(value.clone(), seconds),
        });

        match self.set_nx_ex_ret.get(&key) {
            Some(result) => result.clone(),
            None => Err(CustomRedisError::NotFound),
        }
    }

    async fn set_nx_ex_with_format(
        &self,
        key: String,
        value: String,
        seconds: u64,
        format: RedisValueFormat,
    ) -> Result<bool, CustomRedisError> {
        self.lock_calls().push(MockRedisCall {
            op: "set_nx_ex_with_format".to_string(),
            key: key.clone(),
            value: MockRedisValue::StringWithTTLAndFormat(value.clone(), seconds, format),
        });

        self.set_nx_ex_ret
            .get(&key)
            .cloned()
            .unwrap_or(Err(CustomRedisError::NotFound))
    }

    async fn batch_incr_by_expire_nx(
        &self,
        items: Vec<(String, i64)>,
        ttl_seconds: usize,
    ) -> Result<(), CustomRedisError> {
        self.lock_calls().push(MockRedisCall {
            op: "batch_incr_by_expire_nx".to_string(),
            key: format!("items={};ttl={}", items.len(), ttl_seconds),
            value: MockRedisValue::None,
        });

        match &self.batch_incr_by_expire_nx_ret {
            Some(ret) => ret.clone(),
            None => Ok(()),
        }
    }

    async fn batch_incr_by_expire(
        &self,
        items: Vec<(String, i64)>,
        ttl_seconds: usize,
    ) -> Result<(), CustomRedisError> {
        self.lock_calls().push(MockRedisCall {
            op: "batch_incr_by_expire".to_string(),
            key: format!("items={};ttl={}", items.len(), ttl_seconds),
            value: MockRedisValue::None,
        });

        match &self.batch_incr_by_expire_ret {
            Some(ret) => ret.clone(),
            None => Ok(()),
        }
    }

    async fn del(&self, key: String) -> Result<(), CustomRedisError> {
        let mut calls = self.lock_calls();
        calls.push(MockRedisCall {
            op: "del".to_string(),
            key: key.clone(),
            value: MockRedisValue::None,
        });

        match self.del_ret.get(&key) {
            Some(result) => result.clone(),
            None => Err(CustomRedisError::NotFound),
        }
    }

    async fn hget(&self, key: String, field: String) -> Result<String, CustomRedisError> {
        let mut calls = self.lock_calls();
        calls.push(MockRedisCall {
            op: "hget".to_string(),
            key: format!("{key}:{field}"),
            value: MockRedisValue::None,
        });

        match self.hget_ret.get(&key) {
            Some(result) => result.clone(),
            None => Err(CustomRedisError::NotFound),
        }
    }

    async fn scard(&self, key: String) -> Result<u64, CustomRedisError> {
        let mut calls = self.lock_calls();
        calls.push(MockRedisCall {
            op: "scard".to_string(),
            key: key.to_string(),
            value: MockRedisValue::None,
        });

        match self.scard_ret.get(&key) {
            Some(result) => result.clone(),
            None => Err(CustomRedisError::NotFound),
        }
    }

    async fn mget(&self, keys: Vec<String>) -> Result<Vec<Option<Vec<u8>>>, CustomRedisError> {
        self.lock_calls().push(MockRedisCall {
            op: "mget".to_string(),
            key: format!("keys={}", keys.len()),
            value: MockRedisValue::VecString(keys.clone()),
        });

        if let Some(err) = &self.mget_error {
            return Err(err.clone());
        }

        let results: Vec<Option<Vec<u8>>> = keys
            .iter()
            .map(|k| self.mget_ret.get(k).and_then(|v| v.clone()))
            .collect();
        Ok(results)
    }
}
