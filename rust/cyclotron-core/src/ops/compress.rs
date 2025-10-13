use common_compression::{compress_data, CompressionFormat};

use crate::{error::QueueError, types::Bytes};
use common_metrics::inc;

const DECOMPRESS_METRICS_KEY: &str = "decompress_vm_state";
const COMPRESS_METRICS_KEY: &str = "compress_vm_state";

// this doesn't return an error as we expect errors during the transition
// to compressed vm_state. Returns input buffer and assumes not compressed on fail
pub fn decompress_vm_state(maybe_compressed: Option<Bytes>) -> Option<Bytes> {
    match &maybe_compressed {
        Some(in_buffer) => {
            // Use common compression library with multi-format support
            match common_compression::decompress_data(in_buffer) {
                Ok(decompressed_str) => {
                    inc(
                        DECOMPRESS_METRICS_KEY,
                        &[("result".to_string(), "success".to_string())],
                        1,
                    );
                    Some(decompressed_str.into_bytes())
                }
                Err(_) => {
                    inc(
                        DECOMPRESS_METRICS_KEY,
                        &[("result".to_string(), "fail_or_no_op".to_string())],
                        1,
                    );
                    maybe_compressed
                }
            }
        }
        _ => {
            inc(
                DECOMPRESS_METRICS_KEY,
                &[("result".to_string(), "empty_buffer".to_string())],
                1,
            );
            maybe_compressed
        }
    }
}

// returns an error as on the encode side, this would represent corrupted data
pub fn compress_vm_state(uncompressed: Option<Bytes>) -> Result<Option<Bytes>, QueueError> {
    if let Some(in_buffer) = &uncompressed {
        if in_buffer.is_empty() {
            inc(
                COMPRESS_METRICS_KEY,
                &[("result".to_string(), "empty_buffer".to_string())],
                1,
            );
            return Ok(uncompressed);
        }

        // Use common compression library with gzip (maintaining backward compatibility)
        match compress_data(in_buffer, CompressionFormat::Gzip) {
            Ok(compressed) => {
                inc(
                    COMPRESS_METRICS_KEY,
                    &[("result".to_string(), "success".to_string())],
                    1,
                );
                Ok(Some(compressed))
            }
            Err(e) => {
                inc(
                    COMPRESS_METRICS_KEY,
                    &[("result".to_string(), "failed".to_string())],
                    1,
                );
                Err(QueueError::CompressionError(e.to_string()))
            }
        }
    } else {
        Ok(uncompressed)
    }
}

#[cfg(test)]
pub mod test {
    use super::{compress_vm_state, decompress_vm_state};
    use crate::types::Bytes;

    #[test]
    fn test_compress_decompress_json() {
        let payload = Some(Vec::from(br#"{"foo": "bar", "hog": "function"}"#));
        perform_compression_decompression_test(payload);
    }

    #[test]
    fn test_compress_decompress_vm_state() {
        let payload = Some(Vec::from(VM_STATE_PAYLOAD));
        perform_compression_decompression_test(payload);
    }

    #[test]
    fn test_compress_decompress_empty_buffer_no_ops() {
        let payload = Some(Vec::new());
        perform_compression_decompression_test(payload);
    }

    #[test]
    fn test_compress_decompress_none_no_ops() {
        let compressed = compress_vm_state(None);
        assert!(compressed.is_ok());

        let result = decompress_vm_state(None);
        assert!(result.is_none());
    }

    #[test]
    fn test_corrupt_compressed_payload_decompresses_as_no_op() {
        let payload = Some(Vec::from(br#"{"foo": 1, "bar": false}"#));
        let compressed = compress_vm_state(payload.clone());
        assert!(compressed.is_ok());

        // corrupt the payload and attempt to decompress it
        let mut buf = compressed.unwrap().unwrap();
        buf[0] = 0;
        buf[1] = 0;

        // decompression should fail silently, returning the input buffer
        let result = decompress_vm_state(Some(buf.clone()));
        assert!(result.is_some());
        assert_eq!(result.unwrap(), buf);
    }

    #[test]
    fn test_decompressing_uncompressed_buffer_no_ops() {
        let payload = Some(Vec::from(br#"{"foo": 1, "bar": false}"#));

        // decompression should fail silently, returning the input buffer
        let result = decompress_vm_state(payload.clone());
        assert!(result.is_some());
        assert!(result == payload);
    }

    fn perform_compression_decompression_test(payload: Option<Bytes>) {
        let compressed = compress_vm_state(payload.clone());
        assert!(compressed.is_ok());

        let result = decompress_vm_state(compressed.unwrap());
        assert!(result.is_some());
        assert_eq!(result.unwrap(), payload.unwrap());
    }

    const VM_STATE_PAYLOAD: &[u8; 6194]= br#"{"id":"00000000-0000-0000-0000-000000000000","globals":{"project":{"id":44444,"name":"test fixture","url":"https://us.posthog.com/project/44444"},"event":{"uuid":"00000000-0000-0000-0000-000000000000","event":"$autocapture","elements_chain":"span:text=\"Awesome Site\"nth-child=\"2\"nth-of-type=\"1\"href=\"/as\"attr__style=\"display: flex; align-items: center; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; flex: 1 1 0%;\"attr__href=\"/as\";button.rt-BaseButton.rt-Button.rt-high-contrast.rt-r-size-2.rt-reset.rt-variant-ghost:text=\"Awesome Site\"nth-child=\"1\"nth-of-type=\"1\"attr__data-accent-color=\"gray\"attr__class=\"rt-reset rt-BaseButton rt-r-size-2 rt-variant-ghost rt-high-contrast rt-Button\"attr__style=\"width: 100%; justify-content: flex-start; gap: var(--space-2);\";a:nth-child=\"3\"nth-of-type=\"3\"href=\"as\"attr__data-discover=\"true\"attr__href=\"as\";div.rt-Flex.rt-r-fd-column.rt-r-fg-0.rt-r-gap-2.rt-r-h.rt-r-overflow-hidden.rt-r-p-2.rt-r-w:nth-child=\"2\"nth-of-type=\"1\"attr__class=\"rt-Flex rt-r-fd-column rt-r-gap-2 rt-r-p-2 rt-r-w rt-r-h rt-r-overflow-hidden rt-r-fg-0\"attr__style=\"--width: 100%; --height: 100%;\";div.rt-Flex.rt-r-fd-column.rt-r-gap-0.rt-r-w:nth-child=\"3\"nth-of-type=\"3\"attr__class=\"rt-Flex rt-r-fd-column rt-r-gap-0 rt-r-w\"attr__style=\"--width: 100%;\";div.rt-Flex.rt-r-fd-column.rt-r-gap-4:nth-child=\"2\"nth-of-type=\"2\"attr__class=\"rt-Flex rt-r-fd-column rt-r-gap-4\";div.rt-Flex.rt-r-fd-column.rt-r-gap-2.rt-r-p-3.rt-r-w:nth-child=\"1\"nth-of-type=\"1\"attr__class=\"rt-Flex rt-r-fd-column rt-r-gap-2 rt-r-p-3 rt-r-w\"attr__style=\"--width: 190px; border-right: 1px solid var(--gray-a6);\";div:nth-child=\"1\"nth-of-type=\"1\"attr__style=\"position: fixed; z-index: 5; background-color: var(--color-background); height: 100vh; left: 0%;\";div.md:rt-r-display-none.rt-Box.rt-r-display-block:nth-child=\"1\"nth-of-type=\"1\"attr__class=\"rt-Box rt-r-display-block md:rt-r-display-none\";div.rt-Flex.rt-r-gap-0:nth-child=\"2\"nth-of-type=\"1\"attr__class=\"rt-Flex rt-r-gap-0\";div.radix-themes:nth-child=\"8\"nth-of-type=\"1\"attr__data-is-root-theme=\"true\"attr__data-accent-color=\"green\"attr__data-gray-color=\"sage\"attr__data-has-background=\"true\"attr__data-panel-background=\"translucent\"attr__data-radius=\"medium\"attr__data-scaling=\"100%\"attr__style=\"width:100%\"attr__class=\"radix-themes\";body:nth-child=\"2\"nth-of-type=\"1\"attr__style=\"transition: margin 250ms; margin-top: 0px;\"","distinct_id":"00000000-0000-0000-0000-000000000000","properties":{"$process_person_profile":false,"$session_recording_canvas_recording":{},"$os":"iOS","$sdk_debug_retry_queue_size":0,"$replay_sample_rate":null,"$session_entry_pathname":"/","$pageview_id":"00000000-0000-0000-0000-000000000000","$viewport_width":402,"$device_type":"Mobile","distinct_id":"00000000-0000-0000-0000-000000000000","$el_text":"Awesome Site","$session_recording_masking":null,"$session_id":"00000000-0000-0000-0000-000000000000","$pathname":"/","$is_identified":false,"$browser_version":18.3,"$web_vitals_enabled_server_side":true,"$event_type":"click","$initial_person_info":{"r":"$direct","u":"https://some.example.com/?posts%5Bquery%5D=&posts%5Bpage%5D=1"},"$web_vitals_allowed_metrics":null,"$lib_version":"1.230.4","$timezone":"America/New_York","$current_url":"https://some.example.com","$window_id":"00000000-0000-0000-0000-000000000000","$browser_language_prefix":"en","$session_entry_referrer":"$direct","$recording_status":"active","$screen_height":896,"$replay_script_config":null,"$session_recording_network_payload_capture":{"capturePerformance":{"network_timing":true,"web_vitals":true,"web_vitals_allowed_metrics":null}},"$session_entry_referring_domain":"$direct","$lib":"web","$os_version":"18.3.1","$active_feature_flags":[],"$browser":"Mobile Safari","$feature_flag_payloads":{},"token":"redacted","$replay_minimum_duration":null,"$time":1741912549.921,"$sdk_debug_replay_internal_buffer_size":9446,"$dead_clicks_enabled_server_side":false,"$exception_capture_enabled_server_side":false,"$referring_domain":"$direct","$raw_user_agent":"Mozilla/5.0 (iPhone; CPU iPhone OS 18_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 Mobile/15E148 Safari/604.1","$browser_language":"en-US","$viewport_height":673,"$host":"some.example.com","$feature_flag_request_id":"00000000-0000-0000-0000-000000000000","$session_entry_url":"https://some.example.com/?posts%5Bquery%5D=&posts%5Bpage%5D=1","$device":"iPhone","$console_log_recording_enabled_server_side":true,"$session_recording_start_reason":"recording_initialized","$insert_id":"redacted","$screen_width":414,"$device_id":"00000000-0000-0000-0000-000000000000","$referrer":"$direct","$configured_session_timeout_ms":1800000,"$session_entry_host":"some.example.com","$sdk_debug_replay_internal_buffer_length":9,"$ce_version":1,"$autocapture_disabled_server_side":false,"$lib_rate_limit_remaining_tokens":99,"$ip":"10.0.0.1","$sent_at":"2025-03-14T00:35:52.922Z","$geoip_city_name":"Springfield","$geoip_country_name":"United States","$geoip_country_code":"US","$geoip_continent_name":"North America","$geoip_continent_code":"NA","$geoip_postal_code":"00000","$geoip_latitude":28.1234,"$geoip_longitude":-81.1234,"$geoip_accuracy_radius":5,"$geoip_time_zone":"America/New_York","$geoip_subdivision_1_code":"FL","$geoip_subdivision_1_name":"Florida","$transformations_succeeded":["GeoIP (00000000-0000-0000-0000-000000000000)"],"$transformations_failed":[]},"timestamp":"2025-03-14T00:35:49.962Z","url":"https://us.posthog.com/project/44444/events/01959214-2a21-7cb4-9bc2-b347c93bec22/2025-03-14T00%3A35%3A49.962Z"},"person":{"id":"00000000-0000-0000-0000-000000000000","properties":{},"name":"00000000-0000-0000-0000-000000000000","url":"https://us.posthog.com/project/44444/person/00000000-0000-0000-0000-000000000000"},"groups":{},"source":{"name":"Acme, Inc.","url":"https://us.posthog.com/project/44444/pipeline/destinations/hog-00000000-0000-0000-0000-000000000000/configuration/"},"inputs":{"email":null,"api_key":"redacted"}},"teamId":44444,"queue":"hog","priority":1,"timings":[],"hogFunctionId":"00000000-0000-0000-0000-000000000000"}"#;
}
