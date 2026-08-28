CREATE TABLE `auth_org_project_preferences` (
	`account_key` text NOT NULL,
	`cloud_region` text NOT NULL,
	`org_id` text NOT NULL,
	`last_selected_project_id` integer NOT NULL,
	`created_at` text DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
	`updated_at` text DEFAULT (CURRENT_TIMESTAMP) NOT NULL
);
--> statement-breakpoint
CREATE INDEX `auth_org_project_account_region_org_idx` ON `auth_org_project_preferences` (`account_key`,`cloud_region`,`org_id`);--> statement-breakpoint
ALTER TABLE `auth_preferences` ADD `last_selected_org_id` text;