use std::{collections::HashMap, fmt::Debug, time::Duration};

use base64::{prelude::BASE64_URL_SAFE, Engine};
use fernet::MultiFernet;
use metrics::counter;
use moka::sync::{Cache, CacheBuilder};

use serde_json::Value;
use sqlx::Postgres;
use tracing::{debug, warn};
use uuid::Uuid;

use crate::{
    error::UnhandledError,
    metric_consts::{TRANSFORMATION_OUTCOME, TRANSFORMATION_SECRETS_FAILED},
    pipeline::transformations::{
        types::{HogFunction, HogFunctionTemplate, HogFunctionType, TransformOutcome},
        TransformResult,
    },
};

// This entire module could be in `common`, and only isn't because nobody else needs it yet.

pub struct HogFunctionManager {
    function_cache: Cache<i32, Vec<CachedWeight<HogFunction>>>,

    // There are a small number of templates, we mostly use the cache here to re-fetch them occasionally
    template_cache: Cache<Uuid, CachedWeight<HogFunctionTemplate>>,
}

#[derive(Debug, Clone, Default)]
pub struct HogFunctionManagerConfig {
    pub function_cache_size: u64,
    pub function_cache_ttl: Duration,
    pub template_cache_size: u64,
    pub template_cache_ttl: Duration,
}

impl HogFunctionManager {
    pub fn new(config: HogFunctionManagerConfig) -> Self {
        let function_cache = CacheBuilder::new(config.function_cache_size)
            .time_to_live(config.function_cache_ttl)
            .weigher(|_, v: &Vec<CachedWeight<HogFunction>>| {
                v.iter().map(|f| f.weight as u32).sum() // CAST: if this is larger than 4GB worth of data, we're dead anyway
            })
            .build();
        let template_cache = CacheBuilder::new(config.template_cache_size)
            .time_to_live(config.template_cache_ttl)
            .weigher(|_, v: &CachedWeight<HogFunctionTemplate>| v.weight as u32) // CAST: as above
            .build();
        HogFunctionManager {
            function_cache,
            template_cache,
        }
    }

    pub async fn get_functions<'c, E>(
        &self,
        e: E,
        team_id: i32,
    ) -> Result<Vec<HogFunction>, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = Postgres>,
    {
        if let Some(functions) = self.function_cache.get(&team_id) {
            return Ok(functions.into_iter().map(|f| f.inner).collect());
        };

        // TODO - we hardcode transoformations as the function type in a bunch of places. Really the cache should be keyed
        // on function type as well as team id.
        let fetched =
            HogFunction::fetch_for_team(e, team_id, HogFunctionType::Transformation).await?;
        let cached: Vec<_> = fetched
            .clone()
            .into_iter()
            .map(|f| CachedWeight::from(f))
            .collect();
        self.function_cache.insert(team_id, cached);
        Ok(fetched)
    }

    pub async fn get_template<'c, E>(
        &self,
        e: E,
        template_id: Uuid,
    ) -> Result<Option<HogFunctionTemplate>, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = Postgres>,
    {
        if let Some(template) = self.template_cache.get(&template_id) {
            return Ok(Some(template.inner));
        };

        let fetched = HogFunctionTemplate::fetch_by_id(e, template_id).await?;
        let cached = CachedWeight::from(fetched.clone());
        self.template_cache.insert(template_id, cached);
        Ok(Some(fetched))
    }

    pub async fn get_function_bytecode<'c, E>(
        &self,
        e: E,
        function: &HogFunction,
    ) -> Result<Option<Value>, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = Postgres>,
    {
        if let Some(bc) = function.bytecode.clone() {
            return Ok(Some(bc)); // If the functions got bytecode, just use that
        }

        // Otherwise, if it's got a template, use that
        let Some(template_id) = function.hog_function_template_id else {
            return Ok(None);
        };
        let template = self.get_template(e, template_id).await?;
        Ok(template.and_then(|t| t.bytecode))
    }

    pub async fn get_function_inputs(
        &self,
        secret_input_keys: &[String],
        function: &HogFunction,
    ) -> Result<HashMap<String, Value>, UnhandledError> {
        let mut res = HashMap::new();
        if let Some(Value::Object(inputs)) = function.inputs.as_ref() {
            for (key, value) in inputs {
                res.insert(key.clone(), value.clone());
            }
        }

        if let Some(encrypted) = function.encrypted_inputs.as_ref() {
            // Matching the plugin server, each key is 32 btyes of utf8 data, which we
            // then, treating as raw bytes, b64 encode before passing into fernet. I'm
            // a little thrown off by this - seems like keys could just be the already
            // encoded strings, but :shrug:, this is how it's done there, so it's how
            // I'll do it here
            let fernets: Vec<_> = secret_input_keys
                .iter()
                .map(|k| k.as_bytes())
                .map(|b| BASE64_URL_SAFE.encode(b))
                .filter_map(|k| fernet::Fernet::new(&k))
                .collect();
            let fernet = MultiFernet::new(fernets);
            let Ok(decrypted) = fernet.decrypt(encrypted) else {
                warn!(
                    "Failed to decrypt encrypted inputs for function {}",
                    function.id
                );
                counter!(
                    TRANSFORMATION_SECRETS_FAILED,
                    &[("cause", "failed-decryption")]
                )
                .increment(1);
                return Ok(res);
            };
            let Ok(secrets) = serde_json::from_slice::<HashMap<String, Value>>(&decrypted) else {
                warn!(
                    "Failed to parse encrypted inputs for function {}",
                    function.id
                );
                counter!(
                    TRANSFORMATION_SECRETS_FAILED,
                    &[("cause", "failed-parsing")]
                )
                .increment(1);
                return Ok(res);
            };
            res.extend(secrets);
        }

        Ok(res)
    }

    pub async fn disable_function(
        &self,
        function: &HogFunction,
        s: impl ToString,
    ) -> Result<(), UnhandledError> {
        // TODO - for now, all this does is this - need to coord with CDP. This is called when we failed to start executing
        // a function /at all/, which indicates either a cymbal bug or an invalid function, rather than the function failing
        // during execution.
        debug!("Function {} disabled due to {}", function.id, s.to_string());
        Ok(())
    }

    pub async fn process_execution_results(
        &self,
        results: HashMap<Uuid, Vec<TransformResult>>,
    ) -> Result<(), UnhandledError> {
        for (_function_id, result_set) in results {
            for result in result_set {
                // TODO - emit logs + metrics to kafka (probably as a best-effort task), figure out how to handle e.g. function disableing
                // (co-ord with CDP).
                let label = match result.outcome {
                    TransformOutcome::Skipped => "skipped",
                    TransformOutcome::Success => "success",
                    TransformOutcome::FilterFailure(_) => "filter failure",
                    TransformOutcome::TransformFailure(_) => "transform failure",
                };

                counter!(TRANSFORMATION_OUTCOME, &[("outcome", label)]).increment(1);
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone)]
struct CachedWeight<T>
where
    T: Clone + Debug,
{
    pub inner: T,
    pub weight: usize,
}

impl From<HogFunction> for CachedWeight<HogFunction> {
    fn from(function: HogFunction) -> Self {
        let weight = function.cache_weight();
        CachedWeight {
            inner: function,
            weight,
        }
    }
}

impl From<HogFunctionTemplate> for CachedWeight<HogFunctionTemplate> {
    fn from(template: HogFunctionTemplate) -> Self {
        let weight = template.cache_weight();
        CachedWeight {
            inner: template,
            weight,
        }
    }
}
