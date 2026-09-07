PRAGMA foreign_keys=OFF;--> statement-breakpoint
CREATE TABLE `__new_browser_tabs` (
	`id` text PRIMARY KEY NOT NULL,
	`window_id` text NOT NULL,
	`dashboard_id` text,
	`channel_id` text,
	`position` integer NOT NULL,
	`scroll_state` text,
	`created_at` integer NOT NULL,
	`last_active_at` integer NOT NULL,
	FOREIGN KEY (`window_id`) REFERENCES `browser_windows`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
INSERT INTO `__new_browser_tabs`("id", "window_id", "dashboard_id", "channel_id", "position", "scroll_state", "created_at", "last_active_at") SELECT "id", "window_id", "dashboard_id", "channel_id", "position", "scroll_state", "created_at", "last_active_at" FROM `browser_tabs`;--> statement-breakpoint
DROP TABLE `browser_tabs`;--> statement-breakpoint
ALTER TABLE `__new_browser_tabs` RENAME TO `browser_tabs`;--> statement-breakpoint
PRAGMA foreign_keys=ON;--> statement-breakpoint
CREATE INDEX `browser_tabs_window_idx` ON `browser_tabs` (`window_id`);