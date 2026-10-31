### Existing Inbox reports

This project can have self-driving Inbox reports: research that PostHog already did on errors, bugs, metric changes, and support tickets.
Before you investigate one of these in code, check whether a report already covers it.

- Look for a report with {inbox_list} and `include_all_statuses=true`. If you have the id of the source record, pass it as `source_id` with exactly one `source_product`, for example an error tracking issue id with `source_product=error_tracking`. Otherwise pass a short `search` term, such as the error type or the page. `search` matches report titles and summaries only.
- If no report matches, continue and do not mention the check.
- If a report matches, read it with {inbox_retrieve} before you read code. Use its research as a starting point, and verify it against the code.
- If the report has an open pull request, continue that work. Do not start a second fix.
{inbox_claim_line}
