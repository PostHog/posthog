# Publishing email records with your own DNS tools

Use this when you add the records from `integrations-email-verify-create` yourself.
Before writing anything, list the existing records at each name you are about to touch.

## Per record

| Record                 | Name                          | What to do                                                                                                                                                                               |
| ---------------------- | ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Domain ownership (TXT) | `_amazonses.<domain>`         | Add it. Another `_amazonses` TXT value from an older setup can stay next to it.                                                                                                          |
| DKIM (3 × CNAME)       | `<token>._domainkey.<domain>` | Add all three. On Cloudflare, set them to DNS only (grey cloud); a proxied CNAME never verifies.                                                                                         |
| SPF (TXT)              | `@` (the sending domain)      | If an SPF record (`v=spf1 ...`) already exists at that name, add `include:amazonses.com` to it before its `all` term instead of adding a record. Two SPF records break SPF for all mail. |
| MAIL FROM (MX)         | `<mail_from>.<domain>`        | Add it with the given priority. The name must have no other MX record, or the MAIL FROM check fails.                                                                                     |
| MAIL FROM SPF (TXT)    | `<mail_from>.<domain>`        | Add it, merging into an existing SPF record at that name the same way as above.                                                                                                          |
| DMARC (TXT)            | `_dmarc.<domain>`             | Add it only if no `v=DMARC1` record exists. If one exists, leave it alone: it is the domain owner's policy, and a second DMARC record invalidates both.                                  |

`<domain>` is the sending domain, for example `mail.example.com`, which may sit inside the zone `example.com`.
Names from the tool are fully qualified; convert them to the form your DNS tool expects, usually relative to the zone.

## After publishing

Look the records up from a public resolver if you can, to catch typos before you start polling.
Then return to the verify loop in the main skill.
Do not delete or edit records that are unrelated to this sender, even if they look stale.
