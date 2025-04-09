use std::sync::Arc;

use chrono::{Duration, Utc};
use common::{assert_job_matches_init, create_new_job, dates_match};
use cyclotron_core::{Job, JobState, QueueManager, Worker, WorkerConfig};
use sqlx::PgPool;
use uuid::Uuid;

mod common;

const VM_STATE_PAYLOAD: &[u8; 6194]= br#"{"id":"00000000-0000-0000-0000-000000000000","globals":{"project":{"id":44444,"name":"test fixture","url":"https://us.posthog.com/project/44444"},"event":{"uuid":"00000000-0000-0000-0000-000000000000","event":"$autocapture","elements_chain":"span:text=\"Awesome Site\"nth-child=\"2\"nth-of-type=\"1\"href=\"/as\"attr__style=\"display: flex; align-items: center; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; flex: 1 1 0%;\"attr__href=\"/as\";button.rt-BaseButton.rt-Button.rt-high-contrast.rt-r-size-2.rt-reset.rt-variant-ghost:text=\"Awesome Site\"nth-child=\"1\"nth-of-type=\"1\"attr__data-accent-color=\"gray\"attr__class=\"rt-reset rt-BaseButton rt-r-size-2 rt-variant-ghost rt-high-contrast rt-Button\"attr__style=\"width: 100%; justify-content: flex-start; gap: var(--space-2);\";a:nth-child=\"3\"nth-of-type=\"3\"href=\"as\"attr__data-discover=\"true\"attr__href=\"as\";div.rt-Flex.rt-r-fd-column.rt-r-fg-0.rt-r-gap-2.rt-r-h.rt-r-overflow-hidden.rt-r-p-2.rt-r-w:nth-child=\"2\"nth-of-type=\"1\"attr__class=\"rt-Flex rt-r-fd-column rt-r-gap-2 rt-r-p-2 rt-r-w rt-r-h rt-r-overflow-hidden rt-r-fg-0\"attr__style=\"--width: 100%; --height: 100%;\";div.rt-Flex.rt-r-fd-column.rt-r-gap-0.rt-r-w:nth-child=\"3\"nth-of-type=\"3\"attr__class=\"rt-Flex rt-r-fd-column rt-r-gap-0 rt-r-w\"attr__style=\"--width: 100%;\";div.rt-Flex.rt-r-fd-column.rt-r-gap-4:nth-child=\"2\"nth-of-type=\"2\"attr__class=\"rt-Flex rt-r-fd-column rt-r-gap-4\";div.rt-Flex.rt-r-fd-column.rt-r-gap-2.rt-r-p-3.rt-r-w:nth-child=\"1\"nth-of-type=\"1\"attr__class=\"rt-Flex rt-r-fd-column rt-r-gap-2 rt-r-p-3 rt-r-w\"attr__style=\"--width: 190px; border-right: 1px solid var(--gray-a6);\";div:nth-child=\"1\"nth-of-type=\"1\"attr__style=\"position: fixed; z-index: 5; background-color: var(--color-background); height: 100vh; left: 0%;\";div.md:rt-r-display-none.rt-Box.rt-r-display-block:nth-child=\"1\"nth-of-type=\"1\"attr__class=\"rt-Box rt-r-display-block md:rt-r-display-none\";div.rt-Flex.rt-r-gap-0:nth-child=\"2\"nth-of-type=\"1\"attr__class=\"rt-Flex rt-r-gap-0\";div.radix-themes:nth-child=\"8\"nth-of-type=\"1\"attr__data-is-root-theme=\"true\"attr__data-accent-color=\"green\"attr__data-gray-color=\"sage\"attr__data-has-background=\"true\"attr__data-panel-background=\"translucent\"attr__data-radius=\"medium\"attr__data-scaling=\"100%\"attr__style=\"width:100%\"attr__class=\"radix-themes\";body:nth-child=\"2\"nth-of-type=\"1\"attr__style=\"transition: margin 250ms; margin-top: 0px;\"","distinct_id":"00000000-0000-0000-0000-000000000000","properties":{"$process_person_profile":false,"$session_recording_canvas_recording":{},"$os":"iOS","$sdk_debug_retry_queue_size":0,"$replay_sample_rate":null,"$session_entry_pathname":"/","$pageview_id":"00000000-0000-0000-0000-000000000000","$viewport_width":402,"$device_type":"Mobile","distinct_id":"00000000-0000-0000-0000-000000000000","$el_text":"Awesome Site","$session_recording_masking":null,"$session_id":"00000000-0000-0000-0000-000000000000","$pathname":"/","$is_identified":false,"$browser_version":18.3,"$web_vitals_enabled_server_side":true,"$event_type":"click","$initial_person_info":{"r":"$direct","u":"https://some.example.com/?posts%5Bquery%5D=&posts%5Bpage%5D=1"},"$web_vitals_allowed_metrics":null,"$lib_version":"1.230.4","$timezone":"America/New_York","$current_url":"https://some.example.com","$window_id":"00000000-0000-0000-0000-000000000000","$browser_language_prefix":"en","$session_entry_referrer":"$direct","$recording_status":"active","$screen_height":896,"$replay_script_config":null,"$session_recording_network_payload_capture":{"capturePerformance":{"network_timing":true,"web_vitals":true,"web_vitals_allowed_metrics":null}},"$session_entry_referring_domain":"$direct","$lib":"web","$os_version":"18.3.1","$active_feature_flags":[],"$browser":"Mobile Safari","$feature_flag_payloads":{},"token":"redacted","$replay_minimum_duration":null,"$time":1741912549.921,"$sdk_debug_replay_internal_buffer_size":9446,"$dead_clicks_enabled_server_side":false,"$exception_capture_enabled_server_side":false,"$referring_domain":"$direct","$raw_user_agent":"Mozilla/5.0 (iPhone; CPU iPhone OS 18_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 Mobile/15E148 Safari/604.1","$browser_language":"en-US","$viewport_height":673,"$host":"some.example.com","$feature_flag_request_id":"00000000-0000-0000-0000-000000000000","$session_entry_url":"https://some.example.com/?posts%5Bquery%5D=&posts%5Bpage%5D=1","$device":"iPhone","$console_log_recording_enabled_server_side":true,"$session_recording_start_reason":"recording_initialized","$insert_id":"redacted","$screen_width":414,"$device_id":"00000000-0000-0000-0000-000000000000","$referrer":"$direct","$configured_session_timeout_ms":1800000,"$session_entry_host":"some.example.com","$sdk_debug_replay_internal_buffer_length":9,"$ce_version":1,"$autocapture_disabled_server_side":false,"$lib_rate_limit_remaining_tokens":99,"$ip":"10.0.0.1","$sent_at":"2025-03-14T00:35:52.922Z","$geoip_city_name":"Springfield","$geoip_country_name":"United States","$geoip_country_code":"US","$geoip_continent_name":"North America","$geoip_continent_code":"NA","$geoip_postal_code":"00000","$geoip_latitude":28.1234,"$geoip_longitude":-81.1234,"$geoip_accuracy_radius":5,"$geoip_time_zone":"America/New_York","$geoip_subdivision_1_code":"FL","$geoip_subdivision_1_name":"Florida","$transformations_succeeded":["GeoIP (00000000-0000-0000-0000-000000000000)"],"$transformations_failed":[]},"timestamp":"2025-03-14T00:35:49.962Z","url":"https://us.posthog.com/project/44444/events/01959214-2a21-7cb4-9bc2-b347c93bec22/2025-03-14T00%3A35%3A49.962Z"},"person":{"id":"00000000-0000-0000-0000-000000000000","properties":{},"name":"00000000-0000-0000-0000-000000000000","url":"https://us.posthog.com/project/44444/person/00000000-0000-0000-0000-000000000000"},"groups":{},"source":{"name":"Acme, Inc.","url":"https://us.posthog.com/project/44444/pipeline/destinations/hog-00000000-0000-0000-0000-000000000000/configuration/"},"inputs":{"email":null,"api_key":"redacted"}},"teamId":44444,"queue":"hog","priority":1,"timings":[],"hogFunctionId":"00000000-0000-0000-0000-000000000000"}"#;

// I know this should be a bunch of tests, but for hacking together stuff right now, it'll do
#[sqlx::test(migrations = "./migrations")]
async fn test_queue(db: PgPool) {
    let manager = QueueManager::from_pool(db.clone(), true, true); // defaults to vm_state compression; for testing only!
    let mut worker = Worker::from_pool(db, Default::default());
    worker.max_buffered = 0; // No buffering for testing, flush immediately

    let job_1 = create_new_job();
    let mut job_2 = create_new_job();

    job_2.priority = 2; // Lower priority jobs should be returned second

    let queue_name = job_1.queue_name.clone();

    manager
        .create_job(job_1.clone())
        .await
        .expect("failed to create job");
    manager
        .create_job(job_2.clone())
        .await
        .expect("failed to create job");

    let jobs = worker
        .dequeue_jobs(&queue_name, 2)
        .await
        .expect("failed to dequeue job");

    assert_eq!(jobs.len(), 2);
    // This also assert that the ordering is correct in terms of priority
    assert_job_matches_init(&jobs[0], &job_1);
    assert_job_matches_init(&jobs[1], &job_2);

    // Now we can re-queue these jobs (imagine we had done work)
    worker
        .set_state(jobs[0].id, JobState::Available)
        .expect("failed to set state");
    worker
        .set_state(jobs[1].id, JobState::Available)
        .expect("failed to set state");

    // Flush the two jobs, having made no other changes, then assert we can re-dequeue them
    let handle_1 = worker.release_job(jobs[0].id, None);
    let handle_2 = worker.release_job(jobs[1].id, None);

    worker.force_flush().await.unwrap();
    handle_1.await.unwrap();
    handle_2.await.unwrap();

    let jobs = worker
        .dequeue_jobs(&queue_name, 2)
        .await
        .expect("failed to dequeue job");

    assert_eq!(jobs.len(), 2);
    assert_job_matches_init(&jobs[0], &job_1);
    assert_job_matches_init(&jobs[1], &job_2);

    // Re-queue them again
    worker
        .set_state(jobs[0].id, JobState::Available)
        .expect("failed to set state");
    worker
        .set_state(jobs[1].id, JobState::Available)
        .expect("failed to set state");

    let handle_1 = worker.release_job(jobs[0].id, None);
    let handle_2 = worker.release_job(jobs[1].id, None);

    worker.force_flush().await.unwrap();
    handle_1.await.unwrap();
    handle_2.await.unwrap();

    // Spin up two tasks to race on dequeuing, and assert at most 2 jobs are dequeued
    let worker: Arc<Worker> = Arc::new(worker);
    let moved = worker.clone();
    let queue_name_moved = queue_name.clone();
    let fut_1 = async move {
        moved
            .dequeue_jobs(&queue_name_moved, 2)
            .await
            .expect("failed to dequeue job")
    };
    let moved = worker.clone();
    let queue_name_moved = queue_name.clone();
    let fut_2 = async move {
        moved
            .dequeue_jobs(&queue_name_moved, 2)
            .await
            .expect("failed to dequeue job")
    };

    let (jobs_1, jobs_2) = tokio::join!(fut_1, fut_2);
    assert_eq!(jobs_1.len() + jobs_2.len(), 2);

    let jobs = jobs_1
        .into_iter()
        .chain(jobs_2.into_iter())
        .collect::<Vec<_>>();

    // And now, any subsequent dequeues will return no jobs
    let empty = worker
        .dequeue_jobs(&queue_name, 2)
        .await
        .expect("failed to dequeue job");
    assert_eq!(empty.len(), 0);

    // If we try to flush a job without setting what it's next state will be,
    // we should get an error. We don't bother forcing a flush here, because
    // the worker should return a handle that immediately resolves.
    assert!(worker.release_job(jobs[0].id, None).await.is_err());

    // Trying to flush a job with the state "running" should also fail
    worker
        .set_state(jobs[1].id, JobState::Running)
        .expect("failed to set state");
    assert!(worker.release_job(jobs[1].id, None).await.is_err());

    // But if we properly set the state to completed or failed, now we can flush
    worker
        .set_state(jobs[0].id, JobState::Completed)
        .expect("failed to set state");
    worker
        .set_state(jobs[1].id, JobState::Failed)
        .expect("failed to set state");

    let handle_1 = worker.release_job(jobs[0].id, None);
    let handle_2 = worker.release_job(jobs[1].id, None);

    worker.force_flush().await.expect("failed to flush job");
    handle_1.await.unwrap();
    handle_2.await.unwrap();

    // And now, any subsequent dequeues will return no jobs (because these jobs are finished)
    let empty = worker
        .dequeue_jobs(&queue_name, 2)
        .await
        .expect("failed to dequeue job");
    assert_eq!(empty.len(), 0);

    // Now, lets check that we can set every variable on a job

    // Set up some initial values
    let now = Utc::now();
    let mut job = create_new_job();
    job.queue_name = "test".to_string();
    job.priority = 0;
    job.scheduled = now - Duration::minutes(2);
    job.vm_state = None;
    job.parameters = None;
    job.metadata = None;

    // Queue the job
    manager
        .create_job(job.clone())
        .await
        .expect("failed to create job");

    // Then dequeue it
    let job = worker
        .dequeue_jobs("test", 1)
        .await
        .expect("failed to dequeue job")
        .pop()
        .expect("failed to dequeue job");

    // Set everything we're able to set, including state to available, so we can dequeue it again
    worker
        .set_state(job.id, JobState::Available)
        .expect("failed to set state");
    worker
        .set_queue(job.id, "test_2")
        .expect("failed to set queue");
    worker
        .set_priority(job.id, 1)
        .expect("failed to set priority");
    worker
        .set_scheduled_at(job.id, now - Duration::minutes(10))
        .expect("failed to set scheduled_at");
    worker
        .set_vm_state(job.id, Some("test".as_bytes().to_owned()))
        .expect("failed to set vm_state");
    worker
        .set_parameters(job.id, Some("test".as_bytes().to_owned()))
        .expect("failed to set parameters");
    worker
        .set_blob(job.id, Some("test".as_bytes().to_owned()))
        .expect("failed to set blob");
    worker
        .set_metadata(job.id, Some("test".as_bytes().to_owned()))
        .expect("failed to set metadata");

    // Flush the job
    let handle = worker.release_job(job.id, None);

    worker.force_flush().await.unwrap();
    handle.await.unwrap();
    // Then dequeue it again (this time being sure to grab the vm state too)
    let job = worker
        .dequeue_with_vm_state("test_2", 1)
        .await
        .expect("failed to dequeue job")
        .pop()
        .expect("failed to dequeue job");

    // And every value should be the updated one
    assert_eq!(job.queue_name, "test_2");
    assert_eq!(job.priority, 1);
    assert!(dates_match(&job.scheduled, &(now - Duration::minutes(10))),);
    assert_eq!(job.vm_state, Some("test".as_bytes().to_owned()));
    assert_eq!(job.parameters, Some("test".as_bytes().to_owned()));
    assert_eq!(job.metadata, Some("test".as_bytes().to_owned()));
}

#[sqlx::test(migrations = "./migrations")]
pub async fn test_bulk_insert(db: PgPool) {
    let worker = Worker::from_pool(db.clone(), Default::default());
    let manager = QueueManager::from_pool(db.clone(), true, false);

    let job_template = create_new_job();

    let jobs = (0..100)
        .map(|_| {
            let mut job = job_template.clone();
            job.function_id = Some(Uuid::now_v7());
            job
        })
        .collect::<Vec<_>>();

    manager
        .bulk_create_jobs(jobs)
        .await
        .expect("failed to bulk insert jobs");

    let dequeue_jobs = worker
        .dequeue_jobs(&job_template.queue_name, 100)
        .await
        .expect("failed to dequeue job");

    assert_eq!(dequeue_jobs.len(), 100);
}

#[sqlx::test(migrations = "./migrations")]
pub async fn test_bulk_insert_copy_from_with_binary_nulls(db: PgPool) {
    let worker = Worker::from_pool(db.clone(), Default::default());
    let manager = QueueManager::from_pool(db.clone(), false, true);

    let job_template = create_new_job();

    let jobs = (0..1000)
        .map(|_| {
            let mut job = job_template.clone();
            job.function_id = Some(Uuid::now_v7());

            // all BYTEA fields will be None, and record as NULLs

            job
        })
        .collect::<Vec<_>>();

    manager
        .bulk_create_jobs(jobs)
        .await
        .expect("failed to bulk insert jobs");

    let results = worker
        .dequeue_jobs(&job_template.queue_name, 100)
        .await
        .expect("failed to dequeue job");

    assert_eq!(results.len(), 100);

    for result in results {
        assert!(result.function_id.is_some());
        let fid = result.function_id.unwrap().to_string();
        assert!(Uuid::parse_str(&fid).is_ok());

        assert!(result.vm_state.is_none());
        assert!(result.metadata.is_none());
        assert!(result.parameters.is_none());
        assert!(result.blob.is_none());
    }
}

#[sqlx::test(migrations = "./migrations")]
pub async fn test_bulk_insert_copy_from_with_binary_blobs(db: PgPool) {
    let worker = Worker::from_pool(db.clone(), Default::default());
    let manager = QueueManager::from_pool(db.clone(), false, true);

    let job_template = create_new_job();

    let jobs = (0..100)
        .map(|_| {
            let mut job = job_template.clone();
            job.function_id = Some(Uuid::now_v7());

            // populate fields that map to Postgres BYTEA columns
            job.vm_state = Some(VM_STATE_PAYLOAD.to_vec());
            job.metadata = Some(VM_STATE_PAYLOAD.to_vec());
            job.parameters = Some(VM_STATE_PAYLOAD.to_vec());
            job.blob = Some(VM_STATE_PAYLOAD.to_vec());

            job
        })
        .collect::<Vec<_>>();

    manager
        .bulk_create_jobs(jobs)
        .await
        .expect("failed to bulk insert jobs");

    let results: Vec<Job> = worker
        .dequeue_jobs(&job_template.queue_name, 100)
        .await
        .expect("failed to dequeue job");

    assert_eq!(results.len(), 100);
    let payload = VM_STATE_PAYLOAD.clone().to_vec();

    for result in results {
        assert!(result.function_id.is_some());
        let fid = result.function_id.unwrap().to_string();
        assert!(Uuid::parse_str(&fid).is_ok());

        // dequeue_jobs always returns vm_state as NULL
        assert!(result.vm_state.is_none());

        // other binary blobs columns should be returned and hydrated properly
        assert!(result.metadata.is_some());
        assert!(result.parameters.is_some());
        assert!(result.blob.is_some());
        assert_eq!(result.metadata.unwrap(), payload);
        assert_eq!(result.parameters.unwrap(), payload);
        assert_eq!(result.blob.unwrap(), payload);
    }
}

#[sqlx::test(migrations = "./migrations")]
pub async fn test_bulk_insert_copy_from_with_compressed_vm_state(db: PgPool) {
    let worker_cfg = WorkerConfig {
        should_compress_vm_state: Some(true),
        ..Default::default()
    };
    let worker = Worker::from_pool(db.clone(), worker_cfg);
    let manager = QueueManager::from_pool(db.clone(), true, true);

    let job_template = create_new_job();
    let mut job = job_template.clone();
    job.function_id = Some(Uuid::now_v7());
    job.vm_state = Some(VM_STATE_PAYLOAD.to_vec());
    let queue_name = job.queue_name.clone();

    let ids = manager
        .bulk_create_jobs(vec![job])
        .await
        .expect("failed to bulk insert jobs");
    assert_eq!(ids.len(), 1);

    let results: Vec<Job> = worker
        .dequeue_with_vm_state(&queue_name, 1)
        .await
        .expect("failed to dequeue Job vm_state");

    assert_eq!(results.len(), 1);
    assert_eq!(
        results[0].vm_state.as_ref().unwrap(),
        &VM_STATE_PAYLOAD.clone().to_vec()
    );
}
