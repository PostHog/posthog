ALTER TABLE `archives` ADD `title` text;
--> statement-breakpoint
ALTER TABLE `archives` ADD `task_created_at` text;
--> statement-breakpoint
ALTER TABLE `archives` ADD `repository` text;
--> statement-breakpoint
ALTER TABLE `task_metadata` ADD `archived_title` text;
--> statement-breakpoint
ALTER TABLE `task_metadata` ADD `archived_task_created_at` text;
--> statement-breakpoint
ALTER TABLE `task_metadata` ADD `archived_repository` text;
