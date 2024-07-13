-- Dequeue is not hitting this index, so dropping is safe this time.
DROP INDEX idx_queue_scheduled_at;

/*
Partial index used for dequeuing from job_queue.

Dequeue only looks at available jobs so a partial index serves us well.
Moreover, dequeue sorts jobs by attempt and scheduled_at, which matches this index.
*/
CREATE INDEX idx_queue_dequeue_partial ON job_queue(queue, attempt, scheduled_at) WHERE status = 'available' :: job_status;
