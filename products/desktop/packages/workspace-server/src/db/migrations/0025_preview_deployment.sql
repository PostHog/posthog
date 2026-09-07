ALTER TABLE `auth_sessions` ADD `deployment_target` text DEFAULT 'us' NOT NULL;
ALTER TABLE `auth_sessions` ADD `deployment_id` text;
