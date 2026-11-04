# Moving transactional emails from another provider

Move one email at a time. Pick a low-risk email first, switch it, check a few real sends, then move the next one.

## Map the send call

Keep the email in the app's code unless the user chose a PostHog template. First find where the email lives today:

| Provider                  | What the code sends today                                                   | Where the email lives |
| ------------------------- | --------------------------------------------------------------------------- | --------------------- |
| Resend, Mandrill, Brevo   | Often a subject and an HTML body, or a React Email component, built in code | Code                  |
| nodemailer or SMTP        | A subject and a body built in code                                          | Code                  |
| Amazon SES                | A template name and template data, or a raw subject and body                | Provider, or code     |
| SendGrid                  | `templateId`, `to`, `dynamicTemplateData`                                   | Provider              |
| Postmark                  | `TemplateAlias` or `TemplateId`, `To`, `TemplateModel`                      | Provider              |
| Mailgun                   | `template`, `to`, `h:X-Mailgun-Variables`                                   | Provider              |
| Loops                     | `transactionalId`, `email`, `dataVariables`                                 | Provider              |
| Customer.io transactional | `transactional_message_id`, `to`, `identifiers`, `message_data`             | Provider              |

Every row becomes the same PostHog send. The fields are in the skill's **Send from code** section.

## Move the content

- **An email built in code** stays where it is. Only the send call changes, and it keeps the subject and the HTML and text bodies the old send passed. When the old send passed a React Email component, render it to HTML in the app and pass that as `html`.
- **An email stored at the provider** becomes code: export its HTML, or ask the user for it or a screenshot if you can't read it, and write it as a function in the repo that takes the values the provider's template variables held. When the app uses React Email, write it as a component. Keep the same logo, colors, and layout.
- **For a PostHog template** instead, recreate the email with the skill's **Design it in PostHog** steps, starting from the email the provider sends today. Rename the placeholders to Liquid: a variable `name` becomes `{{ variables.name }}`. The template can't read person properties, so pass every value in `templateData`. Values that the old template computed, such as loops or conditions, become Liquid tags, and logic that needs backend data stays in the backend.

## Check before the switch

- **What the send can't carry:** A PostHog send has one recipient and no attachments, cc or bcc. If the old send passes any of them, tell the user what the switch would drop before you change the call.
- **Sender:** The sending domain must be verified in PostHog, even if it already sends with the other provider. The app shows the DNS records to add.
- **Suppressions:** Addresses that the old provider suppressed after bounces or complaints are not in PostHog's suppression list. Ask the user whether to add them before high-volume emails move.
- **Errors:** Map the old provider's error handling to PostHog's error codes, such as `recipient_suppressed`, `recipient_unreachable`, and `quota_limited`. A code that means "don't retry" must not go back into a retry loop.
- **Retries:** Keep one idempotency key for each email across retries, so a retry after a timeout doesn't send twice.
- **Volume:** Transactional emails count toward the project's sending allowance and email quota. For a large volume, check the allowance with `workflows-reputation-get` before the switch.

## After the switch

Watch the first sends. Read a few statuses from the user's code, and, for a PostHog template, look at its **Sends** and **Metrics** tabs. Remove the old provider's code for that email only when the user is happy with it.
