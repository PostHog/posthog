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

/// Like ioredis, it runs `SCRIPT EXISTS` and `SCRIPT LOAD` before it sends bare `EVALSHA`. If Redis
/// loses the script, each call of that pipeline replies `NOSCRIPT`, which the limiter treats as a
/// missing reply, as Node does. The next pipeline loads the script again. ioredis clears its
/// script cache every 60 seconds, so Node recovers within that time; see PORTING.md.
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
        let lost_script = values
            .iter()
            .any(|value| matches!(value, Value::ServerError(e) if e.code() == "NOSCRIPT"));
        if lost_script {
            self.loaded
                .lock()
                .map_err(|e| e.to_string())?
                .remove(&script.sha);
        }
        Ok(values.into_iter().map(reply_from_value).collect())
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use redis::{Cmd, Pipeline, RedisFuture};

    use super::*;

    /// A Redis that answers the script commands and can lose its script cache.
    #[derive(Clone, Default)]
    struct FakeRedis {
        state: Arc<Mutex<(bool, usize)>>,
    }

    impl ConnectionLike for FakeRedis {
        fn req_packed_command<'a>(&'a mut self, cmd: &'a Cmd) -> RedisFuture<'a, Value> {
            let mut state = self.state.lock().unwrap();
            let load = cmd
                .args_iter()
                .any(|arg| matches!(arg, redis::Arg::Simple(b"LOAD")));
            let reply = if load {
                *state = (true, state.1 + 1);
                Value::BulkString(token_bucket_v2().sha.clone().into_bytes())
            } else {
                Value::Array(vec![Value::Int(state.0.into())])
            };
            Box::pin(async move { Ok(reply) })
        }

        fn req_packed_commands<'a>(
            &'a mut self,
            _pipe: &'a Pipeline,
            _offset: usize,
            count: usize,
        ) -> RedisFuture<'a, Vec<Value>> {
            let loaded = self.state.lock().unwrap().0;
            let reply = if loaded {
                Value::Array(vec![Value::Int(1), Value::Int(2)])
            } else {
                redis::parse_redis_value(b"-NOSCRIPT No matching script.\r\n").unwrap()
            };
            Box::pin(async move { Ok(vec![reply; count]) })
        }

        fn get_db(&self) -> i64 {
            0
        }
    }

    #[tokio::test]
    async fn a_lost_script_is_loaded_again_by_the_next_pipeline() {
        let redis = FakeRedis::default();
        let bucket = RedisTokenBucket::new(redis.clone());
        let calls = [ScriptCall {
            key: "k".into(),
            args: vec![],
        }];
        let ok = |replies: Vec<ScriptReply>| replies == vec![Ok(vec![1, 2])];
        assert!(ok(bucket
            .eval_pipeline(token_bucket_v2(), &calls)
            .await
            .unwrap()));
        // SCRIPT FLUSH: the pipeline that meets it gets NOSCRIPT, as the Node pipeline does.
        redis.state.lock().unwrap().0 = false;
        let lost = bucket
            .eval_pipeline(token_bucket_v2(), &calls)
            .await
            .unwrap();
        assert!(lost[0].is_err());
        assert!(ok(bucket
            .eval_pipeline(token_bucket_v2(), &calls)
            .await
            .unwrap()));
        assert_eq!(redis.state.lock().unwrap().1, 2);
    }
}
