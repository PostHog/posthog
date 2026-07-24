CREATE TABLE `task_metadata` (
	`task_id` text PRIMARY KEY NOT NULL,
	`pinned_at` text,
	`last_viewed_at` text,
	`last_activity_at` text,
	`created_at` text DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
	`updated_at` text DEFAULT (CURRENT_TIMESTAMP) NOT NULL
);
