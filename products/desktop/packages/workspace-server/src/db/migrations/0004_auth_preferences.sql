CREATE TABLE `auth_preferences` (
	`account_key` text NOT NULL,
	`cloud_region` text NOT NULL,
	`last_selected_project_id` integer,
	`created_at` text DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
	`updated_at` text DEFAULT (CURRENT_TIMESTAMP) NOT NULL
);
--> statement-breakpoint
CREATE INDEX `auth_preferences_account_region_idx` ON `auth_preferences` (`account_key`,`cloud_region`);
