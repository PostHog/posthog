# Replying to review bots

Every finding gets a reply. The audience is the human who opens the PR next and needs to know, per
thread, what was concluded and why — not whether a bot was satisfied.

## What a reply contains

1. **The verdict up front.** "Accurate, fixed in `<sha>`." / "Real, but out of scope here."
   / "This does not hold, here is why." Do not bury it under analysis.
2. **The mechanism, in your own words.** Restating the mechanism proves you traced it rather than
   pattern-matching the bot's summary. If the bot's description was subtly wrong about the
   mechanism, this is where that surfaces.
3. **What you did, and why that approach.** When the bot offered options, say which you took and
   what it bought.
4. **The test.** Name it, and say what it does on the unfixed code.
5. **Honest severity.** If the bot rated it high and you think it is low, say so with the reason.
   If it rated it low and it is worse than that, say that too.

Keep it plain. No preamble, no thanking the bot.

## Posting

Reply inside the thread so it resolves in place:

```sh
gh api repos/PostHog/posthog/pulls/<pr>/comments/<comment-id>/replies -f body='...'
```

`<comment-id>` is the `id` of the original review comment. A new top-level comment is not a reply
and leaves the thread open.

For bodies with backticks and quotes, prefer a heredoc into a file and `-F body=@file`, or use
single-quoted shell strings and escape internal single quotes. Getting shell-mangled markdown into
a public repo is worse than a terse reply.

## Worked examples

### Accurate and fixed

> Accurate, and fixed in `d8fe3be`.
>
> You are right on the mechanics: DRF runs `check_throttles` in `initial()`, before the handler
> calls `load_grant()`, and the key was the grant id alone. So a partner that learned another
> partner's grant id could spend the owner's poll budget on it with requests that all end in 404.
>
> Went with your second suggestion (partner in the key) rather than moving the check after
> `load_grant()`, because keeping it a declarative throttle means it still gets the base view's
> `rate_limited` envelope and `Retry-After` for free. A grant belongs to exactly one partner, so
> scoping the key does not split any legitimate caller's quota.
>
> Added `test_poll_budget_is_not_shared_across_partners`, which fails with a 429 on the old key.
>
> Worth noting the practical severity matches your "low": `grant_id` is opaque and only ever
> returned to the partner that created it, so the attacker needs a secret they should not have.
> Fixed anyway since it was two lines.

Note the last paragraph. Agreeing with a finding and disagreeing with its framing is normal.

### Accurate but not this PR's to fix

> Real, and it is not new here — `git show master:<path>` has the same call. This PR moves the
> function into the DRF view without changing its behavior, so fixing it here would mix a security
> change into a refactor and make both harder to review or revert.
>
> Filed as a follow-up. Not blocking this one.

Only say this when you have actually checked master. "Pre-existing" asserted without evidence is
how real bugs get waved through.

### Wrong

> This does not hold. The claim is that `<x>` is user-controlled, but it comes from
> `<view>.get_search_fields()`, which returns a fixed tuple defined on the viewset — there is no
> request data on that path. Traced from the caller at `<file>:<line>`.
>
> Suppressed at the line with the rule id and that reason rather than leaving it to fire on every
> future run.

Evidence, not adjectives. "False positive" on its own tells the next reader nothing and they will
re-litigate it.

## When you cannot decide

Some findings turn on facts outside the repo: whether a production row has a usable credential,
whether a partner integration relies on the behavior you are about to tighten. Do not guess and do
not stall.

Land the part you can — a log line that surfaces the affected rows at migration time, a check that
fails closed — then say exactly what you could not verify and who has to:

> The mechanism is right and I have added a migration-time warning listing affected application
> ids, so this cannot fail silently on deploy. Whether any such row actually exists is an
> operational question I cannot answer from the repo — each one needs a secret set or a jwks_uri
> published before the old column is dropped. Flagging for you rather than guessing.

That is a finished reply, not a punt. It moves the code to a safe state and puts a named decision
in front of the person who can make it.
