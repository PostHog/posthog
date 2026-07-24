---
title: Linking Excel as a source
sidebar: Docs
showTitle: true
availability: { free: full, selfServe: full, enterprise: full }
sourceId: Excel
beta: true
---

import SourceSetupIntro from "../\_snippets/source-setup-intro.mdx"
import SyncModes from "../\_snippets/sync-modes.mdx"
import TroubleshootingLink from "../\_snippets/dw-troubleshooting-link.mdx"
import AlphaRelease from "../\_snippets/alpha-release.mdx"

<AlphaRelease />

Upload an Excel workbook and query it in the PostHog Data warehouse. Every sheet becomes its own table, so a workbook with `orders` and `refunds` tabs gives you two tables you can query and join with your product data.

Unlike most sources, there's nothing to connect to: you upload the file and PostHog reads it. The workbook is stored in PostHog's own storage, and the import runs in the background rather than while you wait.

## Prerequisites

- A workbook saved as **`.xlsx`** or **`.xlsm`**. The older binary `.xls` format isn't supported — open it in Excel and re-save as `.xlsx`.
- The file must be **50MB or smaller**. For bigger datasets, export to CSV or Parquet in cloud storage and connect that bucket as a [self-managed source](/docs/cdp/sources/s3) instead.
- Each sheet you want to import needs a **header row** as its first row. Column names come from those cells; blank ones become `column_1`, `column_2`, and so on, and duplicates get a numbered suffix. Sheets without a header row are skipped.

## Adding a data source

<SourceSetupIntro />

Choose your workbook, then pick which sheets to import. You can also deselect individual columns on any sheet if you only need part of it.

## Sync modes

<SyncModes />

An uploaded workbook is a snapshot, not a live feed, so every sheet is synced as **full refresh** and the import runs **once** rather than on a schedule.

To refresh the data, upload the replacement file and sync again. The table is rebuilt from the new file, so nothing is left over from the previous version.

## Configuration

<SourceParameters />

## Supported tables

The tables you get depend on your workbook: one per sheet, named after the sheet. Column types are inferred from the cell values, so numbers and dates stay numbers and dates rather than becoming text.

## Troubleshooting

- **"Could not read the Excel file"** — the file isn't a valid `.xlsx` or `.xlsm` workbook. This is most often an `.xls` file, or a file renamed to `.xlsx` without being re-saved. Open it in Excel and use **Save As ▸ Excel Workbook (.xlsx)**.
- **"No sheets with a header row were found"** — every sheet is either empty or starts with blank cells. Add a header row with column names as the first row of each sheet you want to import.
- **"Uploaded file not found"** — the stored file is no longer available, which happens if it was removed after the source was created. Upload the workbook again.
- **A column is empty when you expected values** — formula cells import their last calculated value, which Excel saves with the file. If a formula was never calculated, it imports as empty. Open the workbook, let it recalculate, save, and re-upload.
- **A sheet is missing from the table list** — check it has a header row, and that you selected it during setup. You can add more sheets later by refreshing the source's schemas.

<TroubleshootingLink />

<!--
STAGING NOTE (delete when relocating): this file is the user-facing posthog.com doc for the Excel
source. It is staged in this repo because no posthog.com checkout was available during implementation.
Before shipping, move it to the posthog.com repo at contents/docs/cdp/sources/excel.md (served at
/docs/cdp/sources/excel and /docs/data-warehouse/sources/excel), then run from the posthog repo:
python manage.py audit_source_docs --docs-dir ../posthog.com/contents/docs/cdp/sources
-->
