CREATE TABLE `browser_tabs` (
	`id` text PRIMARY KEY NOT NULL,
	`window_id` text NOT NULL,
	`dashboard_id` text NOT NULL,
	`channel_id` text,
	`position` integer NOT NULL,
	`scroll_state` text,
	`created_at` integer NOT NULL,
	`last_active_at` integer NOT NULL,
	FOREIGN KEY (`window_id`) REFERENCES `browser_windows`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `browser_tabs_window_idx` ON `browser_tabs` (`window_id`);--> statement-breakpoint
CREATE TABLE `browser_windows` (
	`id` text PRIMARY KEY NOT NULL,
	`is_primary` integer DEFAULT false NOT NULL,
	`bounds` text,
	`active_tab_id` text,
	`position` integer DEFAULT 0 NOT NULL,
	`created_at` integer NOT NULL,
	`updated_at` integer NOT NULL
);
