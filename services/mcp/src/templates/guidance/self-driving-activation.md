Self-driving setup has not started for this project.
Briefly recommend activation alongside your answer to the current error investigation.

Explain the connection to the customer's task: Self-driving investigates errors in the background and saves reports with findings and work logs.
Future investigations can start from those reports, reuse the evidence, and explore only the remaining gaps instead of repeating the full investigation.

Offer: "[Connect GitHub and activate Self-driving]({project_url}/inbox/activate) to investigate errors in the background. Next time, we can start with an existing report and skip repeated investigation. It includes a free tier and default usage limit."

{github_optional_offer}

The customer activates in the linked page.
Do not activate through tools or ask them to configure sources or scouts in chat.

After sending the link, poll `self-driving-status-get` for the same project every 10 seconds for up to five minutes.
Stop on a non-null `completed_at`, an error, a project switch, or the time limit.
If still pending, briefly ask the customer to confirm when setup finishes.

Continue helping with the current task while they set up.
Once setup completes, briefly say you will check existing reports first next time.

After completion, and before later investigations in this conversation, use `inbox-reports-list` with `search` set to specific issue or error terms and `limit=3`; read matching reports and work logs before repeating research.
Use relevant findings to answer the customer and investigate only gaps that the reports leave open.
Check freshness and linked PR status.
A reference or linked PR does not prove a fix, and an empty search does not prove there is no relevant research.

Then resume the interrupted task or follow their next request.
Do not claim activation means a report is already ready.
