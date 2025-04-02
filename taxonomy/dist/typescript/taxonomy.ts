export const CORE_FILTER_DEFINITIONS_BY_GROUP = {
    events: {
        'All Events': {
            label: 'All events',
            description: 'This is a wildcard that matches all events.',
        },
        $pageview: {
            label: 'Pageview',
            description: 'When a user loads (or reloads) a page.',
        },
        $pageleave: {
            label: 'Pageleave',
            description: 'When a user leaves a page.',
            ignored_in_assistant: true,
        },
        $autocapture: {
            label: 'Autocapture',
            description: 'User interactions that were automatically captured.',
            examples: ['clicked button'],
            ignored_in_assistant: true,
        },
        $$heatmap: {
            label: 'Heatmap',
            description: 'Heatmap events carry heatmap data to the backend, they do not contribute to event counts.',
            ignored_in_assistant: true,
        },
        $copy_autocapture: {
            label: 'Clipboard autocapture',
            description: 'Selected text automatically captured when a user copies or cuts.',
            ignored_in_assistant: true,
        },
        $screen: {
            label: 'Screen',
            description: 'When a user loads a screen in a mobile app.',
        },
        $set: {
            label: 'Set person properties',
            description: 'Setting person properties. Sent as `$set`',
            ignored_in_assistant: true,
        },
        $opt_in: {
            label: 'Opt In',
            description: 'When a user opts into analytics.',
            ignored_in_assistant: true,
        },
        $feature_flag_called: {
            label: 'Feature Flag Called',
            description: 'The feature flag that was called.\n\nWarning! This only works in combination with the $feature_flag event. If you want to filter other events, try "Active Feature Flags".',
            examples: ['beta-feature'],
            ignored_in_assistant: true,
        },
        $feature_view: {
            label: 'Feature View',
            description: 'When a user views a feature.',
            ignored_in_assistant: true,
        },
        $feature_interaction: {
            label: 'Feature Interaction',
            description: 'When a user interacts with a feature.',
            ignored_in_assistant: true,
        },
        $feature_enrollment_update: {
            label: 'Feature Enrollment',
            description: 'When a user opts in or out of a beta feature. This event is specific to the PostHog Early Access Features product, and is only relevant if the project is using this product.',
        },
        $capture_metrics: {
            label: 'Capture Metrics',
            description: 'Metrics captured with values pertaining to your systems at a specific point in time',
            ignored_in_assistant: true,
        },
        $identify: {
            label: 'Identify',
            description: 'Identifies an anonymous user. The event shows how many users used an account, so do not use it for active users metrics because a user may skip identification.',
        },
        $create_alias: {
            label: 'Alias',
            description: 'An alias ID has been added to a user',
            ignored_in_assistant: true,
        },
        $merge_dangerously: {
            label: 'Merge',
            description: 'An alias ID has been added to a user',
            ignored_in_assistant: true,
        },
        $groupidentify: {
            label: 'Group Identify',
            description: 'A group has been identified with properties',
            ignored_in_assistant: true,
        },
        $rageclick: {
            label: 'Rageclick',
            description: 'A user has rapidly and repeatedly clicked in a single place',
        },
        $dead_click: {
            label: 'Dead click',
            description: 'A user has clicked on something that is probably not clickable',
        },
        $exception: {
            label: 'Exception',
            description: 'An unexpected error or unhandled exception in your application',
        },
        $web_vitals: {
            label: 'Web vitals',
            description: 'Automatically captured web vitals data',
        },
        $ai_generation: {
            label: 'AI Generation (LLM)',
            description: 'A call to an LLM model. Contains the input prompt, output, model used and costs.',
        },
        $ai_metric: {
            label: 'AI Metric (LLM)',
            description: 'An evaluation metric for a trace of a generative AI model (LLM). Contains the trace ID, metric name, and metric value.',
        },
        $ai_feedback: {
            label: 'AI Feedback (LLM)',
            description: 'User-provided feedback for a trace of a generative AI model (LLM).',
        },
        $ai_trace: {
            label: 'AI Trace (LLM)',
            description: 'A generative AI trace. Usually a trace tracks a single user interaction and contains one or more AI generation calls',
        },
        $ai_span: {
            label: 'AI Span (LLM)',
            description: 'A generative AI span. Usually a span tracks a unit of work for a trace of generative AI models (LLMs)',
        },
        $ai_embedding: {
            label: 'AI Embedding (LLM)',
            description: 'A call to an embedding model',
        },
        'Application Opened': {
            label: 'Application Opened',
            description: 'When a user opens the mobile app either for the first time or from the foreground.',
        },
        'Application Backgrounded': {
            label: 'Application Backgrounded',
            description: 'When a user puts the mobile app in the background.',
        },
        'Application Updated': {
            label: 'Application Updated',
            description: 'When a user upgrades the mobile app.',
        },
        'Application Installed': {
            label: 'Application Installed',
            description: 'When a user installs the mobile app.',
        },
        'Application Became Active': {
            label: 'Application Became Active',
            description: 'When a user puts the mobile app in the foreground.',
        },
        'Deep Link Opened': {
            label: 'Deep Link Opened',
            description: 'When a user opens the mobile app via a deep link.',
        },
    },
    elements: {
        tag_name: {
            label: 'Tag Name',
            description: 'HTML tag name of the element which you want to filter.',
            examples: ['a', 'button', 'input'],
        },
        selector: {
            label: 'CSS Selector',
            description: 'Select any element by CSS selector.',
            examples: ['div > a', 'table td:nth-child(2)', '.my-class'],
        },
        text: {
            label: 'Text',
            description: 'Filter on the inner text of the HTML element.',
        },
        href: {
            label: 'Target (href)',
            description: 'Filter on the href attribute of the element.',
            examples: ['https://posthog.com/about'],
        },
    },
    metadata: {
        distinct_id: {
            label: 'Distinct ID',
            description: 'The current distinct ID of the user',
            examples: ['16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767'],
        },
        timestamp: {
            label: 'Timestamp',
            description: 'Time the event happened.',
            examples: ['2023-05-20T15:30:00Z'],
            system: true,
            ignored_in_assistant: true,
        },
        event: {
            label: 'Event',
            description: 'The name of the event.',
            examples: ['$pageview'],
            system: true,
            ignored_in_assistant: true,
        },
    },
    event_properties: {
        $python_runtime: {
            label: 'Python Runtime',
            description: 'The Python runtime that was used to capture the event.',
            examples: ['CPython'],
            system: true,
            ignored_in_assistant: true,
        },
        $python_version: {
            label: 'Python Version',
            description: 'The Python version that was used to capture the event.',
            examples: ['3.11.5'],
            system: true,
            ignored_in_assistant: true,
        },
        $sdk_debug_replay_internal_buffer_length: {
            label: 'Replay internal buffer length',
            description: 'Useful for debugging. The internal buffer length for replay.',
            examples: ['100'],
            system: true,
            ignored_in_assistant: true,
        },
        $sdk_debug_replay_internal_buffer_size: {
            label: 'Replay internal buffer size',
            description: 'Useful for debugging. The internal buffer size for replay.',
            examples: ['100'],
            system: true,
            ignored_in_assistant: true,
        },
        $sdk_debug_retry_queue_size: {
            label: 'Retry queue size',
            description: 'Useful for debugging. The size of the retry queue.',
            examples: ['100'],
            system: true,
            ignored_in_assistant: true,
        },
        $last_posthog_reset: {
            label: 'Timestamp of last call to `Reset` in the web sdk',
            description: 'The timestamp of the last call to `Reset` in the web SDK. This can be useful for debugging.',
            ignored_in_assistant: true,
            system: true,
        },
        $copy_type: {
            label: 'Copy Type',
            description: 'Type of copy event.',
            examples: ['copy', 'cut'],
            ignored_in_assistant: true,
        },
        $selected_content: {
            label: 'Copied content',
            description: 'The content that was selected when the user copied or cut.',
            ignored_in_assistant: true,
        },
        $set: {
            label: 'Set person properties',
            description: 'Person properties to be set. Sent as `$set`',
            ignored_in_assistant: true,
        },
        $set_once: {
            label: 'Set person properties once',
            description: 'Person properties to be set if not set already (i.e. first-touch). Sent as `$set_once`',
            ignored_in_assistant: true,
        },
        $pageview_id: {
            label: 'Pageview ID',
            description: 'PostHog\'s internal ID for matching events to a pageview.',
            system: true,
            ignored_in_assistant: true,
        },
        $autocapture_disabled_server_side: {
            label: 'Autocapture Disabled Server-Side',
            description: 'If autocapture has been disabled server-side.',
            system: true,
            ignored_in_assistant: true,
        },
        $console_log_recording_enabled_server_side: {
            label: 'Console Log Recording Enabled Server-Side',
            description: 'If console log recording has been enabled server-side.',
            system: true,
            ignored_in_assistant: true,
        },
        $session_recording_recorder_version_server_side: {
            label: 'Session Recording Recorder Version Server-Side',
            description: 'The version of the session recording recorder that is enabled server-side.',
            examples: ['v2'],
            system: true,
            ignored_in_assistant: true,
        },
        $session_is_sampled: {
            label: 'Whether the session is sampled',
            description: 'Whether the session is sampled for session recording.',
            examples: ['true', 'false'],
            system: true,
            ignored_in_assistant: true,
        },
        $feature_flag_payloads: {
            label: 'Feature Flag Payloads',
            description: 'Feature flag payloads active in the environment.',
            ignored_in_assistant: true,
        },
        $capture_failed_request: {
            label: 'Capture Failed Request',
            description: '',
            ignored_in_assistant: true,
        },
        $lib_rate_limit_remaining_tokens: {
            label: 'Clientside rate limit remaining tokens',
            description: 'Remaining rate limit tokens for the posthog-js library client-side rate limiting implementation.',
            examples: ['100'],
            ignored_in_assistant: true,
        },
        token: {
            label: 'Token',
            description: 'Token used for authentication.',
            examples: ['ph_abcdefg'],
            ignored_in_assistant: true,
        },
        $sentry_exception: {
            label: 'Sentry exception',
            description: 'Raw Sentry exception data',
            system: true,
        },
        $sentry_exception_message: {
            label: 'Sentry exception message',
        },
        $sentry_exception_type: {
            label: 'Sentry exception type',
            description: 'Class name of the exception object',
        },
        $sentry_tags: {
            label: 'Sentry tags',
            description: 'Tags sent to Sentry along with the exception',
        },
        $exception_list: {
            label: 'Exception list',
            description: 'List of one or more associated exceptions',
            system: true,
        },
        $exception_level: {
            label: 'Exception level',
            description: 'Exception categorized by severity',
            examples: ['error'],
        },
        $exception_type: {
            label: 'Exception type',
            description: 'Exception categorized into types',
            examples: ['Error'],
        },
        $exception_message: {
            label: 'Exception message',
            description: 'The message detected on the error',
        },
        $exception_fingerprint: {
            label: 'Exception fingerprint',
            description: 'A fingerprint used to group issues, can be set clientside',
        },
        $exception_proposed_fingerprint: {
            label: 'Exception proposed fingerprint',
            description: 'The fingerprint used to group issues. Auto generated unless provided clientside',
        },
        $exception_issue_id: {
            label: 'Exception issue ID',
            description: 'The id of the issue the fingerprint was associated with at ingest time',
        },
        $exception_source: {
            label: 'Exception source',
            description: 'The source of the exception',
            examples: ['JS file'],
        },
        $exception_lineno: {
            label: 'Exception source line number',
            description: 'Which line in the exception source that caused the exception',
        },
        $exception_colno: {
            label: 'Exception source column number',
            description: 'Which column of the line in the exception source that caused the exception',
        },
        $exception_DOMException_code: {
            label: 'DOMException code',
            description: 'If a DOMException was thrown, it also has a DOMException code',
        },
        $exception_is_synthetic: {
            label: 'Exception is synthetic',
            description: 'Whether this was detected as a synthetic exception',
        },
        $exception_stack_trace_raw: {
            label: 'Exception raw stack trace',
            description: 'The exceptions stack trace, as a string',
        },
        $exception_handled: {
            label: 'Exception was handled',
            description: 'Whether this was a handled or unhandled exception',
        },
        $exception_personURL: {
            label: 'Exception person URL',
            description: 'The PostHog person that experienced the exception',
        },
        $cymbal_errors: {
            label: 'Exception processing errors',
            description: 'Errors encountered while trying to process exceptions',
            system: true,
        },
        $exception_capture_endpoint: {
            label: 'Exception capture endpoint',
            description: 'Endpoint used by posthog-js exception autocapture.',
            examples: ['/e/'],
        },
        $exception_capture_endpoint_suffix: {
            label: 'Exception capture endpoint',
            description: 'Endpoint used by posthog-js exception autocapture.',
            examples: ['/e/'],
        },
        $exception_capture_enabled_server_side: {
            label: 'Exception capture enabled server side',
            description: 'Whether exception autocapture was enabled in remote config.',
        },
        $ce_version: {
            label: '$ce_version',
            description: '',
            system: true,
        },
        $anon_distinct_id: {
            label: 'Anon Distinct ID',
            description: 'If the user was previously anonymous, their anonymous ID will be set here.',
            examples: ['16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767'],
            system: true,
        },
        $event_type: {
            label: 'Event Type',
            description: 'When the event is an $autocapture event, this specifies what the action was against the element.',
            examples: ['click', 'submit', 'change'],
        },
        $insert_id: {
            label: 'Insert ID',
            description: 'Unique insert ID for the event.',
            system: true,
        },
        $time: {
            label: '$time (deprecated)',
            description: 'Use the HogQL field `timestamp` instead. This field was previously set on some client side events.',
            system: true,
            examples: ['1681211521.345'],
        },
        $browser_type: {
            label: 'Browser Type',
            description: 'This is only added when posthog-js config.opt_out_useragent_filter is true.',
            examples: ['browser', 'bot'],
        },
        $device_id: {
            label: 'Device ID',
            description: 'Unique ID for that device, consistent even if users are logging in/out.',
            examples: ['16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767'],
            system: true,
        },
        $replay_minimum_duration: {
            label: 'Replay config - minimum duration',
            description: 'Config for minimum duration before emitting a session recording.',
            examples: ['1000'],
            system: true,
        },
        $replay_sample_rate: {
            label: 'Replay config - sample rate',
            description: 'Config for sampling rate of session recordings.',
            examples: ['0.1'],
            system: true,
        },
        $session_recording_start_reason: {
            label: 'Session recording start reason',
            description: 'Reason for starting the session recording. Useful for e.g. if you have sampling enabled and want to see on batch exported events which sessions have recordings available.',
            examples: ['sampling_override', 'recording_initialized', 'linked_flag_match'],
            system: true,
        },
        $session_recording_canvas_recording: {
            label: 'Session recording canvas recording',
            description: 'Session recording canvas capture config.',
            examples: ['{"enabled": false}'],
            system: true,
        },
        $session_recording_network_payload_capture: {
            label: 'Session recording network payload capture',
            description: 'Session recording network payload capture config.',
            examples: ['{"recordHeaders": false}'],
            system: true,
        },
        $configured_session_timeout_ms: {
            label: 'Configured session timeout',
            description: 'Configured session timeout in milliseconds.',
            examples: ['1800000'],
            system: true,
        },
        $replay_script_config: {
            label: 'Replay script config',
            description: 'Sets an alternative recorder script for the web sdk.',
            examples: ['{"script": "recorder-next""}'],
            system: true,
        },
        $session_recording_url_trigger_activated_session: {
            label: 'Session recording URL trigger activated session',
            description: 'Session recording URL trigger activated session config. Used by posthog-js to track URL activation of session replay.',
            system: true,
        },
        $session_recording_url_trigger_status: {
            label: 'Session recording URL trigger status',
            description: 'Session recording URL trigger status. Used by posthog-js to track URL activation of session replay.',
            system: true,
        },
        $recording_status: {
            label: 'Session recording status',
            description: 'The status of session recording at the time the event was captured',
            system: true,
        },
        $geoip_city_name: {
            label: 'City Name',
            description: 'Name of the city matched to this event\'s IP address.',
            examples: ['Sydney', 'Chennai', 'Brooklyn'],
        },
        $geoip_country_name: {
            label: 'Country Name',
            description: 'Name of the country matched to this event\'s IP address.',
            examples: ['Australia', 'India', 'United States'],
        },
        $geoip_country_code: {
            label: 'Country Code',
            description: 'Code of the country matched to this event\'s IP address.',
            examples: ['AU', 'IN', 'US'],
        },
        $geoip_continent_name: {
            label: 'Continent Name',
            description: 'Name of the continent matched to this event\'s IP address.',
            examples: ['Oceania', 'Asia', 'North America'],
        },
        $geoip_continent_code: {
            label: 'Continent Code',
            description: 'Code of the continent matched to this event\'s IP address.',
            examples: ['OC', 'AS', 'NA'],
        },
        $geoip_postal_code: {
            label: 'Postal Code',
            description: 'Approximated postal code matched to this event\'s IP address.',
            examples: ['2000', '600004', '11211'],
        },
        $geoip_postal_code_confidence: {
            label: 'Postal Code identification confidence score',
            description: 'If provided by the licensed geoip database',
            examples: ['null', '0.1'],
            system: true,
            ignored_in_assistant: true,
        },
        $geoip_latitude: {
            label: 'Latitude',
            description: 'Approximated latitude matched to this event\'s IP address.',
            examples: ['-33.8591', '13.1337', '40.7'],
        },
        $geoip_longitude: {
            label: 'Longitude',
            description: 'Approximated longitude matched to this event\'s IP address.',
            examples: ['151.2', '80.8008', '-73.9'],
        },
        $geoip_time_zone: {
            label: 'Timezone',
            description: 'Timezone matched to this event\'s IP address.',
            examples: ['Australia/Sydney', 'Asia/Kolkata', 'America/New_York'],
        },
        $geoip_subdivision_1_name: {
            label: 'Subdivision 1 Name',
            description: 'Name of the subdivision matched to this event\'s IP address.',
            examples: ['New South Wales', 'Tamil Nadu', 'New York'],
        },
        $geoip_subdivision_1_code: {
            label: 'Subdivision 1 Code',
            description: 'Code of the subdivision matched to this event\'s IP address.',
            examples: ['NSW', 'TN', 'NY'],
        },
        $geoip_subdivision_2_name: {
            label: 'Subdivision 2 Name',
            description: 'Name of the second subdivision matched to this event\'s IP address.',
        },
        $geoip_subdivision_2_code: {
            label: 'Subdivision 2 Code',
            description: 'Code of the second subdivision matched to this event\'s IP address.',
        },
        $geoip_subdivision_2_confidence: {
            label: 'Subdivision 2 identification confidence score',
            description: 'If provided by the licensed geoip database',
            examples: ['null', '0.1'],
            ignored_in_assistant: true,
        },
        $geoip_subdivision_3_name: {
            label: 'Subdivision 3 Name',
            description: 'Name of the third subdivision matched to this event\'s IP address.',
        },
        $geoip_subdivision_3_code: {
            label: 'Subdivision 3 Code',
            description: 'Code of the third subdivision matched to this event\'s IP address.',
        },
        $geoip_disable: {
            label: 'GeoIP Disabled',
            description: 'Whether to skip GeoIP processing for the event.',
        },
        $el_text: {
            label: 'Element Text',
            description: 'The text of the element that was clicked. Only sent with Autocapture events.',
            examples: ['Click here!'],
        },
        $app_build: {
            label: 'App Build',
            description: 'The build number for the app.',
        },
        $app_name: {
            label: 'App Name',
            description: 'The name of the app.',
        },
        $app_namespace: {
            label: 'App Namespace',
            description: 'The namespace of the app as identified in the app store.',
            examples: ['com.posthog.app'],
        },
        $app_version: {
            label: 'App Version',
            description: 'The version of the app.',
        },
        $device_manufacturer: {
            label: 'Device Manufacturer',
            description: 'The manufacturer of the device',
            examples: ['Apple', 'Samsung'],
        },
        $device_name: {
            label: 'Device Name',
            description: 'Name of the device',
            examples: ['iPhone 12 Pro', 'Samsung Galaxy 10'],
        },
        $locale: {
            label: 'Locale',
            description: 'The locale of the device',
            examples: ['en-US', 'de-DE'],
        },
        $os_name: {
            label: 'OS Name',
            description: 'The Operating System name',
            examples: ['iOS', 'Android'],
        },
        $os_version: {
            label: 'OS Version',
            description: 'The Operating System version.',
            examples: ['15.5'],
        },
        $timezone: {
            label: 'Timezone',
            description: 'The timezone as reported by the device',
        },
        $touch_x: {
            label: 'Touch X',
            description: 'The location of a Touch event on the X axis',
        },
        $touch_y: {
            label: 'Touch Y',
            description: 'The location of a Touch event on the Y axis',
        },
        $plugins_succeeded: {
            label: 'Plugins Succeeded',
            description: 'Plugins that successfully processed the event, e.g. edited properties (plugin method processEvent).',
        },
        $groups: {
            label: 'Groups',
            description: 'Relevant groups',
        },
        $group_0: {
            label: 'Group 1',
            system: true,
        },
        $group_1: {
            label: 'Group 2',
            system: true,
        },
        $group_2: {
            label: 'Group 3',
            system: true,
        },
        $group_3: {
            label: 'Group 4',
            system: true,
        },
        $group_4: {
            label: 'Group 5',
            system: true,
        },
        $group_set: {
            label: 'Group Set',
            description: 'Group properties to be set',
        },
        $group_key: {
            label: 'Group Key',
            description: 'Specified group key',
        },
        $group_type: {
            label: 'Group Type',
            description: 'Specified group type',
        },
        $window_id: {
            label: 'Window ID',
            description: 'Unique window ID for session recording disambiguation',
            system: true,
        },
        $session_id: {
            label: 'Session ID',
            description: 'Unique session ID for session recording disambiguation',
            system: true,
        },
        $plugins_failed: {
            label: 'Plugins Failed',
            description: 'Plugins that failed to process the event (plugin method processEvent).',
        },
        $plugins_deferred: {
            label: 'Plugins Deferred',
            description: 'Plugins to which the event was handed off post-ingestion, e.g. for export (plugin method onEvent).',
        },
        $$plugin_metrics: {
            label: 'Plugin Metric',
            description: 'Performance metrics for a given plugin.',
        },
        $creator_event_uuid: {
            label: 'Creator Event ID',
            description: 'Unique ID for the event, which created this person.',
            examples: ['16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767'],
        },
        utm_source: {
            label: 'UTM Source',
            description: 'UTM source tag.',
            examples: ['Google', 'Bing', 'Twitter', 'Facebook'],
        },
        $initial_utm_source: {
            label: 'Initial UTM Source',
            description: 'UTM source tag.',
            examples: ['Google', 'Bing', 'Twitter', 'Facebook'],
        },
        utm_medium: {
            label: 'UTM Medium',
            description: 'UTM medium tag.',
            examples: ['Social', 'Organic', 'Paid', 'Email'],
        },
        utm_campaign: {
            label: 'UTM Campaign',
            description: 'UTM campaign tag.',
            examples: ['feature launch', 'discount'],
        },
        utm_name: {
            label: 'UTM Name',
            description: 'UTM campaign tag, sent via Segment.',
            examples: ['feature launch', 'discount'],
        },
        utm_content: {
            label: 'UTM Content',
            description: 'UTM content tag.',
            examples: ['bottom link', 'second button'],
        },
        utm_term: {
            label: 'UTM Term',
            description: 'UTM term tag.',
            examples: ['free goodies'],
        },
        $performance_page_loaded: {
            label: 'Page Loaded',
            description: 'The time taken until the browser\'s page load event in milliseconds.',
        },
        $performance_raw: {
            label: 'Browser Performance',
            description: 'The browser performance entries for navigation (the page), paint, and resources. That were available when the page view event fired',
            system: true,
        },
        $had_persisted_distinct_id: {
            label: '$had_persisted_distinct_id',
            description: '',
            system: true,
        },
        $sentry_event_id: {
            label: 'Sentry Event ID',
            description: 'This is the Sentry key for an event.',
            examples: ['byroc2ar9ee4ijqp'],
            system: true,
        },
        $timestamp: {
            label: 'Timestamp (deprecated)',
            description: 'Use the HogQL field `timestamp` instead. This field was previously set on some client side events.',
            examples: ['2023-05-20T15:30:00Z'],
            system: true,
        },
        $sent_at: {
            label: 'Sent At',
            description: 'Time the event was sent to PostHog. Used for correcting the event timestamp when the device clock is off.',
            examples: ['2023-05-20T15:31:00Z'],
        },
        $browser: {
            label: 'Browser',
            description: 'Name of the browser the user has used.',
            examples: ['Chrome', 'Firefox'],
        },
        $os: {
            label: 'OS',
            description: 'The operating system of the user.',
            examples: ['Windows', 'Mac OS X'],
        },
        $browser_language: {
            label: 'Browser Language',
            description: 'Language.',
            examples: ['en', 'en-US', 'cn', 'pl-PL'],
        },
        $browser_language_prefix: {
            label: 'Browser Language Prefix',
            description: 'Language prefix.',
            examples: ['en', 'ja'],
        },
        $current_url: {
            label: 'Current URL',
            description: 'The URL visited at the time of the event.',
            examples: ['https://example.com/interesting-article?parameter=true'],
        },
        $browser_version: {
            label: 'Browser Version',
            description: 'The version of the browser that was used. Used in combination with Browser.',
            examples: ['70', '79'],
        },
        $raw_user_agent: {
            label: 'Raw User Agent',
            description: 'PostHog process information like browser, OS, and device type from the user agent string. This is the raw user agent string.',
            examples: ['Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)'],
        },
        $user_agent: {
            label: 'Raw User Agent',
            description: 'Some SDKs (like Android) send the raw user agent as $user_agent.',
            examples: ['Dalvik/2.1.0 (Linux; U; Android 11; Pixel 3 Build/RQ2A.210505.002)'],
        },
        $screen_height: {
            label: 'Screen Height',
            description: 'The height of the user\'s entire screen (in pixels).',
            examples: ['2160', '1050'],
        },
        $screen_width: {
            label: 'Screen Width',
            description: 'The width of the user\'s entire screen (in pixels).',
            examples: ['1440', '1920'],
        },
        $screen_name: {
            label: 'Screen Name',
            description: 'The name of the active screen.',
        },
        $viewport_height: {
            label: 'Viewport Height',
            description: 'The height of the user\'s actual browser window (in pixels).',
            examples: ['2094', '1031'],
        },
        $viewport_width: {
            label: 'Viewport Width',
            description: 'The width of the user\'s actual browser window (in pixels).',
            examples: ['1439', '1915'],
        },
        $lib: {
            label: 'Library',
            description: 'What library was used to send the event.',
            examples: ['web', 'posthog-ios'],
        },
        $lib_custom_api_host: {
            label: 'Library Custom API Host',
            description: 'The custom API host used to send the event.',
            examples: ['https://ph.example.com'],
        },
        $lib_version: {
            label: 'Library Version',
            description: 'Version of the library used to send the event. Used in combination with Library.',
            examples: ['1.0.3'],
        },
        $lib_version__major: {
            label: 'Library Version (Major)',
            description: 'Major version of the library used to send the event.',
            examples: [1],
        },
        $lib_version__minor: {
            label: 'Library Version (Minor)',
            description: 'Minor version of the library used to send the event.',
            examples: [0],
        },
        $lib_version__patch: {
            label: 'Library Version (Patch)',
            description: 'Patch version of the library used to send the event.',
            examples: [3],
        },
        $referrer: {
            label: 'Referrer URL',
            description: 'URL of where the user came from.',
            examples: ['https://google.com/search?q=posthog&rlz=1C...'],
        },
        $referring_domain: {
            label: 'Referring Domain',
            description: 'Domain of where the user came from.',
            examples: ['google.com', 'facebook.com'],
        },
        $user_id: {
            label: 'User ID',
            description: 'This variable will be set to the distinct ID if you\'ve called posthog.identify(\'distinct id\'). If the user is anonymous, it\'ll be empty.',
        },
        $ip: {
            label: 'IP Address',
            description: 'IP address for this user when the event was sent.',
            examples: ['203.0.113.0'],
        },
        $host: {
            label: 'Host',
            description: 'The hostname of the Current URL.',
            examples: ['example.com', 'localhost:8000'],
        },
        $pathname: {
            label: 'Path Name',
            description: 'The path of the Current URL, which means everything in the url after the domain.',
            examples: ['/pricing', '/about-us/team'],
        },
        $search_engine: {
            label: 'Search Engine',
            description: 'The search engine the user came in from (if any).',
            examples: ['Google', 'DuckDuckGo'],
        },
        $active_feature_flags: {
            label: 'Active Feature Flags',
            description: 'Keys of the feature flags that were active while this event was sent.',
            examples: ["['beta-feature']"],
        },
        $enabled_feature_flags: {
            label: 'Enabled Feature Flags',
            description: 'Keys and multivariate values of the feature flags that were active while this event was sent.',
            examples: ['{"flag": "value"}'],
        },
        $feature_flag_response: {
            label: 'Feature Flag Response',
            description: 'What the call to feature flag responded with.',
            examples: ['true', 'false'],
        },
        $feature_flag_payload: {
            label: 'Feature Flag Response Payload',
            description: 'The JSON payload that the call to feature flag responded with (if any)',
            examples: ['{"variant": "test"}'],
        },
        $feature_flag: {
            label: 'Feature Flag',
            description: 'The feature flag that was called.\n\nWarning! This only works in combination with the $feature_flag_called event. If you want to filter other events, try "Active Feature Flags".',
            examples: ['beta-feature'],
        },
        $feature_flag_reason: {
            label: 'Feature Flag Evaluation Reason',
            description: 'The reason the feature flag was matched or not matched.',
            examples: ['Matched condition set 1'],
        },
        $feature_flag_request_id: {
            label: 'Feature Flag Request ID',
            description: 'The unique identifier for the request that retrieved this feature flag result. Primarily used by PostHog support for debugging issues with feature flags.',
            examples: ['01234567-89ab-cdef-0123-456789abcdef'],
        },
        $feature_flag_version: {
            label: 'Feature Flag Version',
            description: 'The version of the feature flag that was called.',
            examples: ['3'],
        },
        $survey_response: {
            label: 'Survey Response',
            description: 'The response value for the first question in the survey.',
            examples: ['I love it!', 5, "['choice 1', 'choice 3']"],
        },
        $survey_name: {
            label: 'Survey Name',
            description: 'The name of the survey.',
            examples: ['Product Feedback for New Product', 'Home page NPS'],
        },
        $survey_questions: {
            label: 'Survey Questions',
            description: 'The questions asked in the survey.',
        },
        $survey_id: {
            label: 'Survey ID',
            description: 'The unique identifier for the survey.',
        },
        $survey_iteration: {
            label: 'Survey Iteration Number',
            description: 'The iteration number for the survey.',
        },
        $survey_iteration_start_date: {
            label: 'Survey Iteration Start Date',
            description: 'The start date for the current iteration of the survey.',
        },
        $device: {
            label: 'Device',
            description: 'The mobile device that was used.',
            examples: ['iPad', 'iPhone', 'Android'],
        },
        $sentry_url: {
            label: 'Sentry URL',
            description: 'Direct link to the exception in Sentry',
            examples: ['https://sentry.io/...'],
        },
        $device_type: {
            label: 'Device Type',
            description: 'The type of device that was used.',
            examples: ['Mobile', 'Tablet', 'Desktop'],
        },
        $screen_density: {
            label: 'Screen density',
            description: 'The logical density of the display. This is a scaling factor for the Density Independent Pixel unit, where one DIP is one pixel on an approximately 160 dpi screen (for example a 240x320, 1.5"x2" screen), providing the baseline of the system\'s display. Thus on a 160dpi screen this density value will be 1; on a 120 dpi screen it would be .75; etc.',
            examples: [2.75],
        },
        $device_model: {
            label: 'Device Model',
            description: 'The model of the device that was used.',
            examples: ['iPhone9,3', 'SM-G965W'],
        },
        $network_wifi: {
            label: 'Network WiFi',
            description: 'Whether the user was on WiFi when the event was sent.',
            examples: ['true', 'false'],
        },
        $network_bluetooth: {
            label: 'Network Bluetooth',
            description: 'Whether the user was on Bluetooth when the event was sent.',
            examples: ['true', 'false'],
        },
        $network_cellular: {
            label: 'Network Cellular',
            description: 'Whether the user was on cellular when the event was sent.',
            examples: ['true', 'false'],
        },
        $client_session_initial_referring_host: {
            label: 'Referrer Host',
            description: 'Host that the user came from. (First-touch, session-scoped)',
            examples: ['google.com', 'facebook.com'],
        },
        $client_session_initial_pathname: {
            label: 'Initial Path',
            description: 'Path that the user started their session on. (First-touch, session-scoped)',
            examples: ['/register', '/some/landing/page'],
        },
        $client_session_initial_utm_source: {
            label: 'Initial UTM Source',
            description: 'UTM Source. (First-touch, session-scoped)',
            examples: ['Google', 'Bing', 'Twitter', 'Facebook'],
        },
        $client_session_initial_utm_campaign: {
            label: 'Initial UTM Campaign',
            description: 'UTM Campaign. (First-touch, session-scoped)',
            examples: ['feature launch', 'discount'],
        },
        $client_session_initial_utm_medium: {
            label: 'Initial UTM Medium',
            description: 'UTM Medium. (First-touch, session-scoped)',
            examples: ['Social', 'Organic', 'Paid', 'Email'],
        },
        $client_session_initial_utm_content: {
            label: 'Initial UTM Source',
            description: 'UTM Source. (First-touch, session-scoped)',
            examples: ['bottom link', 'second button'],
        },
        $client_session_initial_utm_term: {
            label: 'Initial UTM Source',
            description: 'UTM Source. (First-touch, session-scoped)',
            examples: ['free goodies'],
        },
        $network_carrier: {
            label: 'Network Carrier',
            description: 'The network carrier that the user is on.',
            examples: ['cricket', 'telecom'],
        },
        from_background: {
            label: 'From Background',
            description: 'Whether the app was opened for the first time or from the background.',
            examples: ['true', 'false'],
        },
        url: {
            label: 'URL',
            description: 'The deep link URL that the app was opened from.',
            examples: ['https://open.my.app'],
        },
        referring_application: {
            label: 'Referrer Application',
            description: 'The namespace of the app that made the request.',
            examples: ['com.posthog.app'],
        },
        version: {
            label: 'App Version',
            description: 'The version of the app',
            examples: ['1.0.0'],
        },
        previous_version: {
            label: 'App Previous Version',
            description: 'The previous version of the app',
            examples: ['1.0.0'],
        },
        build: {
            label: 'App Build',
            description: 'The build number for the app',
            examples: ['1'],
        },
        previous_build: {
            label: 'App Previous Build',
            description: 'The previous build number for the app',
            examples: ['1'],
        },
        gclid: {
            label: 'gclid',
            description: 'Google Click ID',
        },
        rdt_cid: {
            label: 'rdt_cid',
            description: 'Reddit Click ID',
        },
        irclid: {
            label: 'irclid',
            description: 'Impact Click ID',
        },
        _kx: {
            label: '_kx',
            description: 'Klaviyo Tracking ID',
        },
        gad_source: {
            label: 'gad_source',
            description: 'Google Ads Source',
        },
        gclsrc: {
            label: 'gclsrc',
            description: 'Google Click Source',
        },
        dclid: {
            label: 'dclid',
            description: 'DoubleClick ID',
        },
        gbraid: {
            label: 'gbraid',
            description: 'Google Ads, web to app',
        },
        wbraid: {
            label: 'wbraid',
            description: 'Google Ads, app to web',
        },
        fbclid: {
            label: 'fbclid',
            description: 'Facebook Click ID',
        },
        msclkid: {
            label: 'msclkid',
            description: 'Microsoft Click ID',
        },
        twclid: {
            label: 'twclid',
            description: 'Twitter Click ID',
        },
        li_fat_id: {
            label: 'li_fat_id',
            description: 'LinkedIn First-Party Ad Tracking ID',
        },
        mc_cid: {
            label: 'mc_cid',
            description: 'Mailchimp Campaign ID',
        },
        igshid: {
            label: 'igshid',
            description: 'Instagram Share ID',
        },
        ttclid: {
            label: 'ttclid',
            description: 'TikTok Click ID',
        },
        $is_identified: {
            label: 'Is Identified',
            description: 'When the person was identified',
        },
        $initial_person_info: {
            label: 'Initial Person Info',
            description: 'posthog-js initial person information. used in the $set_once flow',
            system: true,
        },
        $web_vitals_enabled_server_side: {
            label: 'Web vitals enabled server side',
            description: 'Whether web vitals was enabled in remote config',
        },
        $web_vitals_FCP_event: {
            label: 'Web vitals FCP measure event details',
        },
        $web_vitals_FCP_value: {
            label: 'Web vitals FCP value',
        },
        $web_vitals_LCP_event: {
            label: 'Web vitals LCP measure event details',
        },
        $web_vitals_LCP_value: {
            label: 'Web vitals LCP value',
        },
        $web_vitals_INP_event: {
            label: 'Web vitals INP measure event details',
        },
        $web_vitals_INP_value: {
            label: 'Web vitals INP value',
        },
        $web_vitals_CLS_event: {
            label: 'Web vitals CLS measure event details',
        },
        $web_vitals_CLS_value: {
            label: 'Web vitals CLS value',
        },
        $web_vitals_allowed_metrics: {
            label: 'Web vitals allowed metrics',
            description: 'Allowed web vitals metrics config.',
            examples: ['["LCP", "CLS"]'],
            system: true,
        },
        $prev_pageview_last_scroll: {
            label: 'Previous pageview last scroll',
            description: 'posthog-js adds these to the page leave event, they are used in web analytics calculations',
            examples: [0],
        },
        $prev_pageview_id: {
            label: 'Previous pageview ID',
            description: 'posthog-js adds these to the page leave event, they are used in web analytics calculations',
            examples: ['1'],
            system: true,
        },
        $prev_pageview_last_scroll_percentage: {
            label: 'Previous pageview last scroll percentage',
            description: 'posthog-js adds these to the page leave event, they are used in web analytics calculations',
            examples: [0],
        },
        $prev_pageview_max_scroll: {
            examples: [0],
            label: 'Previous pageview max scroll',
            description: 'posthog-js adds these to the page leave event, they are used in web analytics calculations',
        },
        $prev_pageview_max_scroll_percentage: {
            examples: [0],
            label: 'Previous pageview max scroll percentage',
            description: 'posthog-js adds these to the page leave event, they are used in web analytics calculations',
        },
        $prev_pageview_last_content: {
            examples: [0],
            label: 'Previous pageview last content',
            description: 'posthog-js adds these to the page leave event, they are used in web analytics calculations',
        },
        $prev_pageview_last_content_percentage: {
            examples: [0],
            description: 'posthog-js adds these to the page leave event, they are used in web analytics calculations',
            label: 'Previous pageview last content percentage',
        },
        $prev_pageview_max_content: {
            examples: [0],
            description: 'posthog-js adds these to the page leave event, they are used in web analytics calculations',
            label: 'Previous pageview max content',
        },
        $prev_pageview_max_content_percentage: {
            examples: [0],
            description: 'posthog-js adds these to the page leave event, they are used in web analytics calculations',
            label: 'Previous pageview max content percentage',
        },
        $prev_pageview_pathname: {
            examples: ['/pricing', '/about-us/team'],
            description: 'posthog-js adds these to the page leave event, they are used in web analytics calculations',
            label: 'Previous pageview pathname',
        },
        $prev_pageview_duration: {
            examples: [0],
            description: 'posthog-js adds these to the page leave event, they are used in web analytics calculations',
            label: 'Previous pageview duration',
        },
        $surveys_activated: {
            label: 'Surveys Activated',
            description: 'The surveys that were activated for this event.',
        },
        $process_person_profile: {
            label: 'Person Profile processing flag',
            description: 'The setting from an SDK to control whether an event has person processing enabled',
            system: true,
        },
        $dead_clicks_enabled_server_side: {
            label: 'Dead clicks enabled server side',
            description: 'Whether dead clicks were enabled in remote config',
            system: true,
        },
        $dead_click_scroll_delay_ms: {
            label: 'Dead click scroll delay in milliseconds',
            description: 'The delay between a click and the next scroll event',
            system: true,
        },
        $dead_click_mutation_delay_ms: {
            label: 'Dead click mutation delay in milliseconds',
            description: 'The delay between a click and the next mutation event',
            system: true,
        },
        $dead_click_absolute_delay_ms: {
            label: 'Dead click absolute delay in milliseconds',
            description: 'The delay between a click and having seen no activity at all',
            system: true,
        },
        $dead_click_selection_changed_delay_ms: {
            label: 'Dead click selection changed delay in milliseconds',
            description: 'The delay between a click and the next text selection change event',
            system: true,
        },
        $dead_click_last_mutation_timestamp: {
            label: 'Dead click last mutation timestamp',
            description: 'debug signal time of the last mutation seen by dead click autocapture',
            system: true,
        },
        $dead_click_event_timestamp: {
            label: 'Dead click event timestamp',
            description: 'debug signal time of the event that triggered dead click autocapture',
            system: true,
        },
        $dead_click_scroll_timeout: {
            label: 'Dead click scroll timeout',
            description: 'whether the dead click autocapture passed the threshold for waiting for a scroll event',
        },
        $dead_click_mutation_timeout: {
            label: 'Dead click mutation timeout',
            description: 'whether the dead click autocapture passed the threshold for waiting for a mutation event',
            system: true,
        },
        $dead_click_absolute_timeout: {
            label: 'Dead click absolute timeout',
            description: 'whether the dead click autocapture passed the threshold for waiting for any activity',
            system: true,
        },
        $dead_click_selection_changed_timeout: {
            label: 'Dead click selection changed timeout',
            description: 'whether the dead click autocapture passed the threshold for waiting for a text selection change event',
            system: true,
        },
        $ai_base_url: {
            label: 'AI Base URL (LLM)',
            description: 'The base URL of the request made to the LLM API',
            examples: ['https://api.openai.com/v1/'],
        },
        $ai_http_status: {
            label: 'AI HTTP Status (LLM)',
            description: 'The HTTP status code of the request made to the LLM API',
            examples: [200, 429],
        },
        $ai_input: {
            label: 'AI Input (LLM)',
            description: 'The input JSON that was sent to the LLM API',
            examples: ['{"content": "Explain quantum computing in simple terms.", "role": "user"}'],
        },
        $ai_input_tokens: {
            label: 'AI Input Tokens (LLM)',
            description: 'The number of tokens in the input prmopt that was sent to the LLM API',
            examples: [23],
        },
        $ai_output: {
            label: 'AI Output (LLM)',
            description: 'The output JSON that was received from the LLM API',
            examples: ['{"choices": [{"text": "Quantum computing is a type of computing that harnesses the power of quantum mechanics to perform operations on data."}]}'],
        },
        $ai_output_tokens: {
            label: 'AI Output Tokens (LLM)',
            description: 'The number of tokens in the output from the LLM API',
            examples: [23],
        },
        $ai_latency: {
            label: 'AI Latency (LLM)',
            description: 'The latency of the request made to the LLM API, in seconds',
            examples: [1000],
        },
        $ai_model: {
            label: 'AI Model (LLM)',
            description: 'The model used to generate the output from the LLM API',
            examples: ['gpt-4o-mini'],
        },
        $ai_model_parameters: {
            label: 'AI Model Parameters (LLM)',
            description: 'The parameters used to configure the model in the LLM API, in JSON',
            examples: ['{"temperature": 0.5, "max_tokens": 50}'],
        },
        $ai_provider: {
            label: 'AI Provider (LLM)',
            description: 'The provider of the AI model used to generate the output from the LLM API',
            examples: ['openai'],
        },
        $ai_trace_id: {
            label: 'AI Trace ID (LLM)',
            description: 'The trace ID of the request made to the LLM API. Used to group together multiple generations into a single trace',
            examples: ['c9222e05-8708-41b8-98ea-d4a21849e761'],
        },
        $ai_metric_name: {
            label: 'AI Metric Name (LLM)',
            description: 'The name assigned to the metric used to evaluate the LLM trace',
            examples: ['rating', 'accuracy'],
        },
        $ai_metric_value: {
            label: 'AI Metric Value (LLM)',
            description: 'The value assigned to the metric used to evaluate the LLM trace',
            examples: ['negative', '95'],
        },
        $ai_feedback_text: {
            label: 'AI Feedback Text (LLM)',
            description: 'The text provided by the user for feedback on the LLM trace',
            examples: ['"The response was helpful, but it did not use the provided context."'],
        },
        $ai_parent_id: {
            label: 'AI Parent ID (LLM)',
            description: 'The parent span ID of a span or generation, used to group a trace into a tree view',
            examples: ['bdf42359-9364-4db7-8958-c001f28c9255'],
        },
        $ai_span_id: {
            label: 'AI Span ID (LLM)',
            description: 'The unique identifier for a LLM trace, generation, or span.',
            examples: ['bdf42359-9364-4db7-8958-c001f28c9255'],
        },
        $session_entry_url: {
            label: 'Session entry Current URL',
            description: 'The URL visited at the time of the event.. Captured at the start of the session and remains constant for the duration of the session.',
            examples: ['https://example.com/interesting-article?parameter=true'],
        },
        $session_entry_fbclid: {
            label: 'Session entry fbclid',
            description: 'Facebook Click ID. Captured at the start of the session and remains constant for the duration of the session.',
        },
        $session_entry_gclid: {
            label: 'Session entry gclid',
            description: 'Google Click ID. Captured at the start of the session and remains constant for the duration of the session.',
        },
        $session_entry_utm_campaign: {
            label: 'Session entry UTM Campaign',
            description: 'UTM campaign tag.. Captured at the start of the session and remains constant for the duration of the session.',
            examples: ['feature launch', 'discount'],
        },
        $session_entry_utm_source: {
            label: 'Session entry UTM Source',
            description: 'UTM source tag.. Captured at the start of the session and remains constant for the duration of the session.',
            examples: ['Google', 'Bing', 'Twitter', 'Facebook'],
        },
        $session_entry_rdt_cid: {
            label: 'Session entry rdt_cid',
            description: 'Reddit Click ID. Captured at the start of the session and remains constant for the duration of the session.',
        },
        $session_entry_referring_domain: {
            label: 'Session entry Referring Domain',
            description: 'Domain of where the user came from.. Captured at the start of the session and remains constant for the duration of the session.',
            examples: ['google.com', 'facebook.com'],
        },
        $session_entry_pathname: {
            label: 'Session entry Path Name',
            description: 'The path of the Current URL, which means everything in the url after the domain.. Captured at the start of the session and remains constant for the duration of the session.',
            examples: ['/pricing', '/about-us/team'],
        },
        $session_entry_wbraid: {
            label: 'Session entry wbraid',
            description: 'Google Ads, app to web. Captured at the start of the session and remains constant for the duration of the session.',
        },
        $session_entry__kx: {
            label: 'Session entry _kx',
            description: 'Klaviyo Tracking ID. Captured at the start of the session and remains constant for the duration of the session.',
        },
        $session_entry_referrer: {
            label: 'Session entry Referrer URL',
            description: 'URL of where the user came from.. Captured at the start of the session and remains constant for the duration of the session.',
            examples: ['https://google.com/search?q=posthog&rlz=1C...'],
        },
        $session_entry_twclid: {
            label: 'Session entry twclid',
            description: 'Twitter Click ID. Captured at the start of the session and remains constant for the duration of the session.',
        },
        $session_entry_host: {
            label: 'Session entry Host',
            description: 'The hostname of the Current URL.. Captured at the start of the session and remains constant for the duration of the session.',
            examples: ['example.com', 'localhost:8000'],
        },
        $session_entry_gad_source: {
            label: 'Session entry gad_source',
            description: 'Google Ads Source. Captured at the start of the session and remains constant for the duration of the session.',
        },
        $session_entry_irclid: {
            label: 'Session entry irclid',
            description: 'Impact Click ID. Captured at the start of the session and remains constant for the duration of the session.',
        },
        $session_entry_utm_medium: {
            label: 'Session entry UTM Medium',
            description: 'UTM medium tag.. Captured at the start of the session and remains constant for the duration of the session.',
            examples: ['Social', 'Organic', 'Paid', 'Email'],
        },
        $session_entry_gclsrc: {
            label: 'Session entry gclsrc',
            description: 'Google Click Source. Captured at the start of the session and remains constant for the duration of the session.',
        },
        $session_entry_msclkid: {
            label: 'Session entry msclkid',
            description: 'Microsoft Click ID. Captured at the start of the session and remains constant for the duration of the session.',
        },
        $session_entry_li_fat_id: {
            label: 'Session entry li_fat_id',
            description: 'LinkedIn First-Party Ad Tracking ID. Captured at the start of the session and remains constant for the duration of the session.',
        },
        $session_entry_igshid: {
            label: 'Session entry igshid',
            description: 'Instagram Share ID. Captured at the start of the session and remains constant for the duration of the session.',
        },
        $session_entry_dclid: {
            label: 'Session entry dclid',
            description: 'DoubleClick ID. Captured at the start of the session and remains constant for the duration of the session.',
        },
        $session_entry_gbraid: {
            label: 'Session entry gbraid',
            description: 'Google Ads, web to app. Captured at the start of the session and remains constant for the duration of the session.',
        },
        $session_entry_utm_term: {
            label: 'Session entry UTM Term',
            description: 'UTM term tag.. Captured at the start of the session and remains constant for the duration of the session.',
            examples: ['free goodies'],
        },
        $session_entry_ttclid: {
            label: 'Session entry ttclid',
            description: 'TikTok Click ID. Captured at the start of the session and remains constant for the duration of the session.',
        },
        $session_entry_mc_cid: {
            label: 'Session entry mc_cid',
            description: 'Mailchimp Campaign ID. Captured at the start of the session and remains constant for the duration of the session.',
        },
        $session_entry_utm_content: {
            label: 'Session entry UTM Content',
            description: 'UTM content tag.. Captured at the start of the session and remains constant for the duration of the session.',
            examples: ['bottom link', 'second button'],
        },
    },
    numerical_event_properties: {
    },
    person_properties: {
        $python_runtime: {
            label: 'Python Runtime',
            description: 'The Python runtime that was used to capture the event.',
            examples: ['CPython'],
            system: true,
            ignored_in_assistant: true,
        },
        $python_version: {
            label: 'Python Version',
            description: 'The Python version that was used to capture the event.',
            examples: ['3.11.5'],
            system: true,
            ignored_in_assistant: true,
        },
        $sdk_debug_replay_internal_buffer_length: {
            label: 'Replay internal buffer length',
            description: 'Useful for debugging. The internal buffer length for replay.',
            examples: ['100'],
            system: true,
            ignored_in_assistant: true,
        },
        $sdk_debug_replay_internal_buffer_size: {
            label: 'Replay internal buffer size',
            description: 'Useful for debugging. The internal buffer size for replay.',
            examples: ['100'],
            system: true,
            ignored_in_assistant: true,
        },
        $sdk_debug_retry_queue_size: {
            label: 'Retry queue size',
            description: 'Useful for debugging. The size of the retry queue.',
            examples: ['100'],
            system: true,
            ignored_in_assistant: true,
        },
        $last_posthog_reset: {
            label: 'Timestamp of last call to `Reset` in the web sdk',
            description: 'The timestamp of the last call to `Reset` in the web SDK. This can be useful for debugging.',
            ignored_in_assistant: true,
            system: true,
        },
        $copy_type: {
            label: 'Copy Type',
            description: 'Type of copy event.',
            examples: ['copy', 'cut'],
            ignored_in_assistant: true,
        },
        $selected_content: {
            label: 'Copied content',
            description: 'The content that was selected when the user copied or cut.',
            ignored_in_assistant: true,
        },
        $set: {
            label: 'Set person properties',
            description: 'Person properties to be set. Sent as `$set`',
            ignored_in_assistant: true,
        },
        $set_once: {
            label: 'Set person properties once',
            description: 'Person properties to be set if not set already (i.e. first-touch). Sent as `$set_once`',
            ignored_in_assistant: true,
        },
        $pageview_id: {
            label: 'Pageview ID',
            description: 'PostHog\'s internal ID for matching events to a pageview.',
            system: true,
            ignored_in_assistant: true,
        },
        $autocapture_disabled_server_side: {
            label: 'Autocapture Disabled Server-Side',
            description: 'If autocapture has been disabled server-side.',
            system: true,
            ignored_in_assistant: true,
        },
        $console_log_recording_enabled_server_side: {
            label: 'Console Log Recording Enabled Server-Side',
            description: 'If console log recording has been enabled server-side.',
            system: true,
            ignored_in_assistant: true,
        },
        $session_recording_recorder_version_server_side: {
            label: 'Session Recording Recorder Version Server-Side',
            description: 'The version of the session recording recorder that is enabled server-side.',
            examples: ['v2'],
            system: true,
            ignored_in_assistant: true,
        },
        $session_is_sampled: {
            label: 'Whether the session is sampled',
            description: 'Whether the session is sampled for session recording.',
            examples: ['true', 'false'],
            system: true,
            ignored_in_assistant: true,
        },
        $feature_flag_payloads: {
            label: 'Feature Flag Payloads',
            description: 'Feature flag payloads active in the environment.',
            ignored_in_assistant: true,
        },
        $capture_failed_request: {
            label: 'Capture Failed Request',
            description: '',
            ignored_in_assistant: true,
        },
        $lib_rate_limit_remaining_tokens: {
            label: 'Clientside rate limit remaining tokens',
            description: 'Remaining rate limit tokens for the posthog-js library client-side rate limiting implementation.',
            examples: ['100'],
            ignored_in_assistant: true,
        },
        token: {
            label: 'Token',
            description: 'Token used for authentication.',
            examples: ['ph_abcdefg'],
            ignored_in_assistant: true,
        },
        $sentry_exception: {
            label: 'Sentry exception',
            description: 'Raw Sentry exception data',
            system: true,
        },
        $sentry_exception_message: {
            label: 'Sentry exception message',
        },
        $sentry_exception_type: {
            label: 'Sentry exception type',
            description: 'Class name of the exception object',
        },
        $sentry_tags: {
            label: 'Sentry tags',
            description: 'Tags sent to Sentry along with the exception',
        },
        $exception_list: {
            label: 'Exception list',
            description: 'List of one or more associated exceptions',
            system: true,
        },
        $exception_level: {
            label: 'Exception level',
            description: 'Exception categorized by severity',
            examples: ['error'],
        },
        $exception_type: {
            label: 'Exception type',
            description: 'Exception categorized into types',
            examples: ['Error'],
        },
        $exception_message: {
            label: 'Exception message',
            description: 'The message detected on the error',
        },
        $exception_fingerprint: {
            label: 'Exception fingerprint',
            description: 'A fingerprint used to group issues, can be set clientside',
        },
        $exception_proposed_fingerprint: {
            label: 'Exception proposed fingerprint',
            description: 'The fingerprint used to group issues. Auto generated unless provided clientside',
        },
        $exception_issue_id: {
            label: 'Exception issue ID',
            description: 'The id of the issue the fingerprint was associated with at ingest time',
        },
        $exception_source: {
            label: 'Exception source',
            description: 'The source of the exception',
            examples: ['JS file'],
        },
        $exception_lineno: {
            label: 'Exception source line number',
            description: 'Which line in the exception source that caused the exception',
        },
        $exception_colno: {
            label: 'Exception source column number',
            description: 'Which column of the line in the exception source that caused the exception',
        },
        $exception_DOMException_code: {
            label: 'DOMException code',
            description: 'If a DOMException was thrown, it also has a DOMException code',
        },
        $exception_is_synthetic: {
            label: 'Exception is synthetic',
            description: 'Whether this was detected as a synthetic exception',
        },
        $exception_stack_trace_raw: {
            label: 'Exception raw stack trace',
            description: 'The exceptions stack trace, as a string',
        },
        $exception_handled: {
            label: 'Exception was handled',
            description: 'Whether this was a handled or unhandled exception',
        },
        $exception_personURL: {
            label: 'Exception person URL',
            description: 'The PostHog person that experienced the exception',
        },
        $cymbal_errors: {
            label: 'Exception processing errors',
            description: 'Errors encountered while trying to process exceptions',
            system: true,
        },
        $exception_capture_endpoint: {
            label: 'Exception capture endpoint',
            description: 'Endpoint used by posthog-js exception autocapture.',
            examples: ['/e/'],
        },
        $exception_capture_endpoint_suffix: {
            label: 'Exception capture endpoint',
            description: 'Endpoint used by posthog-js exception autocapture.',
            examples: ['/e/'],
        },
        $exception_capture_enabled_server_side: {
            label: 'Exception capture enabled server side',
            description: 'Whether exception autocapture was enabled in remote config.',
        },
        $ce_version: {
            label: '$ce_version',
            description: '',
            system: true,
        },
        $anon_distinct_id: {
            label: 'Anon Distinct ID',
            description: 'If the user was previously anonymous, their anonymous ID will be set here.',
            examples: ['16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767'],
            system: true,
        },
        $event_type: {
            label: 'Event Type',
            description: 'When the event is an $autocapture event, this specifies what the action was against the element.',
            examples: ['click', 'submit', 'change'],
        },
        $insert_id: {
            label: 'Insert ID',
            description: 'Unique insert ID for the event.',
            system: true,
        },
        $time: {
            label: '$time (deprecated)',
            description: 'Use the HogQL field `timestamp` instead. This field was previously set on some client side events.',
            system: true,
            examples: ['1681211521.345'],
        },
        $browser_type: {
            label: 'Browser Type',
            description: 'This is only added when posthog-js config.opt_out_useragent_filter is true.',
            examples: ['browser', 'bot'],
        },
        $device_id: {
            label: 'Device ID',
            description: 'Unique ID for that device, consistent even if users are logging in/out.',
            examples: ['16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767'],
            system: true,
        },
        $replay_minimum_duration: {
            label: 'Replay config - minimum duration',
            description: 'Config for minimum duration before emitting a session recording.',
            examples: ['1000'],
            system: true,
        },
        $replay_sample_rate: {
            label: 'Replay config - sample rate',
            description: 'Config for sampling rate of session recordings.',
            examples: ['0.1'],
            system: true,
        },
        $session_recording_start_reason: {
            label: 'Session recording start reason',
            description: 'Reason for starting the session recording. Useful for e.g. if you have sampling enabled and want to see on batch exported events which sessions have recordings available.',
            examples: ['sampling_override', 'recording_initialized', 'linked_flag_match'],
            system: true,
        },
        $session_recording_canvas_recording: {
            label: 'Session recording canvas recording',
            description: 'Session recording canvas capture config.',
            examples: ['{"enabled": false}'],
            system: true,
        },
        $session_recording_network_payload_capture: {
            label: 'Session recording network payload capture',
            description: 'Session recording network payload capture config.',
            examples: ['{"recordHeaders": false}'],
            system: true,
        },
        $configured_session_timeout_ms: {
            label: 'Configured session timeout',
            description: 'Configured session timeout in milliseconds.',
            examples: ['1800000'],
            system: true,
        },
        $replay_script_config: {
            label: 'Replay script config',
            description: 'Sets an alternative recorder script for the web sdk.',
            examples: ['{"script": "recorder-next""}'],
            system: true,
        },
        $session_recording_url_trigger_activated_session: {
            label: 'Session recording URL trigger activated session',
            description: 'Session recording URL trigger activated session config. Used by posthog-js to track URL activation of session replay.',
            system: true,
        },
        $session_recording_url_trigger_status: {
            label: 'Session recording URL trigger status',
            description: 'Session recording URL trigger status. Used by posthog-js to track URL activation of session replay.',
            system: true,
        },
        $recording_status: {
            label: 'Session recording status',
            description: 'The status of session recording at the time the event was captured',
            system: true,
        },
        $geoip_city_name: {
            label: 'Latest City Name',
            description: 'Name of the city matched to this event\'s IP address. Data from the last time this user was seen.',
            examples: ['Sydney', 'Chennai', 'Brooklyn'],
        },
        $initial_geoip_city_name: {
            label: 'Initial City Name',
            description: 'Name of the city matched to this event\'s IP address. Data from the first time this user was seen.',
            examples: ['Sydney', 'Chennai', 'Brooklyn'],
        },
        $geoip_country_name: {
            label: 'Latest Country Name',
            description: 'Name of the country matched to this event\'s IP address. Data from the last time this user was seen.',
            examples: ['Australia', 'India', 'United States'],
        },
        $initial_geoip_country_name: {
            label: 'Initial Country Name',
            description: 'Name of the country matched to this event\'s IP address. Data from the first time this user was seen.',
            examples: ['Australia', 'India', 'United States'],
        },
        $geoip_country_code: {
            label: 'Latest Country Code',
            description: 'Code of the country matched to this event\'s IP address. Data from the last time this user was seen.',
            examples: ['AU', 'IN', 'US'],
        },
        $initial_geoip_country_code: {
            label: 'Initial Country Code',
            description: 'Code of the country matched to this event\'s IP address. Data from the first time this user was seen.',
            examples: ['AU', 'IN', 'US'],
        },
        $geoip_continent_name: {
            label: 'Latest Continent Name',
            description: 'Name of the continent matched to this event\'s IP address. Data from the last time this user was seen.',
            examples: ['Oceania', 'Asia', 'North America'],
        },
        $initial_geoip_continent_name: {
            label: 'Initial Continent Name',
            description: 'Name of the continent matched to this event\'s IP address. Data from the first time this user was seen.',
            examples: ['Oceania', 'Asia', 'North America'],
        },
        $geoip_continent_code: {
            label: 'Latest Continent Code',
            description: 'Code of the continent matched to this event\'s IP address. Data from the last time this user was seen.',
            examples: ['OC', 'AS', 'NA'],
        },
        $initial_geoip_continent_code: {
            label: 'Initial Continent Code',
            description: 'Code of the continent matched to this event\'s IP address. Data from the first time this user was seen.',
            examples: ['OC', 'AS', 'NA'],
        },
        $geoip_postal_code: {
            label: 'Latest Postal Code',
            description: 'Approximated postal code matched to this event\'s IP address. Data from the last time this user was seen.',
            examples: ['2000', '600004', '11211'],
        },
        $initial_geoip_postal_code: {
            label: 'Initial Postal Code',
            description: 'Approximated postal code matched to this event\'s IP address. Data from the first time this user was seen.',
            examples: ['2000', '600004', '11211'],
        },
        $geoip_postal_code_confidence: {
            label: 'Latest Postal Code identification confidence score',
            description: 'If provided by the licensed geoip database Data from the last time this user was seen.',
            examples: ['null', '0.1'],
            system: true,
            ignored_in_assistant: true,
        },
        $initial_geoip_postal_code_confidence: {
            label: 'Initial Postal Code identification confidence score',
            description: 'If provided by the licensed geoip database Data from the first time this user was seen.',
            examples: ['null', '0.1'],
            system: true,
            ignored_in_assistant: true,
        },
        $geoip_latitude: {
            label: 'Latest Latitude',
            description: 'Approximated latitude matched to this event\'s IP address. Data from the last time this user was seen.',
            examples: ['-33.8591', '13.1337', '40.7'],
        },
        $initial_geoip_latitude: {
            label: 'Initial Latitude',
            description: 'Approximated latitude matched to this event\'s IP address. Data from the first time this user was seen.',
            examples: ['-33.8591', '13.1337', '40.7'],
        },
        $geoip_longitude: {
            label: 'Latest Longitude',
            description: 'Approximated longitude matched to this event\'s IP address. Data from the last time this user was seen.',
            examples: ['151.2', '80.8008', '-73.9'],
        },
        $initial_geoip_longitude: {
            label: 'Initial Longitude',
            description: 'Approximated longitude matched to this event\'s IP address. Data from the first time this user was seen.',
            examples: ['151.2', '80.8008', '-73.9'],
        },
        $geoip_time_zone: {
            label: 'Latest Timezone',
            description: 'Timezone matched to this event\'s IP address. Data from the last time this user was seen.',
            examples: ['Australia/Sydney', 'Asia/Kolkata', 'America/New_York'],
        },
        $initial_geoip_time_zone: {
            label: 'Initial Timezone',
            description: 'Timezone matched to this event\'s IP address. Data from the first time this user was seen.',
            examples: ['Australia/Sydney', 'Asia/Kolkata', 'America/New_York'],
        },
        $geoip_subdivision_1_name: {
            label: 'Latest Subdivision 1 Name',
            description: 'Name of the subdivision matched to this event\'s IP address. Data from the last time this user was seen.',
            examples: ['New South Wales', 'Tamil Nadu', 'New York'],
        },
        $initial_geoip_subdivision_1_name: {
            label: 'Initial Subdivision 1 Name',
            description: 'Name of the subdivision matched to this event\'s IP address. Data from the first time this user was seen.',
            examples: ['New South Wales', 'Tamil Nadu', 'New York'],
        },
        $geoip_subdivision_1_code: {
            label: 'Latest Subdivision 1 Code',
            description: 'Code of the subdivision matched to this event\'s IP address. Data from the last time this user was seen.',
            examples: ['NSW', 'TN', 'NY'],
        },
        $initial_geoip_subdivision_1_code: {
            label: 'Initial Subdivision 1 Code',
            description: 'Code of the subdivision matched to this event\'s IP address. Data from the first time this user was seen.',
            examples: ['NSW', 'TN', 'NY'],
        },
        $geoip_subdivision_2_name: {
            label: 'Latest Subdivision 2 Name',
            description: 'Name of the second subdivision matched to this event\'s IP address. Data from the last time this user was seen.',
        },
        $initial_geoip_subdivision_2_name: {
            label: 'Initial Subdivision 2 Name',
            description: 'Name of the second subdivision matched to this event\'s IP address. Data from the first time this user was seen.',
        },
        $geoip_subdivision_2_code: {
            label: 'Latest Subdivision 2 Code',
            description: 'Code of the second subdivision matched to this event\'s IP address. Data from the last time this user was seen.',
        },
        $initial_geoip_subdivision_2_code: {
            label: 'Initial Subdivision 2 Code',
            description: 'Code of the second subdivision matched to this event\'s IP address. Data from the first time this user was seen.',
        },
        $geoip_subdivision_2_confidence: {
            label: 'Latest Subdivision 2 identification confidence score',
            description: 'If provided by the licensed geoip database Data from the last time this user was seen.',
            examples: ['null', '0.1'],
            ignored_in_assistant: true,
        },
        $initial_geoip_subdivision_2_confidence: {
            label: 'Initial Subdivision 2 identification confidence score',
            description: 'If provided by the licensed geoip database Data from the first time this user was seen.',
            examples: ['null', '0.1'],
            ignored_in_assistant: true,
        },
        $geoip_subdivision_3_name: {
            label: 'Latest Subdivision 3 Name',
            description: 'Name of the third subdivision matched to this event\'s IP address. Data from the last time this user was seen.',
        },
        $initial_geoip_subdivision_3_name: {
            label: 'Initial Subdivision 3 Name',
            description: 'Name of the third subdivision matched to this event\'s IP address. Data from the first time this user was seen.',
        },
        $geoip_subdivision_3_code: {
            label: 'Latest Subdivision 3 Code',
            description: 'Code of the third subdivision matched to this event\'s IP address. Data from the last time this user was seen.',
        },
        $initial_geoip_subdivision_3_code: {
            label: 'Initial Subdivision 3 Code',
            description: 'Code of the third subdivision matched to this event\'s IP address. Data from the first time this user was seen.',
        },
        $geoip_disable: {
            label: 'Latest GeoIP Disabled',
            description: 'Whether to skip GeoIP processing for the event. Data from the last time this user was seen.',
        },
        $initial_geoip_disable: {
            label: 'Initial GeoIP Disabled',
            description: 'Whether to skip GeoIP processing for the event. Data from the first time this user was seen.',
        },
        $el_text: {
            label: 'Element Text',
            description: 'The text of the element that was clicked. Only sent with Autocapture events.',
            examples: ['Click here!'],
        },
        $app_build: {
            label: 'Latest App Build',
            description: 'The build number for the app. Data from the last time this user was seen.',
        },
        $initial_app_build: {
            label: 'Initial App Build',
            description: 'The build number for the app. Data from the first time this user was seen.',
        },
        $app_name: {
            label: 'Latest App Name',
            description: 'The name of the app. Data from the last time this user was seen.',
        },
        $initial_app_name: {
            label: 'Initial App Name',
            description: 'The name of the app. Data from the first time this user was seen.',
        },
        $app_namespace: {
            label: 'Latest App Namespace',
            description: 'The namespace of the app as identified in the app store. Data from the last time this user was seen.',
            examples: ['com.posthog.app'],
        },
        $initial_app_namespace: {
            label: 'Initial App Namespace',
            description: 'The namespace of the app as identified in the app store. Data from the first time this user was seen.',
            examples: ['com.posthog.app'],
        },
        $app_version: {
            label: 'Latest App Version',
            description: 'The version of the app. Data from the last time this user was seen.',
        },
        $initial_app_version: {
            label: 'Initial App Version',
            description: 'The version of the app. Data from the first time this user was seen.',
        },
        $device_manufacturer: {
            label: 'Device Manufacturer',
            description: 'The manufacturer of the device',
            examples: ['Apple', 'Samsung'],
        },
        $device_name: {
            label: 'Device Name',
            description: 'Name of the device',
            examples: ['iPhone 12 Pro', 'Samsung Galaxy 10'],
        },
        $locale: {
            label: 'Locale',
            description: 'The locale of the device',
            examples: ['en-US', 'de-DE'],
        },
        $os_name: {
            label: 'OS Name',
            description: 'The Operating System name',
            examples: ['iOS', 'Android'],
        },
        $os_version: {
            label: 'Latest OS Version',
            description: 'The Operating System version. Data from the last time this user was seen.',
            examples: ['15.5'],
        },
        $initial_os_version: {
            label: 'Initial OS Version',
            description: 'The Operating System version. Data from the first time this user was seen.',
            examples: ['15.5'],
        },
        $timezone: {
            label: 'Timezone',
            description: 'The timezone as reported by the device',
        },
        $touch_x: {
            label: 'Touch X',
            description: 'The location of a Touch event on the X axis',
        },
        $touch_y: {
            label: 'Touch Y',
            description: 'The location of a Touch event on the Y axis',
        },
        $plugins_succeeded: {
            label: 'Plugins Succeeded',
            description: 'Plugins that successfully processed the event, e.g. edited properties (plugin method processEvent).',
        },
        $groups: {
            label: 'Groups',
            description: 'Relevant groups',
        },
        $group_0: {
            label: 'Group 1',
            system: true,
        },
        $group_1: {
            label: 'Group 2',
            system: true,
        },
        $group_2: {
            label: 'Group 3',
            system: true,
        },
        $group_3: {
            label: 'Group 4',
            system: true,
        },
        $group_4: {
            label: 'Group 5',
            system: true,
        },
        $group_set: {
            label: 'Group Set',
            description: 'Group properties to be set',
        },
        $group_key: {
            label: 'Group Key',
            description: 'Specified group key',
        },
        $group_type: {
            label: 'Group Type',
            description: 'Specified group type',
        },
        $window_id: {
            label: 'Window ID',
            description: 'Unique window ID for session recording disambiguation',
            system: true,
        },
        $session_id: {
            label: 'Session ID',
            description: 'Unique session ID for session recording disambiguation',
            system: true,
        },
        $plugins_failed: {
            label: 'Plugins Failed',
            description: 'Plugins that failed to process the event (plugin method processEvent).',
        },
        $plugins_deferred: {
            label: 'Plugins Deferred',
            description: 'Plugins to which the event was handed off post-ingestion, e.g. for export (plugin method onEvent).',
        },
        $$plugin_metrics: {
            label: 'Plugin Metric',
            description: 'Performance metrics for a given plugin.',
        },
        $creator_event_uuid: {
            label: 'Creator Event ID',
            description: 'Unique ID for the event, which created this person.',
            examples: ['16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767'],
        },
        utm_source: {
            label: 'Latest UTM Source',
            description: 'UTM source tag. Data from the last time this user was seen.',
            examples: ['Google', 'Bing', 'Twitter', 'Facebook'],
        },
        $initial_utm_source: {
            label: 'Initial UTM Source',
            description: 'UTM source tag.',
            examples: ['Google', 'Bing', 'Twitter', 'Facebook'],
        },
        utm_medium: {
            label: 'Latest UTM Medium',
            description: 'UTM medium tag. Data from the last time this user was seen.',
            examples: ['Social', 'Organic', 'Paid', 'Email'],
        },
        $initial_utm_medium: {
            label: 'Initial UTM Medium',
            description: 'UTM medium tag. Data from the first time this user was seen.',
            examples: ['Social', 'Organic', 'Paid', 'Email'],
        },
        utm_campaign: {
            label: 'Latest UTM Campaign',
            description: 'UTM campaign tag. Data from the last time this user was seen.',
            examples: ['feature launch', 'discount'],
        },
        $initial_utm_campaign: {
            label: 'Initial UTM Campaign',
            description: 'UTM campaign tag. Data from the first time this user was seen.',
            examples: ['feature launch', 'discount'],
        },
        utm_name: {
            label: 'UTM Name',
            description: 'UTM campaign tag, sent via Segment.',
            examples: ['feature launch', 'discount'],
        },
        utm_content: {
            label: 'Latest UTM Content',
            description: 'UTM content tag. Data from the last time this user was seen.',
            examples: ['bottom link', 'second button'],
        },
        $initial_utm_content: {
            label: 'Initial UTM Content',
            description: 'UTM content tag. Data from the first time this user was seen.',
            examples: ['bottom link', 'second button'],
        },
        utm_term: {
            label: 'Latest UTM Term',
            description: 'UTM term tag. Data from the last time this user was seen.',
            examples: ['free goodies'],
        },
        $initial_utm_term: {
            label: 'Initial UTM Term',
            description: 'UTM term tag. Data from the first time this user was seen.',
            examples: ['free goodies'],
        },
        $performance_page_loaded: {
            label: 'Page Loaded',
            description: 'The time taken until the browser\'s page load event in milliseconds.',
        },
        $performance_raw: {
            label: 'Browser Performance',
            description: 'The browser performance entries for navigation (the page), paint, and resources. That were available when the page view event fired',
            system: true,
        },
        $had_persisted_distinct_id: {
            label: '$had_persisted_distinct_id',
            description: '',
            system: true,
        },
        $sentry_event_id: {
            label: 'Sentry Event ID',
            description: 'This is the Sentry key for an event.',
            examples: ['byroc2ar9ee4ijqp'],
            system: true,
        },
        $timestamp: {
            label: 'Timestamp (deprecated)',
            description: 'Use the HogQL field `timestamp` instead. This field was previously set on some client side events.',
            examples: ['2023-05-20T15:30:00Z'],
            system: true,
        },
        $sent_at: {
            label: 'Sent At',
            description: 'Time the event was sent to PostHog. Used for correcting the event timestamp when the device clock is off.',
            examples: ['2023-05-20T15:31:00Z'],
        },
        $browser: {
            label: 'Latest Browser',
            description: 'Name of the browser the user has used. Data from the last time this user was seen.',
            examples: ['Chrome', 'Firefox'],
        },
        $initial_browser: {
            label: 'Initial Browser',
            description: 'Name of the browser the user has used. Data from the first time this user was seen.',
            examples: ['Chrome', 'Firefox'],
        },
        $os: {
            label: 'Latest OS',
            description: 'The operating system of the user. Data from the last time this user was seen.',
            examples: ['Windows', 'Mac OS X'],
        },
        $initial_os: {
            label: 'Initial OS',
            description: 'The operating system of the user. Data from the first time this user was seen.',
            examples: ['Windows', 'Mac OS X'],
        },
        $browser_language: {
            label: 'Browser Language',
            description: 'Language.',
            examples: ['en', 'en-US', 'cn', 'pl-PL'],
        },
        $browser_language_prefix: {
            label: 'Browser Language Prefix',
            description: 'Language prefix.',
            examples: ['en', 'ja'],
        },
        $current_url: {
            label: 'Latest Current URL',
            description: 'The URL visited at the time of the event. Data from the last time this user was seen.',
            examples: ['https://example.com/interesting-article?parameter=true'],
        },
        $initial_current_url: {
            label: 'Initial Current URL',
            description: 'The URL visited at the time of the event. Data from the first time this user was seen.',
            examples: ['https://example.com/interesting-article?parameter=true'],
        },
        $browser_version: {
            label: 'Latest Browser Version',
            description: 'The version of the browser that was used. Used in combination with Browser. Data from the last time this user was seen.',
            examples: ['70', '79'],
        },
        $initial_browser_version: {
            label: 'Initial Browser Version',
            description: 'The version of the browser that was used. Used in combination with Browser. Data from the first time this user was seen.',
            examples: ['70', '79'],
        },
        $raw_user_agent: {
            label: 'Latest Raw User Agent',
            description: 'PostHog process information like browser, OS, and device type from the user agent string. This is the raw user agent string. Data from the last time this user was seen.',
            examples: ['Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)'],
        },
        $initial_raw_user_agent: {
            label: 'Initial Raw User Agent',
            description: 'PostHog process information like browser, OS, and device type from the user agent string. This is the raw user agent string. Data from the first time this user was seen.',
            examples: ['Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)'],
        },
        $user_agent: {
            label: 'Raw User Agent',
            description: 'Some SDKs (like Android) send the raw user agent as $user_agent.',
            examples: ['Dalvik/2.1.0 (Linux; U; Android 11; Pixel 3 Build/RQ2A.210505.002)'],
        },
        $screen_height: {
            label: 'Latest Screen Height',
            description: 'The height of the user\'s entire screen (in pixels). Data from the last time this user was seen.',
            examples: ['2160', '1050'],
        },
        $initial_screen_height: {
            label: 'Initial Screen Height',
            description: 'The height of the user\'s entire screen (in pixels). Data from the first time this user was seen.',
            examples: ['2160', '1050'],
        },
        $screen_width: {
            label: 'Latest Screen Width',
            description: 'The width of the user\'s entire screen (in pixels). Data from the last time this user was seen.',
            examples: ['1440', '1920'],
        },
        $initial_screen_width: {
            label: 'Initial Screen Width',
            description: 'The width of the user\'s entire screen (in pixels). Data from the first time this user was seen.',
            examples: ['1440', '1920'],
        },
        $screen_name: {
            label: 'Screen Name',
            description: 'The name of the active screen.',
        },
        $viewport_height: {
            label: 'Latest Viewport Height',
            description: 'The height of the user\'s actual browser window (in pixels). Data from the last time this user was seen.',
            examples: ['2094', '1031'],
        },
        $initial_viewport_height: {
            label: 'Initial Viewport Height',
            description: 'The height of the user\'s actual browser window (in pixels). Data from the first time this user was seen.',
            examples: ['2094', '1031'],
        },
        $viewport_width: {
            label: 'Latest Viewport Width',
            description: 'The width of the user\'s actual browser window (in pixels). Data from the last time this user was seen.',
            examples: ['1439', '1915'],
        },
        $initial_viewport_width: {
            label: 'Initial Viewport Width',
            description: 'The width of the user\'s actual browser window (in pixels). Data from the first time this user was seen.',
            examples: ['1439', '1915'],
        },
        $lib: {
            label: 'Library',
            description: 'What library was used to send the event.',
            examples: ['web', 'posthog-ios'],
        },
        $lib_custom_api_host: {
            label: 'Library Custom API Host',
            description: 'The custom API host used to send the event.',
            examples: ['https://ph.example.com'],
        },
        $lib_version: {
            label: 'Library Version',
            description: 'Version of the library used to send the event. Used in combination with Library.',
            examples: ['1.0.3'],
        },
        $lib_version__major: {
            label: 'Library Version (Major)',
            description: 'Major version of the library used to send the event.',
            examples: [1],
        },
        $lib_version__minor: {
            label: 'Library Version (Minor)',
            description: 'Minor version of the library used to send the event.',
            examples: [0],
        },
        $lib_version__patch: {
            label: 'Library Version (Patch)',
            description: 'Patch version of the library used to send the event.',
            examples: [3],
        },
        $referrer: {
            label: 'Latest Referrer URL',
            description: 'URL of where the user came from. Data from the last time this user was seen.',
            examples: ['https://google.com/search?q=posthog&rlz=1C...'],
        },
        $initial_referrer: {
            label: 'Initial Referrer URL',
            description: 'URL of where the user came from. Data from the first time this user was seen.',
            examples: ['https://google.com/search?q=posthog&rlz=1C...'],
        },
        $referring_domain: {
            label: 'Latest Referring Domain',
            description: 'Domain of where the user came from. Data from the last time this user was seen.',
            examples: ['google.com', 'facebook.com'],
        },
        $initial_referring_domain: {
            label: 'Initial Referring Domain',
            description: 'Domain of where the user came from. Data from the first time this user was seen.',
            examples: ['google.com', 'facebook.com'],
        },
        $user_id: {
            label: 'User ID',
            description: 'This variable will be set to the distinct ID if you\'ve called posthog.identify(\'distinct id\'). If the user is anonymous, it\'ll be empty.',
        },
        $ip: {
            label: 'IP Address',
            description: 'IP address for this user when the event was sent.',
            examples: ['203.0.113.0'],
        },
        $host: {
            label: 'Host',
            description: 'The hostname of the Current URL.',
            examples: ['example.com', 'localhost:8000'],
        },
        $pathname: {
            label: 'Latest Path Name',
            description: 'The path of the Current URL, which means everything in the url after the domain. Data from the last time this user was seen.',
            examples: ['/pricing', '/about-us/team'],
        },
        $initial_pathname: {
            label: 'Initial Path Name',
            description: 'The path of the Current URL, which means everything in the url after the domain. Data from the first time this user was seen.',
            examples: ['/pricing', '/about-us/team'],
        },
        $search_engine: {
            label: 'Search Engine',
            description: 'The search engine the user came in from (if any).',
            examples: ['Google', 'DuckDuckGo'],
        },
        $active_feature_flags: {
            label: 'Active Feature Flags',
            description: 'Keys of the feature flags that were active while this event was sent.',
            examples: ["['beta-feature']"],
        },
        $enabled_feature_flags: {
            label: 'Enabled Feature Flags',
            description: 'Keys and multivariate values of the feature flags that were active while this event was sent.',
            examples: ['{"flag": "value"}'],
        },
        $feature_flag_response: {
            label: 'Feature Flag Response',
            description: 'What the call to feature flag responded with.',
            examples: ['true', 'false'],
        },
        $feature_flag_payload: {
            label: 'Feature Flag Response Payload',
            description: 'The JSON payload that the call to feature flag responded with (if any)',
            examples: ['{"variant": "test"}'],
        },
        $feature_flag: {
            label: 'Feature Flag',
            description: 'The feature flag that was called.\n\nWarning! This only works in combination with the $feature_flag_called event. If you want to filter other events, try "Active Feature Flags".',
            examples: ['beta-feature'],
        },
        $feature_flag_reason: {
            label: 'Feature Flag Evaluation Reason',
            description: 'The reason the feature flag was matched or not matched.',
            examples: ['Matched condition set 1'],
        },
        $feature_flag_request_id: {
            label: 'Feature Flag Request ID',
            description: 'The unique identifier for the request that retrieved this feature flag result. Primarily used by PostHog support for debugging issues with feature flags.',
            examples: ['01234567-89ab-cdef-0123-456789abcdef'],
        },
        $feature_flag_version: {
            label: 'Feature Flag Version',
            description: 'The version of the feature flag that was called.',
            examples: ['3'],
        },
        $survey_response: {
            label: 'Survey Response',
            description: 'The response value for the first question in the survey.',
            examples: ['I love it!', 5, "['choice 1', 'choice 3']"],
        },
        $survey_name: {
            label: 'Survey Name',
            description: 'The name of the survey.',
            examples: ['Product Feedback for New Product', 'Home page NPS'],
        },
        $survey_questions: {
            label: 'Survey Questions',
            description: 'The questions asked in the survey.',
        },
        $survey_id: {
            label: 'Survey ID',
            description: 'The unique identifier for the survey.',
        },
        $survey_iteration: {
            label: 'Survey Iteration Number',
            description: 'The iteration number for the survey.',
        },
        $survey_iteration_start_date: {
            label: 'Survey Iteration Start Date',
            description: 'The start date for the current iteration of the survey.',
        },
        $device: {
            label: 'Device',
            description: 'The mobile device that was used.',
            examples: ['iPad', 'iPhone', 'Android'],
        },
        $sentry_url: {
            label: 'Sentry URL',
            description: 'Direct link to the exception in Sentry',
            examples: ['https://sentry.io/...'],
        },
        $device_type: {
            label: 'Latest Device Type',
            description: 'The type of device that was used. Data from the last time this user was seen.',
            examples: ['Mobile', 'Tablet', 'Desktop'],
        },
        $initial_device_type: {
            label: 'Initial Device Type',
            description: 'The type of device that was used. Data from the first time this user was seen.',
            examples: ['Mobile', 'Tablet', 'Desktop'],
        },
        $screen_density: {
            label: 'Screen density',
            description: 'The logical density of the display. This is a scaling factor for the Density Independent Pixel unit, where one DIP is one pixel on an approximately 160 dpi screen (for example a 240x320, 1.5"x2" screen), providing the baseline of the system\'s display. Thus on a 160dpi screen this density value will be 1; on a 120 dpi screen it would be .75; etc.',
            examples: [2.75],
        },
        $device_model: {
            label: 'Device Model',
            description: 'The model of the device that was used.',
            examples: ['iPhone9,3', 'SM-G965W'],
        },
        $network_wifi: {
            label: 'Network WiFi',
            description: 'Whether the user was on WiFi when the event was sent.',
            examples: ['true', 'false'],
        },
        $network_bluetooth: {
            label: 'Network Bluetooth',
            description: 'Whether the user was on Bluetooth when the event was sent.',
            examples: ['true', 'false'],
        },
        $network_cellular: {
            label: 'Network Cellular',
            description: 'Whether the user was on cellular when the event was sent.',
            examples: ['true', 'false'],
        },
        $client_session_initial_referring_host: {
            label: 'Referrer Host',
            description: 'Host that the user came from. (First-touch, session-scoped)',
            examples: ['google.com', 'facebook.com'],
        },
        $client_session_initial_pathname: {
            label: 'Initial Path',
            description: 'Path that the user started their session on. (First-touch, session-scoped)',
            examples: ['/register', '/some/landing/page'],
        },
        $client_session_initial_utm_source: {
            label: 'Initial UTM Source',
            description: 'UTM Source. (First-touch, session-scoped)',
            examples: ['Google', 'Bing', 'Twitter', 'Facebook'],
        },
        $client_session_initial_utm_campaign: {
            label: 'Initial UTM Campaign',
            description: 'UTM Campaign. (First-touch, session-scoped)',
            examples: ['feature launch', 'discount'],
        },
        $client_session_initial_utm_medium: {
            label: 'Initial UTM Medium',
            description: 'UTM Medium. (First-touch, session-scoped)',
            examples: ['Social', 'Organic', 'Paid', 'Email'],
        },
        $client_session_initial_utm_content: {
            label: 'Initial UTM Source',
            description: 'UTM Source. (First-touch, session-scoped)',
            examples: ['bottom link', 'second button'],
        },
        $client_session_initial_utm_term: {
            label: 'Initial UTM Source',
            description: 'UTM Source. (First-touch, session-scoped)',
            examples: ['free goodies'],
        },
        $network_carrier: {
            label: 'Network Carrier',
            description: 'The network carrier that the user is on.',
            examples: ['cricket', 'telecom'],
        },
        from_background: {
            label: 'From Background',
            description: 'Whether the app was opened for the first time or from the background.',
            examples: ['true', 'false'],
        },
        url: {
            label: 'URL',
            description: 'The deep link URL that the app was opened from.',
            examples: ['https://open.my.app'],
        },
        referring_application: {
            label: 'Referrer Application',
            description: 'The namespace of the app that made the request.',
            examples: ['com.posthog.app'],
        },
        version: {
            label: 'App Version',
            description: 'The version of the app',
            examples: ['1.0.0'],
        },
        previous_version: {
            label: 'App Previous Version',
            description: 'The previous version of the app',
            examples: ['1.0.0'],
        },
        build: {
            label: 'App Build',
            description: 'The build number for the app',
            examples: ['1'],
        },
        previous_build: {
            label: 'App Previous Build',
            description: 'The previous build number for the app',
            examples: ['1'],
        },
        gclid: {
            label: 'Latest gclid',
            description: 'Google Click ID Data from the last time this user was seen.',
        },
        $initial_gclid: {
            label: 'Initial gclid',
            description: 'Google Click ID Data from the first time this user was seen.',
        },
        rdt_cid: {
            label: 'Latest rdt_cid',
            description: 'Reddit Click ID Data from the last time this user was seen.',
        },
        $initial_rdt_cid: {
            label: 'Initial rdt_cid',
            description: 'Reddit Click ID Data from the first time this user was seen.',
        },
        irclid: {
            label: 'Latest irclid',
            description: 'Impact Click ID Data from the last time this user was seen.',
        },
        $initial_irclid: {
            label: 'Initial irclid',
            description: 'Impact Click ID Data from the first time this user was seen.',
        },
        _kx: {
            label: 'Latest _kx',
            description: 'Klaviyo Tracking ID Data from the last time this user was seen.',
        },
        $initial__kx: {
            label: 'Initial _kx',
            description: 'Klaviyo Tracking ID Data from the first time this user was seen.',
        },
        gad_source: {
            label: 'Latest gad_source',
            description: 'Google Ads Source Data from the last time this user was seen.',
        },
        $initial_gad_source: {
            label: 'Initial gad_source',
            description: 'Google Ads Source Data from the first time this user was seen.',
        },
        gclsrc: {
            label: 'Latest gclsrc',
            description: 'Google Click Source Data from the last time this user was seen.',
        },
        $initial_gclsrc: {
            label: 'Initial gclsrc',
            description: 'Google Click Source Data from the first time this user was seen.',
        },
        dclid: {
            label: 'Latest dclid',
            description: 'DoubleClick ID Data from the last time this user was seen.',
        },
        $initial_dclid: {
            label: 'Initial dclid',
            description: 'DoubleClick ID Data from the first time this user was seen.',
        },
        gbraid: {
            label: 'Latest gbraid',
            description: 'Google Ads, web to app Data from the last time this user was seen.',
        },
        $initial_gbraid: {
            label: 'Initial gbraid',
            description: 'Google Ads, web to app Data from the first time this user was seen.',
        },
        wbraid: {
            label: 'Latest wbraid',
            description: 'Google Ads, app to web Data from the last time this user was seen.',
        },
        $initial_wbraid: {
            label: 'Initial wbraid',
            description: 'Google Ads, app to web Data from the first time this user was seen.',
        },
        fbclid: {
            label: 'Latest fbclid',
            description: 'Facebook Click ID Data from the last time this user was seen.',
        },
        $initial_fbclid: {
            label: 'Initial fbclid',
            description: 'Facebook Click ID Data from the first time this user was seen.',
        },
        msclkid: {
            label: 'Latest msclkid',
            description: 'Microsoft Click ID Data from the last time this user was seen.',
        },
        $initial_msclkid: {
            label: 'Initial msclkid',
            description: 'Microsoft Click ID Data from the first time this user was seen.',
        },
        twclid: {
            label: 'Latest twclid',
            description: 'Twitter Click ID Data from the last time this user was seen.',
        },
        $initial_twclid: {
            label: 'Initial twclid',
            description: 'Twitter Click ID Data from the first time this user was seen.',
        },
        li_fat_id: {
            label: 'Latest li_fat_id',
            description: 'LinkedIn First-Party Ad Tracking ID Data from the last time this user was seen.',
        },
        $initial_li_fat_id: {
            label: 'Initial li_fat_id',
            description: 'LinkedIn First-Party Ad Tracking ID Data from the first time this user was seen.',
        },
        mc_cid: {
            label: 'Latest mc_cid',
            description: 'Mailchimp Campaign ID Data from the last time this user was seen.',
        },
        $initial_mc_cid: {
            label: 'Initial mc_cid',
            description: 'Mailchimp Campaign ID Data from the first time this user was seen.',
        },
        igshid: {
            label: 'Latest igshid',
            description: 'Instagram Share ID Data from the last time this user was seen.',
        },
        $initial_igshid: {
            label: 'Initial igshid',
            description: 'Instagram Share ID Data from the first time this user was seen.',
        },
        ttclid: {
            label: 'Latest ttclid',
            description: 'TikTok Click ID Data from the last time this user was seen.',
        },
        $initial_ttclid: {
            label: 'Initial ttclid',
            description: 'TikTok Click ID Data from the first time this user was seen.',
        },
        $is_identified: {
            label: 'Is Identified',
            description: 'When the person was identified',
        },
        $initial_person_info: {
            label: 'Initial Person Info',
            description: 'posthog-js initial person information. used in the $set_once flow',
            system: true,
        },
        $web_vitals_enabled_server_side: {
            label: 'Web vitals enabled server side',
            description: 'Whether web vitals was enabled in remote config',
        },
        $web_vitals_FCP_event: {
            label: 'Web vitals FCP measure event details',
        },
        $web_vitals_FCP_value: {
            label: 'Web vitals FCP value',
        },
        $web_vitals_LCP_event: {
            label: 'Web vitals LCP measure event details',
        },
        $web_vitals_LCP_value: {
            label: 'Web vitals LCP value',
        },
        $web_vitals_INP_event: {
            label: 'Web vitals INP measure event details',
        },
        $web_vitals_INP_value: {
            label: 'Web vitals INP value',
        },
        $web_vitals_CLS_event: {
            label: 'Web vitals CLS measure event details',
        },
        $web_vitals_CLS_value: {
            label: 'Web vitals CLS value',
        },
        $web_vitals_allowed_metrics: {
            label: 'Web vitals allowed metrics',
            description: 'Allowed web vitals metrics config.',
            examples: ['["LCP", "CLS"]'],
            system: true,
        },
        $prev_pageview_last_scroll: {
            label: 'Previous pageview last scroll',
            description: 'posthog-js adds these to the page leave event, they are used in web analytics calculations',
            examples: [0],
        },
        $prev_pageview_id: {
            label: 'Previous pageview ID',
            description: 'posthog-js adds these to the page leave event, they are used in web analytics calculations',
            examples: ['1'],
            system: true,
        },
        $prev_pageview_last_scroll_percentage: {
            label: 'Previous pageview last scroll percentage',
            description: 'posthog-js adds these to the page leave event, they are used in web analytics calculations',
            examples: [0],
        },
        $prev_pageview_max_scroll: {
            examples: [0],
            label: 'Previous pageview max scroll',
            description: 'posthog-js adds these to the page leave event, they are used in web analytics calculations',
        },
        $prev_pageview_max_scroll_percentage: {
            examples: [0],
            label: 'Previous pageview max scroll percentage',
            description: 'posthog-js adds these to the page leave event, they are used in web analytics calculations',
        },
        $prev_pageview_last_content: {
            examples: [0],
            label: 'Previous pageview last content',
            description: 'posthog-js adds these to the page leave event, they are used in web analytics calculations',
        },
        $prev_pageview_last_content_percentage: {
            examples: [0],
            description: 'posthog-js adds these to the page leave event, they are used in web analytics calculations',
            label: 'Previous pageview last content percentage',
        },
        $prev_pageview_max_content: {
            examples: [0],
            description: 'posthog-js adds these to the page leave event, they are used in web analytics calculations',
            label: 'Previous pageview max content',
        },
        $prev_pageview_max_content_percentage: {
            examples: [0],
            description: 'posthog-js adds these to the page leave event, they are used in web analytics calculations',
            label: 'Previous pageview max content percentage',
        },
        $prev_pageview_pathname: {
            examples: ['/pricing', '/about-us/team'],
            description: 'posthog-js adds these to the page leave event, they are used in web analytics calculations',
            label: 'Previous pageview pathname',
        },
        $prev_pageview_duration: {
            examples: [0],
            description: 'posthog-js adds these to the page leave event, they are used in web analytics calculations',
            label: 'Previous pageview duration',
        },
        $surveys_activated: {
            label: 'Surveys Activated',
            description: 'The surveys that were activated for this event.',
        },
        $process_person_profile: {
            label: 'Person Profile processing flag',
            description: 'The setting from an SDK to control whether an event has person processing enabled',
            system: true,
        },
        $dead_clicks_enabled_server_side: {
            label: 'Dead clicks enabled server side',
            description: 'Whether dead clicks were enabled in remote config',
            system: true,
        },
        $dead_click_scroll_delay_ms: {
            label: 'Dead click scroll delay in milliseconds',
            description: 'The delay between a click and the next scroll event',
            system: true,
        },
        $dead_click_mutation_delay_ms: {
            label: 'Dead click mutation delay in milliseconds',
            description: 'The delay between a click and the next mutation event',
            system: true,
        },
        $dead_click_absolute_delay_ms: {
            label: 'Dead click absolute delay in milliseconds',
            description: 'The delay between a click and having seen no activity at all',
            system: true,
        },
        $dead_click_selection_changed_delay_ms: {
            label: 'Dead click selection changed delay in milliseconds',
            description: 'The delay between a click and the next text selection change event',
            system: true,
        },
        $dead_click_last_mutation_timestamp: {
            label: 'Dead click last mutation timestamp',
            description: 'debug signal time of the last mutation seen by dead click autocapture',
            system: true,
        },
        $dead_click_event_timestamp: {
            label: 'Dead click event timestamp',
            description: 'debug signal time of the event that triggered dead click autocapture',
            system: true,
        },
        $dead_click_scroll_timeout: {
            label: 'Dead click scroll timeout',
            description: 'whether the dead click autocapture passed the threshold for waiting for a scroll event',
        },
        $dead_click_mutation_timeout: {
            label: 'Dead click mutation timeout',
            description: 'whether the dead click autocapture passed the threshold for waiting for a mutation event',
            system: true,
        },
        $dead_click_absolute_timeout: {
            label: 'Dead click absolute timeout',
            description: 'whether the dead click autocapture passed the threshold for waiting for any activity',
            system: true,
        },
        $dead_click_selection_changed_timeout: {
            label: 'Dead click selection changed timeout',
            description: 'whether the dead click autocapture passed the threshold for waiting for a text selection change event',
            system: true,
        },
        $ai_base_url: {
            label: 'AI Base URL (LLM)',
            description: 'The base URL of the request made to the LLM API',
            examples: ['https://api.openai.com/v1/'],
        },
        $ai_http_status: {
            label: 'AI HTTP Status (LLM)',
            description: 'The HTTP status code of the request made to the LLM API',
            examples: [200, 429],
        },
        $ai_input: {
            label: 'AI Input (LLM)',
            description: 'The input JSON that was sent to the LLM API',
            examples: ['{"content": "Explain quantum computing in simple terms.", "role": "user"}'],
        },
        $ai_input_tokens: {
            label: 'AI Input Tokens (LLM)',
            description: 'The number of tokens in the input prmopt that was sent to the LLM API',
            examples: [23],
        },
        $ai_output: {
            label: 'AI Output (LLM)',
            description: 'The output JSON that was received from the LLM API',
            examples: ['{"choices": [{"text": "Quantum computing is a type of computing that harnesses the power of quantum mechanics to perform operations on data."}]}'],
        },
        $ai_output_tokens: {
            label: 'AI Output Tokens (LLM)',
            description: 'The number of tokens in the output from the LLM API',
            examples: [23],
        },
        $ai_latency: {
            label: 'AI Latency (LLM)',
            description: 'The latency of the request made to the LLM API, in seconds',
            examples: [1000],
        },
        $ai_model: {
            label: 'AI Model (LLM)',
            description: 'The model used to generate the output from the LLM API',
            examples: ['gpt-4o-mini'],
        },
        $ai_model_parameters: {
            label: 'AI Model Parameters (LLM)',
            description: 'The parameters used to configure the model in the LLM API, in JSON',
            examples: ['{"temperature": 0.5, "max_tokens": 50}'],
        },
        $ai_provider: {
            label: 'AI Provider (LLM)',
            description: 'The provider of the AI model used to generate the output from the LLM API',
            examples: ['openai'],
        },
        $ai_trace_id: {
            label: 'AI Trace ID (LLM)',
            description: 'The trace ID of the request made to the LLM API. Used to group together multiple generations into a single trace',
            examples: ['c9222e05-8708-41b8-98ea-d4a21849e761'],
        },
        $ai_metric_name: {
            label: 'AI Metric Name (LLM)',
            description: 'The name assigned to the metric used to evaluate the LLM trace',
            examples: ['rating', 'accuracy'],
        },
        $ai_metric_value: {
            label: 'AI Metric Value (LLM)',
            description: 'The value assigned to the metric used to evaluate the LLM trace',
            examples: ['negative', '95'],
        },
        $ai_feedback_text: {
            label: 'AI Feedback Text (LLM)',
            description: 'The text provided by the user for feedback on the LLM trace',
            examples: ['"The response was helpful, but it did not use the provided context."'],
        },
        $ai_parent_id: {
            label: 'AI Parent ID (LLM)',
            description: 'The parent span ID of a span or generation, used to group a trace into a tree view',
            examples: ['bdf42359-9364-4db7-8958-c001f28c9255'],
        },
        $ai_span_id: {
            label: 'AI Span ID (LLM)',
            description: 'The unique identifier for a LLM trace, generation, or span.',
            examples: ['bdf42359-9364-4db7-8958-c001f28c9255'],
        },
    },
    session_properties: {
        $session_duration: {
            label: 'Session duration',
            description: 'The duration of the session being tracked in seconds.',
            examples: ['30', '146', '2'],
            type: 'Numeric',
        },
        $start_timestamp: {
            label: 'Start timestamp',
            description: 'The timestamp of the first event from this session.',
            examples: ['2023-05-20T15:30:00Z'],
            type: 'DateTime',
        },
        $end_timestamp: {
            label: 'End timestamp',
            description: 'The timestamp of the last event from this session',
            examples: ['2023-05-20T16:30:00Z'],
            type: 'DateTime',
        },
        $entry_current_url: {
            label: 'Entry URL',
            description: 'The first URL visited in this session',
            examples: ['https://example.com/interesting-article?parameter=true'],
            type: 'String',
        },
        $entry_pathname: {
            label: 'Entry pathname',
            description: 'The first pathname visited in this session',
            examples: ['/interesting-article?parameter=true'],
            type: 'String',
        },
        $end_current_url: {
            label: 'Entry URL',
            description: 'The first URL visited in this session',
            examples: ['https://example.com/interesting-article?parameter=true'],
            type: 'String',
        },
        $end_pathname: {
            label: 'Entry pathname',
            description: 'The first pathname visited in this session',
            examples: ['/interesting-article?parameter=true'],
            type: 'String',
        },
        $exit_current_url: {
            label: 'Exit URL',
            description: 'The last URL visited in this session',
            examples: ['https://example.com/interesting-article?parameter=true'],
            type: 'String',
        },
        $exit_pathname: {
            label: 'Exit pathname',
            description: 'The last pathname visited in this session',
            examples: ['/interesting-article?parameter=true'],
            type: 'String',
        },
        $pageview_count: {
            label: 'Pageview count',
            description: 'The number of page view events in this session',
            examples: ['123'],
            type: 'Numeric',
        },
        $autocapture_count: {
            label: 'Autocapture count',
            description: 'The number of autocapture events in this session',
            examples: ['123'],
            type: 'Numeric',
        },
        $screen_count: {
            label: 'Screen count',
            description: 'The number of screen events in this session',
            examples: ['123'],
            type: 'Numeric',
        },
        $channel_type: {
            label: 'Channel type',
            description: 'What type of acquisition channel this traffic came from.',
            examples: ['Paid Search', 'Organic Video', 'Direct'],
            type: 'String',
        },
        $is_bounce: {
            label: 'Is bounce',
            description: 'Whether the session was a bounce.',
            examples: ['true', 'false'],
            type: 'Boolean',
        },
        $last_external_click_url: {
            label: 'Last external click URL',
            description: 'The last external URL clicked in this session.',
            examples: ['https://example.com/interesting-article?parameter=true'],
        },
        $vitals_lcp: {
            label: 'Web vitals LCP',
            description: 'The time it took for the Largest Contentful Paint on the page. This captures the perceived load time of the page, and measure how long it took for the main content of the page to be visible to users.',
            examples: ['2.2'],
        },
        $entry_utm_source: {
            label: 'Entry UTM Source',
            description: 'UTM source tag. Data from the first event in this session.',
            examples: ['Google', 'Bing', 'Twitter', 'Facebook'],
        },
        $entry_utm_medium: {
            label: 'Entry UTM Medium',
            description: 'UTM medium tag. Data from the first event in this session.',
            examples: ['Social', 'Organic', 'Paid', 'Email'],
        },
        $entry_utm_campaign: {
            label: 'Entry UTM Campaign',
            description: 'UTM campaign tag. Data from the first event in this session.',
            examples: ['feature launch', 'discount'],
        },
        $entry_utm_content: {
            label: 'Entry UTM Content',
            description: 'UTM content tag. Data from the first event in this session.',
            examples: ['bottom link', 'second button'],
        },
        $entry_utm_term: {
            label: 'Entry UTM Term',
            description: 'UTM term tag. Data from the first event in this session.',
            examples: ['free goodies'],
        },
        $entry_referring_domain: {
            label: 'Entry Referring Domain',
            description: 'Domain of where the user came from. Data from the first event in this session.',
            examples: ['google.com', 'facebook.com'],
        },
        $entry_gclid: {
            label: 'Entry gclid',
            description: 'Google Click ID Data from the first event in this session.',
        },
        $entry_rdt_cid: {
            label: 'Entry rdt_cid',
            description: 'Reddit Click ID Data from the first event in this session.',
        },
        $entry_irclid: {
            label: 'Entry irclid',
            description: 'Impact Click ID Data from the first event in this session.',
        },
        $entry__kx: {
            label: 'Entry _kx',
            description: 'Klaviyo Tracking ID Data from the first event in this session.',
        },
        $entry_gad_source: {
            label: 'Entry gad_source',
            description: 'Google Ads Source Data from the first event in this session.',
        },
        $entry_gclsrc: {
            label: 'Entry gclsrc',
            description: 'Google Click Source Data from the first event in this session.',
        },
        $entry_dclid: {
            label: 'Entry dclid',
            description: 'DoubleClick ID Data from the first event in this session.',
        },
        $entry_gbraid: {
            label: 'Entry gbraid',
            description: 'Google Ads, web to app Data from the first event in this session.',
        },
        $entry_wbraid: {
            label: 'Entry wbraid',
            description: 'Google Ads, app to web Data from the first event in this session.',
        },
        $entry_fbclid: {
            label: 'Entry fbclid',
            description: 'Facebook Click ID Data from the first event in this session.',
        },
        $entry_msclkid: {
            label: 'Entry msclkid',
            description: 'Microsoft Click ID Data from the first event in this session.',
        },
        $entry_twclid: {
            label: 'Entry twclid',
            description: 'Twitter Click ID Data from the first event in this session.',
        },
        $entry_li_fat_id: {
            label: 'Entry li_fat_id',
            description: 'LinkedIn First-Party Ad Tracking ID Data from the first event in this session.',
        },
        $entry_mc_cid: {
            label: 'Entry mc_cid',
            description: 'Mailchimp Campaign ID Data from the first event in this session.',
        },
        $entry_igshid: {
            label: 'Entry igshid',
            description: 'Instagram Share ID Data from the first event in this session.',
        },
        $entry_ttclid: {
            label: 'Entry ttclid',
            description: 'TikTok Click ID Data from the first event in this session.',
        },
    },
    groups: {
        $group_key: {
            label: 'Group Key',
            description: 'Specified group key',
        },
    },
    replay: {
        snapshot_source: {
            label: 'Platform',
            description: 'Platform the session was recorded on',
            examples: ['web', 'mobile'],
        },
        console_log_level: {
            label: 'Log level',
            description: 'Level of console logs captured',
            examples: ['info', 'warn', 'error'],
        },
        console_log_query: {
            label: 'Console log',
            description: 'Text of console logs captured',
        },
        visited_page: {
            label: 'Visited page',
            description: 'URL a user visited during their session',
        },
        click_count: {
            label: 'Clicks',
            description: 'Number of clicks during the session',
        },
        keypress_count: {
            label: 'Key presses',
            description: 'Number of key presses during the session',
        },
        console_error_count: {
            label: 'Errors',
            description: 'Number of console errors during the session',
        },
    },
    log_entries: {
        level: {
            label: 'Console log level',
            description: 'Level of the ',
            examples: ['info', 'warn', 'error'],
        },
        message: {
            label: 'Console log message',
            description: 'The contents of the log message',
        },
    },
};

export const PROPERTY_KEYS = Object.keys(CORE_FILTER_DEFINITIONS_BY_GROUP.event_properties);
