ALTER TABLE `auth_sessions` ADD `deployment_target` text DEFAULT 'us' NOT NULL;
--> statement-breakpoint
UPDATE `auth_sessions` SET `deployment_target` = `cloud_region`;
--> statement-breakpoint
ALTER TABLE `auth_sessions` ADD `deployment_id` text;
