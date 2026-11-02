//! The Redis side of the keyed token bucket: the Lua scripts that `redis-token-bucket-v2.lua.ts`
//! and `redis-token-bucket-v3.lua.ts` register, and a pipeline of `EVALSHA` calls.
//!
//! The script text is byte-identical to the TypeScript, so both consumers load the same SHA and
//! share bucket state. Redis returns each Lua number truncated to an integer.

use std::collections::HashSet;
use std::sync::{Mutex, OnceLock};

use async_trait::async_trait;
use redis::aio::ConnectionLike;
use redis::Value;

#[derive(Debug)]
pub struct LuaScript {
    pub name: &'static str,
    pub source: &'static str,
    pub sha: String,
}

pub fn token_bucket_v2() -> &'static LuaScript {
    static SCRIPT: OnceLock<LuaScript> = OnceLock::new();
    SCRIPT.get_or_init(|| script("checkRateLimitV2", include_str!("token_bucket_v2.lua")))
}

pub fn token_bucket_v3() -> &'static LuaScript {
    static SCRIPT: OnceLock<LuaScript> = OnceLock::new();
    SCRIPT.get_or_init(|| script("checkRateLimitV3", include_str!("token_bucket_v3.lua")))
}

fn script(name: &'static str, source: &'static str) -> LuaScript {
    LuaScript {
        name,
        source,
        sha: redis::Script::new(source).get_hash().to_string(),
    }
}

/// The JavaScript number that ioredis (redis-parser 3) reads for an integer reply. It adds one
/// decimal digit at a time in floating point, so a value above 2^53 can round differently from a
/// direct conversion: `-9223372036854775808` reads as `-9223372036854778000`.
pub fn ioredis_integer(n: i64) -> f64 {
    let mut number = 0f64;
    for digit in n.unsigned_abs().to_string().bytes() {
        number = number * 10.0 + (digit - b'0') as f64;
    }
    if n < 0 {
        -number
    } else {
        number
    }
}

/// One script call: `KEYS[1]` and `ARGV`, already written as ioredis writes numbers (`String(n)`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ScriptCall {
    pub key: String,
    pub args: Vec<String>,
}

pub type ScriptReply = Result<Vec<i64>, String>;

#[async_trait]
pub trait TokenBucketRedis: Send + Sync {
    /// Runs one `EVALSHA` per call in one pipeline. `Err` means the pipeline failed as a whole,
    /// which `usePipeline({ failOpen: true })` turns into `null`.
    async fn eval_pipeline(
        &self,
        script: &LuaScript,
        calls: &[ScriptCall],
    ) -> Result<Vec<ScriptReply>, String>;
}

/// Like ioredis, it runs `SCRIPT EXISTS` and `SCRIPT LOAD` once per script, then sends bare
/// `EVALSHA`. If Redis later loses the script, each call replies `NOSCRIPT`, which the limiter
/// treats as a missing reply, as Node does.
pub struct RedisTokenBucket<C> {
    conn: C,
    loaded: Mutex<HashSet<String>>,
}

impl<C> RedisTokenBucket<C> {
    pub fn new(conn: C) -> Self {
        RedisTokenBucket {
            conn,
            loaded: Mutex::new(HashSet::new()),
        }
    }
}

fn reply_from_value(value: Value) -> ScriptReply {
    match value {
        Value::Array(items) => items
            .into_iter()
            .map(|item| match item {
                Value::Int(n) => Ok(n),
                other => Err(format!("unexpected script reply item: {other:?}")),
            })
            .collect(),
        Value::ServerError(e) => Err(format!("{e:?}")),
        other => Err(format!("unexpected script reply: {other:?}")),
    }
}

#[async_trait]
impl<C> TokenBucketRedis for RedisTokenBucket<C>
where
    C: ConnectionLike + Clone + Send + Sync + 'static,
{
    async fn eval_pipeline(
        &self,
        script: &LuaScript,
        calls: &[ScriptCall],
    ) -> Result<Vec<ScriptReply>, String> {
        let mut conn = self.conn.clone();
        let is_loaded = self
            .loaded
            .lock()
            .map_err(|e| e.to_string())?
            .contains(&script.sha);
        if !is_loaded {
            let exists: Vec<bool> = redis::cmd("SCRIPT")
                .arg("EXISTS")
                .arg(&script.sha)
                .query_async(&mut conn)
                .await
                .map_err(|e| e.to_string())?;
            if !exists.first().copied().unwrap_or(false) {
                let _: String = redis::cmd("SCRIPT")
                    .arg("LOAD")
                    .arg(script.source)
                    .query_async(&mut conn)
                    .await
                    .map_err(|e| e.to_string())?;
            }
            self.loaded
                .lock()
                .map_err(|e| e.to_string())?
                .insert(script.sha.clone());
        }
        let mut pipe = redis::pipe();
        for call in calls {
            pipe.cmd("EVALSHA")
                .arg(&script.sha)
                .arg(1)
                .arg(&call.key)
                .arg(&call.args);
        }
        let values = conn
            .req_packed_commands(&pipe, 0, calls.len())
            .await
            .map_err(|e| e.to_string())?;
        Ok(values.into_iter().map(reply_from_value).collect())
    }
}
