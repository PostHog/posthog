use std::collections::HashMap;

// keep this in sync with Django posthog.taxonomy pkg values
pub const GROUP_TYPE_LIMIT: i32 = 5;

pub const DEFAULT_QUERY_LIMIT: i64 = 100;
pub const DEFAULT_QUERY_OFFSET: i64 = 0;

pub const SEARCH_TRIGGER_WORD: &str = "latest";
pub const SEARCH_SCREEN_WORD: &str = "initial";

pub const ENTERPRISE_PROP_DEFS_TABLE: &str = "ee_enterprisepropertydefinition";
pub const PROPERTY_DEFS_TABLE: &str = "posthog_propertydefinition";
pub const EVENT_PROPERTY_TABLE: &str = "posthog_eventproperty";
pub const EVENT_PROPERTY_TABLE_ALIAS: &str = "check_for_matching_event_property";

pub const PARENT_PROPERTY_TYPES: [&str; 4] = ["event", "person", "group", "session"];

pub const PROPERTY_DEFS_TABLE_COLUMNS: [&str; 6] = [
    "id",
    "project_id",
    "team_id",
    "name",
    "is_numerical",
    "property_type",
    // "type", "property_type_format", "volume_30_day", "query_usage_30_day"
];

pub const ENTERPRISE_PROP_DEFS_TABLE_COLUMNS: [&str; 7] = [
    "description",
    "verified",
    "verified_at",
    "verified_by_id",
    "updated_at",
    "updated_by_id",
    "tags",
    // "deprecated_tags",
];

// property definitions we don't want customers querying
// https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L343-L361
pub const EVENTS_HIDDEN_PROPERTY_DEFINITIONS: [&str; 14] = [
    // distinct_id is set in properties by some libraries, but not consistently, so we shouldn't allow users to filter on it
    "distinct_id",
    // used for updating properties
    "$set",
    "$set_once",
    // posthog-js used to send it on events and shouldn't have, now it confuses users
    "$initial_referrer",
    "$initial_referring_domain",
    // Group Analytics
    "$groups",
    "$group_type",
    "$group_key",
    "$group_set",
    "$group_0",
    "$group_1",
    "$group_2",
    "$group_3",
    "$group_4",
];

// refinement of the CORE_FILTER_DEFINITIONS_BY_GROUP["event_properties"] registry
// in the Django monolith. To make this cheaper to work with locally, I preprocessed the list:
// 1. dropped all records with no "label" field in the entry's value object
// 2. dropped all records with the work "deprecated" in the entry's value object (same as Django does)
// 3. lowercased all value["label"] entries eligible for capture here (Django does this on the fly)
// **IMPORTANT** we need to keep this in sync the w/Django original!! see below for more details:
// https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L326-L339
// https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/taxonomy.py#L1627-L1631
pub static PROPERTY_DEFINITION_ALIASES: [(&str, &str); 241] = [
    (
        "$last_posthog_reset",
        "timestamp of last call to `reset` in the web sdk",
    ),
    ("$copy_type", "copy type"),
    ("$selected_content", "copied content"),
    ("$set", "set person properties"),
    ("$set_once", "set person properties once"),
    ("$pageview_id", "pageview id"),
    (
        "$autocapture_disabled_server_side",
        "autocapture disabled server-side",
    ),
    (
        "$console_log_recording_enabled_server_side",
        "console log recording enabled server-side",
    ),
    (
        "$session_recording_recorder_version_server_side",
        "session recording recorder version server-side",
    ),
    ("$session_is_sampled", "whether the session is sampled"),
    ("$feature_flag_payloads", "feature flag payloads"),
    ("$capture_failed_request", "capture failed request"),
    (
        "$lib_rate_limit_remaining_tokens",
        "clientside rate limit remaining tokens",
    ),
    ("token", "token"),
    ("$sentry_exception", "sentry exception"),
    ("$sentry_exception_message", "sentry exception message"),
    ("$sentry_exception_type", "sentry exception type"),
    ("$sentry_tags", "sentry tags"),
    ("$exception_list", "exception list"),
    ("$exception_level", "exception level"),
    ("$exception_type", "exception type"),
    ("$exception_message", "exception message"),
    ("$exception_fingerprint", "exception fingerprint"),
    (
        "$exception_proposed_fingerprint",
        "exception proposed fingerprint",
    ),
    ("$exception_issue_id", "exception issue id"),
    ("$exception_source", "exception source"),
    ("$exception_lineno", "exception source line number"),
    ("$exception_colno", "exception source column number"),
    ("$exception_DOMException_code", "domexception code"),
    ("$exception_is_synthetic", "exception is synthetic"),
    ("$exception_handled", "exception was handled"),
    ("$exception_personURL", "exception person url"),
    ("$cymbal_errors", "exception processing errors"),
    ("$exception_capture_endpoint", "exception capture endpoint"),
    (
        "$exception_capture_endpoint_suffix",
        "exception capture endpoint",
    ),
    (
        "$exception_capture_enabled_server_side",
        "exception capture enabled server side",
    ),
    ("$ce_version", "$ce_version"),
    ("$anon_distinct_id", "anon distinct id"),
    ("$event_type", "event type"),
    ("$insert_id", "insert id"),
    ("$time", "$time (deprecated)"),
    ("$browser_type", "browser type"),
    ("$device_id", "device id"),
    (
        "$replay_minimum_duration",
        "replay config - minimum duration",
    ),
    ("$replay_sample_rate", "replay config - sample rate"),
    (
        "$session_recording_start_reason",
        "session recording start reason",
    ),
    (
        "$session_recording_canvas_recording",
        "session recording canvas recording",
    ),
    (
        "$session_recording_network_payload_capture",
        "session recording network payload capture",
    ),
    (
        "$configured_session_timeout_ms",
        "configured session timeout",
    ),
    ("$replay_script_config", "replay script config"),
    (
        "$session_recording_url_trigger_activated_session",
        "session recording url trigger activated session",
    ),
    (
        "$session_recording_url_trigger_status",
        "session recording url trigger status",
    ),
    ("$recording_status", "session recording status"),
    ("$geoip_city_name", "city name"),
    ("$geoip_country_name", "country name"),
    ("$geoip_country_code", "country code"),
    ("$geoip_continent_name", "continent name"),
    ("$geoip_continent_code", "continent code"),
    ("$geoip_postal_code", "postal code"),
    (
        "$geoip_postal_code_confidence",
        "postal code identification confidence score",
    ),
    ("$geoip_latitude", "latitude"),
    ("$geoip_longitude", "longitude"),
    ("$geoip_time_zone", "timezone"),
    ("$geoip_subdivision_1_name", "subdivision 1 name"),
    ("$geoip_subdivision_1_code", "subdivision 1 code"),
    ("$geoip_subdivision_2_name", "subdivision 2 name"),
    ("$geoip_subdivision_2_code", "subdivision 2 code"),
    (
        "$geoip_subdivision_2_confidence",
        "subdivision 2 identification confidence score",
    ),
    ("$geoip_subdivision_3_name", "subdivision 3 name"),
    ("$geoip_subdivision_3_code", "subdivision 3 code"),
    ("$geoip_disable", "geoip disabled"),
    ("$el_text", "element text"),
    ("$app_build", "app build"),
    ("$app_name", "app name"),
    ("$app_namespace", "app namespace"),
    ("$app_version", "app version"),
    ("$device_manufacturer", "device manufacturer"),
    ("$device_name", "device name"),
    ("$locale", "locale"),
    ("$os_name", "os name"),
    ("$os_version", "os version"),
    ("$timezone", "timezone"),
    ("$touch_x", "touch x"),
    ("$touch_y", "touch y"),
    ("$plugins_succeeded", "plugins succeeded"),
    ("$groups", "groups"),
    ("$group_0", "group 1"),
    ("$group_1", "group 2"),
    ("$group_2", "group 3"),
    ("$group_3", "group 4"),
    ("$group_4", "group 5"),
    ("$group_set", "group set"),
    ("$group_key", "group key"),
    ("$group_type", "group type"),
    ("$window_id", "window id"),
    ("$session_id", "session id"),
    ("$plugins_failed", "plugins failed"),
    ("$plugins_deferred", "plugins deferred"),
    ("$$plugin_metrics", "plugin metric"),
    ("$creator_event_uuid", "creator event id"),
    ("utm_source", "utm source"),
    ("$initial_utm_source", "initial utm source"),
    ("utm_medium", "utm medium"),
    ("utm_campaign", "utm campaign"),
    ("utm_name", "utm name"),
    ("utm_content", "utm content"),
    ("utm_term", "utm term"),
    ("$performance_page_loaded", "page loaded"),
    ("$performance_raw", "browser performance"),
    ("$had_persisted_distinct_id", "$had_persisted_distinct_id"),
    ("$sentry_event_id", "sentry event id"),
    ("$timestamp", "timestamp (deprecated)"),
    ("$sent_at", "sent at"),
    ("$browser", "browser"),
    ("$os", "os"),
    ("$browser_language", "browser language"),
    ("$browser_language_prefix", "browser language prefix"),
    ("$current_url", "current url"),
    ("$browser_version", "browser version"),
    ("$raw_user_agent", "raw user agent"),
    ("$user_agent", "raw user agent"),
    ("$screen_height", "screen height"),
    ("$screen_width", "screen width"),
    ("$screen_name", "screen name"),
    ("$viewport_height", "viewport height"),
    ("$viewport_width", "viewport width"),
    ("$lib", "library"),
    ("$lib_custom_api_host", "library custom api host"),
    ("$lib_version", "library version"),
    ("$lib_version__major", "library version (major)"),
    ("$lib_version__minor", "library version (minor)"),
    ("$lib_version__patch", "library version (patch)"),
    ("$referrer", "referrer url"),
    ("$referring_domain", "referring domain"),
    ("$user_id", "user id"),
    ("$ip", "ip address"),
    ("$host", "host"),
    ("$pathname", "path name"),
    ("$search_engine", "search engine"),
    ("$active_feature_flags", "active feature flags"),
    ("$enabled_feature_flags", "enabled feature flags"),
    ("$feature_flag_response", "feature flag response"),
    ("$feature_flag_payload", "feature flag response payload"),
    ("$feature_flag", "feature flag"),
    ("$survey_response", "survey response"),
    ("$survey_name", "survey name"),
    ("$survey_questions", "survey questions"),
    ("$survey_id", "survey id"),
    ("$survey_iteration", "survey iteration number"),
    (
        "$survey_iteration_start_date",
        "survey iteration start date",
    ),
    ("$device", "device"),
    ("$sentry_url", "sentry url"),
    ("$device_type", "device type"),
    ("$screen_density", "screen density"),
    ("$device_model", "device model"),
    ("$network_wifi", "network wifi"),
    ("$network_bluetooth", "network bluetooth"),
    ("$network_cellular", "network cellular"),
    ("$client_session_initial_referring_host", "referrer host"),
    ("$client_session_initial_pathname", "initial path"),
    ("$client_session_initial_utm_source", "initial utm source"),
    (
        "$client_session_initial_utm_campaign",
        "initial utm campaign",
    ),
    ("$client_session_initial_utm_medium", "initial utm medium"),
    ("$client_session_initial_utm_content", "initial utm source"),
    ("$client_session_initial_utm_term", "initial utm source"),
    ("$network_carrier", "network carrier"),
    ("from_background", "from background"),
    ("url", "url"),
    ("referring_application", "referrer application"),
    ("version", "app version"),
    ("previous_version", "app previous version"),
    ("build", "app build"),
    ("previous_build", "app previous build"),
    ("gclid", "gclid"),
    ("rdt_cid", "rdt_cid"),
    ("irclid", "irclid"),
    ("_kx", "_kx"),
    ("gad_source", "gad_source"),
    ("gclsrc", "gclsrc"),
    ("dclid", "dclid"),
    ("gbraid", "gbraid"),
    ("wbraid", "wbraid"),
    ("fbclid", "fbclid"),
    ("msclkid", "msclkid"),
    ("twclid", "twclid"),
    ("li_fat_id", "li_fat_id"),
    ("mc_cid", "mc_cid"),
    ("igshid", "igshid"),
    ("ttclid", "ttclid"),
    ("$is_identified", "is identified"),
    ("$initial_person_info", "initial person info"),
    (
        "$web_vitals_enabled_server_side",
        "web vitals enabled server side",
    ),
    (
        "$web_vitals_FCP_event",
        "web vitals fcp measure event details",
    ),
    ("$web_vitals_FCP_value", "web vitals fcp value"),
    (
        "$web_vitals_LCP_event",
        "web vitals lcp measure event details",
    ),
    ("$web_vitals_LCP_value", "web vitals lcp value"),
    (
        "$web_vitals_INP_event",
        "web vitals inp measure event details",
    ),
    ("$web_vitals_INP_value", "web vitals inp value"),
    (
        "$web_vitals_CLS_event",
        "web vitals cls measure event details",
    ),
    ("$web_vitals_CLS_value", "web vitals cls value"),
    ("$web_vitals_allowed_metrics", "web vitals allowed metrics"),
    (
        "$prev_pageview_last_scroll",
        "previous pageview last scroll",
    ),
    ("$prev_pageview_id", "previous pageview id"),
    (
        "$prev_pageview_last_scroll_percentage",
        "previous pageview last scroll percentage",
    ),
    ("$prev_pageview_max_scroll", "previous pageview max scroll"),
    (
        "$prev_pageview_max_scroll_percentage",
        "previous pageview max scroll percentage",
    ),
    (
        "$prev_pageview_last_content",
        "previous pageview last content",
    ),
    (
        "$prev_pageview_last_content_percentage",
        "previous pageview last content percentage",
    ),
    (
        "$prev_pageview_max_content",
        "previous pageview max content",
    ),
    (
        "$prev_pageview_max_content_percentage",
        "previous pageview max content percentage",
    ),
    ("$prev_pageview_pathname", "previous pageview pathname"),
    ("$prev_pageview_duration", "previous pageview duration"),
    ("$surveys_activated", "surveys activated"),
    ("$process_person_profile", "person profile processing flag"),
    (
        "$dead_clicks_enabled_server_side",
        "dead clicks enabled server side",
    ),
    (
        "$dead_click_scroll_delay_ms",
        "dead click scroll delay in milliseconds",
    ),
    (
        "$dead_click_mutation_delay_ms",
        "dead click mutation delay in milliseconds",
    ),
    (
        "$dead_click_absolute_delay_ms",
        "dead click absolute delay in milliseconds",
    ),
    (
        "$dead_click_selection_changed_delay_ms",
        "dead click selection changed delay in milliseconds",
    ),
    (
        "$dead_click_last_mutation_timestamp",
        "dead click last mutation timestamp",
    ),
    ("$dead_click_event_timestamp", "dead click event timestamp"),
    ("$dead_click_scroll_timeout", "dead click scroll timeout"),
    (
        "$dead_click_mutation_timeout",
        "dead click mutation timeout",
    ),
    (
        "$dead_click_absolute_timeout",
        "dead click absolute timeout",
    ),
    (
        "$dead_click_selection_changed_timeout",
        "dead click selection changed timeout",
    ),
    ("$ai_base_url", "ai base url (llm)"),
    ("$ai_http_status", "ai http status (llm)"),
    ("$ai_input", "ai input (llm)"),
    ("$ai_input_tokens", "ai input tokens (llm)"),
    ("$ai_output", "ai output (llm)"),
    ("$ai_output_tokens", "ai output tokens (llm)"),
    ("$ai_latency", "ai latency (llm)"),
    ("$ai_model", "ai model (llm)"),
    ("$ai_model_parameters", "ai model parameters (llm)"),
    ("$ai_provider", "ai provider (llm)"),
    ("$ai_trace_id", "ai trace id (llm)"),
    ("$ai_metric_name", "ai metric name (llm)"),
    ("$ai_metric_value", "ai metric value (llm)"),
    ("$ai_feedback_text", "ai feedback text (llm)"),
    ("$ai_parent_id", "ai parent id (llm)"),
    ("$ai_span_id", "ai span id (llm)"),
];

// very expensive mapping we cache only once per property-defs-rs service initialization.
// used for search term refinement in the prop defs query builder
pub fn extract_aliases() -> HashMap<&'static str, &'static str> {
    HashMap::<&'static str, &'static str>::from(PROPERTY_DEFINITION_ALIASES)
}
