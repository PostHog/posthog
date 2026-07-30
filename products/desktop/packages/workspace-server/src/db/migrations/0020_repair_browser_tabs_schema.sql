-- Repair migration for profiles that dogfooded a pre-merge bluebird build.
-- Migration 0013 was amended in place on the branch (same folderMillis), so a
-- DB that ran an early version has it recorded as applied without the final
-- tab-strip schema: `browser_windows` lacks `active_tab_id` (and other
-- variants may lack columns or whole tables), which makes every browser-tabs
-- query throw and leaves the tab strip dead.
--
-- Two-step repair, both idempotent on healthy DBs:
-- 1. CREATE TABLE IF NOT EXISTS with the FULL current schema — heals variants
--    where an amendment never created the table at all (a plain ALTER would
--    throw "no such table" and fail the whole migration transaction).
-- 2. ALTER TABLE ADD COLUMN for each column a stale variant may be missing —
--    the runner tolerates "duplicate column name" (see migrate.ts), so these
--    no-op wherever the column already exists.
--
-- Accepted limitation: ALTER can't heal type or NOT NULL divergence on
-- existing columns. Every observed 0013 variant agrees on the shared column
-- shapes (all nullable text), so only missing columns/tables need repair.
CREATE TABLE IF NOT EXISTS `browser_windows` (
	`id` text PRIMARY KEY NOT NULL,
	`is_primary` integer DEFAULT false NOT NULL,
	`bounds` text,
	`active_tab_id` text,
	`position` integer DEFAULT 0 NOT NULL,
	`created_at` integer NOT NULL,
	`updated_at` integer NOT NULL
);--> statement-breakpoint
CREATE TABLE IF NOT EXISTS `browser_tabs` (
	`id` text PRIMARY KEY NOT NULL,
	`window_id` text NOT NULL,
	`dashboard_id` text,
	`channel_id` text,
	`position` integer NOT NULL,
	`scroll_state` text,
	`created_at` integer NOT NULL,
	`last_active_at` integer NOT NULL,
	`task_id` text,
	`channel_section` text,
	`app_view` text,
	FOREIGN KEY (`window_id`) REFERENCES `browser_windows`(`id`) ON UPDATE no action ON DELETE cascade
);--> statement-breakpoint
CREATE INDEX IF NOT EXISTS `browser_tabs_window_idx` ON `browser_tabs` (`window_id`);--> statement-breakpoint
ALTER TABLE `browser_windows` ADD COLUMN `active_tab_id` text;--> statement-breakpoint
ALTER TABLE `browser_tabs` ADD COLUMN `task_id` text;--> statement-breakpoint
ALTER TABLE `browser_tabs` ADD COLUMN `channel_section` text;--> statement-breakpoint
ALTER TABLE `browser_tabs` ADD COLUMN `app_view` text;
