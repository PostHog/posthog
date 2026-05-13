from __future__ import annotations

import json

from pydantic import BaseModel, Field


class RelevantTweet(BaseModel):
    id: str = Field(
        description="The tweet's `id` string exactly as returned by the advanced_search API.",
    )
    user: str = Field(
        description="The author's `userName` (handle without the leading `@`), exactly as returned by `author.userName`.",
    )
    reason: str = Field(
        description=(
            "One short sentence explaining which positive signal triggered the include, "
            "paraphrased (not verbatim quoted) from the tweet. "
            "Format: '[signal type]: [paraphrased substance]'. "
            "Examples: 'Superlative praise: ranks PostHog as the top product analytics tool they have used.' "
            "or 'Operational standardization: requires PostHog experience in a hiring post.'"
        ),
    )


class TwitterReferralCandidates(BaseModel):
    candidates: list[RelevantTweet] = Field(
        description=(
            "Tweets whose authors are strong referral candidates. "
            "Empty list is valid and expected when nothing in the window meets the bar."
        ),
    )


_TWITTER_RESEARCH_PREAMBLE = """You are a growth research agent for PostHog. Your job is to find Twitter/X users who recently posted a positive signal about PostHog and look like reasonable referral targets — people we can DM with a personalized ask to refer other companies they know who would benefit from PostHog.

PostHog is a product analytics platform. The growth team will write a one-off personalized DM to each candidate — they are not running cold mass outreach. The bar is **"would this person plausibly engage with a friendly referral ask?"**, not "is this person a screaming evangelist?". Lukewarm-positive builders and founders who clearly use and prefer PostHog are valid candidates. Pure noise is not.

You will:
1. Fetch all Twitter posts from the last {hours}h mentioning PostHog using the curl command below.
2. Read each post and decide which authors look like reasonable referral targets.
3. Return the candidates as a JSON object matching the schema at the end."""


_TWITTER_FETCH_INSTRUCTIONS = """## Fetching the posts

Run this exact curl command in the sandbox shell to get every tweet mentioning PostHog since the cutoff (retweets excluded, all languages allowed):

```bash
curl -s -G "https://api.twitterapi.io/twitter/tweet/advanced_search" \\
  -H "x-api-key: {api_key}" \\
  --data-urlencode "query=PostHog since_time:{since_unix_ts} -is:retweet" \\
  --data-urlencode "queryType=Latest"
```

Response shape: `{{"tweets": [...], "has_next_page": bool, "next_cursor": str}}`. Each tweet object exposes at least `id`, `createdAt`, `text`, and `author.userName`. Pipe through `jq` to extract what you need, e.g.:

```bash
… | jq '.tweets[] | {{id, createdAt, user: .author.userName, text}}'
```

If `has_next_page` is `true`, repeat the request with the same headers/params plus `--data-urlencode "cursor=$NEXT_CURSOR"` until `has_next_page` becomes `false`. Tweet volume for "PostHog" over a one-hour window is typically small (well under 100), so a single page is usually enough — but always check and paginate when needed."""


_TWITTER_CRITERIA = """## Selection criteria

Include an author when their tweet contains **at least one** of the following positive signals about PostHog. Any one of these is enough — you do not need to see multiple.

1. **Superlative praise** — "incredible", "love", "best", "amazing", "blown away", "obsessed", "game-changer", "couldn't live without", "switched and never looked back", or equivalent in any language.
2. **Firm preference** — "best features", "most useful", "favorite", "go-to", "default choice", "PostHog over X", "this is the one I'd pick", "I always reach for PostHog".
3. **Active recommendation** — telling another user to use PostHog ("definitely @PostHog", "you should use PostHog", "PostHog is the answer for X", "PostHog + Y is great").
4. **Operational standardization** — they have built PostHog into how they work or hire, in a way that signals strong preference: "we standardized on PostHog", "must PostHog" as a hiring requirement, "we've moved everything to PostHog".
5. **Specific positive experience** — a concrete, first-person story about something PostHog did well for them (a feature they love, a problem it solved, a comparison where PostHog won).
6. **Ecosystem alignment** — the author is building a product, service, or integration that explicitly supports or connects to PostHog ("our tool connects to PostHog", "we integrate with PostHog", "supports PostHog out of the box"). Their incentives are aligned with PostHog's growth, and they typically know other companies using PostHog — strong referral potential even when the tweet is promoting their own product.

Bias: when a tweet plausibly fits one of the signals above, **include** it and explain which signal in the `reason`. The growth team can filter further before sending a DM. Missing a real fan is more costly than including a borderline one.

Exclude when **none** of the above apply, especially:

- Pure tool-stack roundups where PostHog is one bullet among many with no opinion attached (e.g. "analytics: @posthog" in a long stack list).
- Tag-only replies with no endorsement content ("@posthog @someone will LOVE this", "@posthog Good read").
- Pure dev logs or factual mentions ("set up PostHog today", "added PostHog to my dashboard") that carry no opinion.
- Complaints or hard critiques about PostHog.
- Pitches for a competing analytics product where PostHog is named only as a comparison or migration target.

Mixed sentiment is fine to **include** as long as the positive signal is real — e.g. "best features even though the UI is a bit complicated" still counts because the core claim is a firm preference.

Non-English tweets are valid; translate them mentally before judging.

## Pattern examples

These are illustrative shapes, not real tweets — match against the *pattern*, not the wording.

INCLUDE shapes:
- Superlative praise about a specific PostHog feature or the product as a whole ("the [feature] is the most incredible [category] tool I've ever used").
- Reply to someone asking for a recommendation, naming PostHog as the answer with a preference phrase ("Definitely PostHog — best features I've used").
- First-person comparison where PostHog wins or ties for the top ("Toss-up between PostHog and [competitor] for the most useful tool in our stack").
- Hiring posts or team policies that require PostHog familiarity ("must know PostHog", "we've standardized our analytics on PostHog").
- A concrete first-person story about a PostHog feature solving a real problem for the author.
- A builder announcing or promoting their own product/service while naming PostHog as a supported integration or connected source ("[my tool] connects to PostHog, Stripe, …"). Aligned incentives + ecosystem visibility make these good referral targets even though it is a self-promo post.

EXCLUDE shapes:
- A long stack/tool list where PostHog appears as a single bullet with no opinion ("analytics: PostHog" alongside ten other tools) and the author is *not* pitching an integration — just listing what they personally use.
- A tag-only reply with no endorsement content ("@posthog [@another_user] will love this", "@posthog good read").
- A pure dev log or build-in-public update that mentions setting up PostHog with no opinion attached and no integration angle.
- A competitor pitching their analytics product and naming PostHog only as a comparison or migration target ("switch from PostHog to [their_tool]")."""


def build_twitter_research_prompt(
    *,
    since_unix_ts: int,
    api_key: str,
    hours: int = 1,
) -> str:
    """Build the single-turn prompt that fetches recent tweets and filters for referral candidates."""
    schema = json.dumps(TwitterReferralCandidates.model_json_schema(), indent=2)
    fetch_block = _TWITTER_FETCH_INSTRUCTIONS.format(
        api_key=api_key,
        since_unix_ts=since_unix_ts,
    )
    return f"""{_TWITTER_RESEARCH_PREAMBLE.format(hours=hours)}

---

{fetch_block}

---

{_TWITTER_CRITERIA}

---

## Output format

Respond with a single JSON object matching this schema. Use the tweet's `id` and `author.userName` exactly as returned by the API — do not reformat or add `@`. Keep each `reason` to one short sentence that paraphrases (does not verbatim quote) the strongest signal, prefixed with the signal type — see the field description for the format:

<jsonschema>
{schema}
</jsonschema>

If no tweets in the window meet any of the signals above, return `{{"candidates": []}}`. Otherwise, include every tweet that plausibly fits — err on the side of inclusion when the signal is real."""
