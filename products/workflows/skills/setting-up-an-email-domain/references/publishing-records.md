# Publishing email records with your own DNS tools

Use this when you add the records from `integrations-email-status-retrieve` yourself.
Before writing anything, list the existing records at each name you are about to touch.

## Per record

| Record                 | Name                             | What to do                                                                                                                                                                               |
| ---------------------- | -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Domain ownership (TXT) | `_amazonses.<domain>`            | Add it. Another `_amazonses` TXT value from an older setup can stay next to it.                                                                                                          |
| DKIM (3 × CNAME)       | `<token>._domainkey.<domain>`    | Add all three. On Cloudflare, set them to DNS only (grey cloud); a proxied CNAME never verifies.                                                                                         |
| SPF (TXT)              | `<domain>`                       | If an SPF record (`v=spf1 ...`) already exists at that name, add `include:amazonses.com` to it before its `all` term instead of adding a record. Two SPF records break SPF for all mail. |
| MAIL FROM (MX)         | `<mail_from>.<domain>`           | Add it with the given priority. The name must have no other MX record, or the MAIL FROM check fails.                                                                                     |
| MAIL FROM SPF (TXT)    | `<mail_from>.<domain>`           | Add it, merging into an existing SPF record at that name the same way as above.                                                                                                          |
| Organization (TXT)     | `_posthog-verification.<domain>` | Add it when the status lists it. It proves your organization owns a domain another organization also claims, and Domain Connect does not publish it.                                     |
| DMARC (TXT)            | `_dmarc.<domain>`                | Never add, change or delete it yourself: it is the domain owner's policy. Give the person the suggested record and let them decide.                                                      |

`<domain>` is the sending domain, for example `mail.example.com`, which may sit inside the zone `example.com`.
Names from the tool are fully qualified; convert them to the form your DNS tool expects, usually relative to the zone.
For `mail.example.com` in the zone `example.com`, the SPF record's relative name is `mail`; `@` is the zone apex `example.com`, so use it only when the sending domain is the zone itself.

## After publishing

Look the records up from a public resolver if you can, to catch typos before you start polling.
Then return to the polling loop in the main skill.
Do not delete or edit records that are unrelated to this sender, even if they look stale.
