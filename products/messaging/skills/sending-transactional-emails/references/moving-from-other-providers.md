# Moving transactional emails from another provider

Move one email at a time. Pick a low-risk email first, switch it, check a few real sends, then move the next one.

## Map the send call

A PostHog send takes a template ID, one recipient, the values for the template's placeholders, the recipient's distinct ID, and an idempotency key. The subject, body, sender and reply-to address live on the template, so move them out of the code and into the template.

| Provider                  | What the code sends today                                                   | In PostHog                                                                                                                |
| ------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Customer.io transactional | `transactional_message_id`, `to`, `identifiers`, `message_data`             | Almost the same shape. `templateId` / `template_id`, `to`, `distinctId` / `distinct_id`, `templateData` / `template_data` |
| Loops                     | `transactionalId`, `email`, `dataVariables`                                 | `templateId`, `to`, `templateData`                                                                                        |
| Postmark                  | `TemplateAlias` or `TemplateId`, `To`, `TemplateModel`                      | `templateId`, `to`, `templateData`                                                                                        |
| SendGrid                  | `templateId`, `to`, `dynamicTemplateData`                                   | `templateId`, `to`, `templateData`                                                                                        |
| Mailgun                   | `template`, `to`, `h:X-Mailgun-Variables`                                   | `templateId`, `to`, `templateData`                                                                                        |
| Amazon SES                | A template name and template data, or a raw subject and body                | `templateId`, `to`, `templateData`                                                                                        |
| Resend, Mandrill, Brevo   | Often a subject and an HTML body, or a React Email component, built in code | Build the email as a PostHog template, then send `templateId`, `to`, `templateData`                                       |
| nodemailer or SMTP        | A subject and a body built in code                                          | Build the email as a PostHog template, then send `templateId`, `to`, `templateData`                                       |

## Move the content

- Recreate the email as a PostHog template with the `designing-email-templates` skill. Start from the email the provider sends today, so it keeps the same logo, colors, and layout. Ask the user for its HTML or a screenshot if you can't read it. For an email built in code, such as a React Email component, render it once and use the result as the starting design.
- Rename the placeholders to Liquid: a variable `name` becomes `{{ variables.name }}`. The template can't read person properties, so pass every value in `templateData`.
- Values that the old code computed in the template language, such as loops or conditions, become Liquid tags. Keep the logic that needs backend data in the backend, and pass the result.

## Check before the switch

- **Sender:** The sending domain must be verified in PostHog, even if it already sends with the other provider. The app shows the DNS records to add.
- **Suppressions:** Addresses that the old provider suppressed after bounces or complaints are not in PostHog's suppression list. Ask the user whether to add them before high-volume emails move.
- **Errors:** Map the old provider's error handling to PostHog's error codes, such as `recipient_suppressed`, `recipient_unreachable`, and `quota_limited`. A code that means "don't retry" must not go back into a retry loop.
- **Retries:** Keep one idempotency key for each email across retries, so a retry after a timeout doesn't send twice.
- **Volume:** Transactional emails count toward the project's sending allowance and email quota. For a large volume, check the allowance with `workflows-reputation-get` before the switch.

## After the switch

Watch the first sends. Read a few statuses from the user's code, and look at the template's **Sends** and **Metrics** tabs. Remove the old provider's code for that email only when the user is happy with it.
