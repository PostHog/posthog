CREATE TABLE `default_additional_directories` (
	`path` text PRIMARY KEY NOT NULL,
	`created_at` text DEFAULT (CURRENT_TIMESTAMP) NOT NULL
);
--> statement-breakpoint
ALTER TABLE `workspaces` ADD `additional_directories` text DEFAULT '[]' NOT NULL;