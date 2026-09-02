CREATE TABLE `auth_sessions` (
	`id` integer PRIMARY KEY NOT NULL CHECK (`id` = 1),
	`refresh_token_encrypted` text NOT NULL,
	`cloud_region` text NOT NULL,
	`selected_project_id` integer,
	`scope_version` integer NOT NULL,
	`created_at` text DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
	`updated_at` text DEFAULT (CURRENT_TIMESTAMP) NOT NULL
);
