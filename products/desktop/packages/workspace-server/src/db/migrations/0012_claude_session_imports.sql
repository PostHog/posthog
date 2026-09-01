CREATE TABLE `claude_session_imports` (
	`id` text PRIMARY KEY NOT NULL,
	`source_session_id` text NOT NULL,
	`imported_session_id` text NOT NULL,
	`task_id` text NOT NULL,
	`repo_path` text NOT NULL,
	`source_mtime_ms` integer NOT NULL,
	`source_size_bytes` integer NOT NULL,
	`source_last_entry_uuid` text,
	`created_at` text DEFAULT (CURRENT_TIMESTAMP) NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `claude_session_imports_importedSessionId_unique` ON `claude_session_imports` (`imported_session_id`);--> statement-breakpoint
CREATE INDEX `claude_session_imports_source_idx` ON `claude_session_imports` (`source_session_id`);--> statement-breakpoint
CREATE INDEX `claude_session_imports_task_idx` ON `claude_session_imports` (`task_id`);