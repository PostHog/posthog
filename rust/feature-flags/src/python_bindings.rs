use pyo3::prelude::*;
use pyo3::types::PyDict;
use pyo3::Bound;
use serde_json::Value;
use std::collections::HashMap;
use std::sync::Arc;
use uuid::Uuid;

use crate::cohorts::cohort_cache_manager::CohortCacheManager;
use crate::database::PostgresRouter;
use crate::flags::flag_group_type_mapping::GroupTypeMappingCache;
use crate::flags::flag_matching::FeatureFlagMatcher;
use crate::flags::flag_models::FeatureFlagList;
use common_database::get_pool;

/// Evaluates feature flags for a given user/distinct_id
///
/// This function is the main entry point from Python. It:
/// 1. Creates database connection pools from the provided URLs
/// 2. Parses the feature flags JSON
/// 3. Creates a FeatureFlagMatcher
/// 4. Evaluates all flags
/// 5. Returns the results in Python-compatible format
///
/// # Arguments
/// * `persons_reader_url` - PostgreSQL connection URL for persons read replica
/// * `persons_writer_url` - PostgreSQL connection URL for persons writer
/// * `non_persons_reader_url` - PostgreSQL connection URL for non-persons read replica
/// * `non_persons_writer_url` - PostgreSQL connection URL for non-persons writer
/// * `team_id` - The team ID
/// * `project_id` - The project ID
/// * `distinct_id` - The user's distinct ID
/// * `feature_flags_json` - JSON string of feature flags (from cache)
/// * `groups` - Optional dict of group type name -> group key
/// * `person_property_overrides` - Optional dict of person property overrides
/// * `group_property_overrides` - Optional dict of group type -> properties
/// * `hash_key_override` - Optional hash key override ($anon_distinct_id)
/// * `flag_keys` - Optional list of specific flag keys to evaluate
///
/// # Returns
/// A tuple of (flag_values, evaluation_reasons, flag_payloads, errors_while_computing, flag_details)
#[pyfunction]
#[pyo3(signature = (
    persons_reader_url,
    persons_writer_url,
    non_persons_reader_url,
    non_persons_writer_url,
    team_id,
    project_id,
    distinct_id,
    feature_flags_json,
    groups=None,
    person_property_overrides=None,
    group_property_overrides=None,
    hash_key_override=None,
    flag_keys=None,
))]
fn evaluate_all_feature_flags_rust(
    py: Python,
    persons_reader_url: String,
    persons_writer_url: String,
    non_persons_reader_url: String,
    non_persons_writer_url: String,
    team_id: i32,
    project_id: i64,
    distinct_id: String,
    feature_flags_json: String,
    groups: Option<&Bound<'_, PyDict>>,
    person_property_overrides: Option<&Bound<'_, PyDict>>,
    group_property_overrides: Option<&Bound<'_, PyDict>>,
    hash_key_override: Option<String>,
    flag_keys: Option<Vec<String>>,
) -> PyResult<PyObject> {
    // Convert Python objects to Rust data structures BEFORE releasing the GIL
    let groups_map = groups.map(|g| convert_pydict_to_hashmap(g)).transpose()?;
    let person_props = person_property_overrides
        .map(|p| convert_pydict_to_value_hashmap(p))
        .transpose()?;
    let group_props = group_property_overrides
        .map(|gp| convert_pydict_to_nested_hashmap(gp))
        .transpose()?;

    // Release GIL while doing async work
    let result = py.allow_threads(|| {
        // Use tokio runtime to block on async function
        let runtime = tokio::runtime::Runtime::new().map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                "Failed to create tokio runtime: {}",
                e
            ))
        })?;

        runtime.block_on(async move {
            evaluate_flags_async(
                persons_reader_url,
                persons_writer_url,
                non_persons_reader_url,
                non_persons_writer_url,
                team_id,
                project_id,
                distinct_id,
                feature_flags_json,
                groups_map,
                person_props,
                group_props,
                hash_key_override,
                flag_keys,
            )
            .await
        })
    })?;

    Ok(result)
}

async fn evaluate_flags_async(
    persons_reader_url: String,
    persons_writer_url: String,
    non_persons_reader_url: String,
    non_persons_writer_url: String,
    team_id: i32,
    project_id: i64,
    distinct_id: String,
    feature_flags_json: String,
    groups_map: Option<HashMap<String, Value>>,
    person_props: Option<HashMap<String, Value>>,
    group_props: Option<HashMap<String, HashMap<String, Value>>>,
    hash_key_override: Option<String>,
    flag_keys: Option<Vec<String>>,
) -> PyResult<PyObject> {
    // Parse feature flags from JSON
    let feature_flags: FeatureFlagList =
        serde_json::from_str(&feature_flags_json).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                "Failed to parse feature flags JSON: {}",
                e
            ))
        })?;

    // Create database pools
    // Using reasonable default of 10 max connections per pool
    let max_connections = 10;

    let persons_reader = Arc::new(
        get_pool(&persons_reader_url, max_connections)
            .await
            .map_err(|e| {
                PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                    "Failed to create persons reader pool: {}",
                    e
                ))
            })?,
    );

    let persons_writer = Arc::new(
        get_pool(&persons_writer_url, max_connections)
            .await
            .map_err(|e| {
                PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                    "Failed to create persons writer pool: {}",
                    e
                ))
            })?,
    );

    let non_persons_reader = Arc::new(
        get_pool(&non_persons_reader_url, max_connections)
            .await
            .map_err(|e| {
                PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                    "Failed to create non-persons reader pool: {}",
                    e
                ))
            })?,
    );

    let non_persons_writer = Arc::new(
        get_pool(&non_persons_writer_url, max_connections)
            .await
            .map_err(|e| {
                PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                    "Failed to create non-persons writer pool: {}",
                    e
                ))
            })?,
    );

    // Create PostgresRouter
    let router = PostgresRouter::new(
        persons_reader.clone(),
        persons_writer,
        non_persons_reader.clone(),
        non_persons_writer,
    );

    // Create CohortCacheManager
    let cohort_cache = Arc::new(CohortCacheManager::new(
        non_persons_reader,
        None, // No custom max entries
        None, // No custom TTL
    ));

    // Create GroupTypeMappingCache
    let group_type_mapping_cache = GroupTypeMappingCache::new(project_id);

    // Create FeatureFlagMatcher
    let mut matcher = FeatureFlagMatcher::new(
        distinct_id,
        team_id,
        project_id,
        router,
        cohort_cache,
        Some(group_type_mapping_cache),
        groups_map,
    );

    // Generate request ID
    let request_id = Uuid::new_v4();

    // Evaluate flags
    let response = matcher
        .evaluate_all_feature_flags(
            feature_flags,
            person_props,
            group_props,
            hash_key_override,
            request_id,
            flag_keys,
        )
        .await;

    // Convert response to Python-compatible format
    // Return tuple: (flag_values, evaluation_reasons, flag_payloads, errors, flag_details)
    Python::with_gil(|py| convert_response_to_python(py, response))
}

/// Convert PyDict to HashMap<String, Value> for groups
fn convert_pydict_to_hashmap(dict: &Bound<'_, PyDict>) -> PyResult<HashMap<String, Value>> {
    let mut map = HashMap::new();
    for (key, value) in dict {
        let key_str: String = key.extract()?;
        let value_str: String = value.extract()?;
        map.insert(key_str, Value::String(value_str));
    }
    Ok(map)
}

/// Convert PyDict to HashMap<String, Value> for property overrides
fn convert_pydict_to_value_hashmap(dict: &Bound<'_, PyDict>) -> PyResult<HashMap<String, Value>> {
    let mut map = HashMap::new();
    for (key, value) in dict {
        let key_str: String = key.extract()?;
        // Try to extract as different types
        let json_value = if let Ok(s) = value.extract::<String>() {
            Value::String(s)
        } else if let Ok(i) = value.extract::<i64>() {
            Value::Number(i.into())
        } else if let Ok(b) = value.extract::<bool>() {
            Value::Bool(b)
        } else if let Ok(f) = value.extract::<f64>() {
            serde_json::Number::from_f64(f)
                .map(Value::Number)
                .unwrap_or(Value::Null)
        } else {
            Value::Null
        };
        map.insert(key_str, json_value);
    }
    Ok(map)
}

/// Convert nested PyDict to HashMap<String, HashMap<String, Value>> for group property overrides
fn convert_pydict_to_nested_hashmap(
    dict: &Bound<'_, PyDict>,
) -> PyResult<HashMap<String, HashMap<String, Value>>> {
    let mut map = HashMap::new();
    for (key, value) in dict {
        let key_str: String = key.extract()?;
        let inner_dict: Bound<'_, PyDict> = value.extract()?;
        let inner_map = convert_pydict_to_value_hashmap(&inner_dict)?;
        map.insert(key_str, inner_map);
    }
    Ok(map)
}

/// Convert FlagsResponse to Python tuple format
fn convert_response_to_python(
    py: Python,
    response: crate::api::types::FlagsResponse,
) -> PyResult<PyObject> {
    // Create dictionaries for the return values
    let flag_values = PyDict::new_bound(py);
    let evaluation_reasons = PyDict::new_bound(py);
    let flag_payloads = PyDict::new_bound(py);
    let flag_details = PyDict::new_bound(py);

    for (key, flag_detail) in response.flags {
        // flag_values: dict[str, Union[str, bool]]
        if let Some(variant) = &flag_detail.variant {
            flag_values.set_item(&key, variant)?;
        } else {
            flag_values.set_item(&key, flag_detail.enabled)?;
        }

        // evaluation_reasons: dict[str, dict]
        let reason_dict = PyDict::new_bound(py);
        reason_dict.set_item("reason", flag_detail.reason.code.clone())?;
        reason_dict.set_item(
            "condition_index",
            flag_detail.reason.condition_index.map(|i| i as usize),
        )?;
        evaluation_reasons.set_item(&key, &reason_dict)?;

        // flag_payloads: dict[str, object]
        if let Some(payload) = &flag_detail.metadata.payload {
            let py_payload = pythonize::pythonize(py, payload).map_err(|e| {
                PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                    "Failed to convert payload: {}",
                    e
                ))
            })?;
            flag_payloads.set_item(&key, py_payload)?;
        }

        // flag_details: Optional[dict[str, FeatureFlagDetails]]
        let detail_dict = PyDict::new_bound(py);
        let match_dict = PyDict::new_bound(py);
        match_dict.set_item("match", flag_detail.enabled)?;
        match_dict.set_item("variant", flag_detail.variant.clone())?;
        match_dict.set_item("reason", flag_detail.reason.code.clone())?;
        match_dict.set_item(
            "condition_index",
            flag_detail.reason.condition_index.map(|i| i as usize),
        )?;
        if let Some(payload) = &flag_detail.metadata.payload {
            let py_payload = pythonize::pythonize(py, payload).map_err(|e| {
                PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                    "Failed to convert payload: {}",
                    e
                ))
            })?;
            match_dict.set_item("payload", py_payload)?;
        } else {
            match_dict.set_item("payload", py.None())?;
        }

        detail_dict.set_item("match", &match_dict)?;
        detail_dict.set_item("id", flag_detail.metadata.id)?;
        detail_dict.set_item("version", flag_detail.metadata.version)?;
        detail_dict.set_item("description", flag_detail.metadata.description)?;

        flag_details.set_item(&key, &detail_dict)?;
    }

    // Return tuple: (flag_values, evaluation_reasons, flag_payloads, errors, flag_details)
    Ok((
        flag_values,
        evaluation_reasons,
        flag_payloads,
        response.errors_while_computing_flags,
        flag_details,
    )
        .to_object(py))
}

/// Initialize the Python module
#[pymodule]
fn posthog_feature_flags_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(evaluate_all_feature_flags_rust, m)?)?;
    Ok(())
}
