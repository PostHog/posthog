# Scoring candidates

The score is a first pass.
It turns 60 to 150 candidates into a rough order so you only judge the top 40 or so carefully.
Adjust the weights when the person's request or the data calls for it, and say what you changed.

## Default formula

```text
score = priority_base × model_multiplier × freshness
      + interest_bonus + needs_me_bonus
```

### `priority_base`

| `priority` | Base |
| ---------- | ---- |
| P0         | 5    |
| P1         | 4    |
| P2         | 3    |
| P3         | 2    |
| P4         | 1    |
| `null`     | 1.5  |

`priority` is `null` before judgment runs (`candidate`, some `pending_input` rows).
1.5 keeps those reports in play without letting them outrank a judged P2.

### `model_multiplier`

```text
lifts = [lift(action), lift(fix)] without missing values
if ranking.status == "scored" and scored_at is within ~7 days and lifts:
    model_multiplier = 0.5 + 0.5 × min(mean(lifts), 8) / 2
else:
    model_multiplier = 1.0
```

- A lift of 1.0 is an average report. Lifts of 2 give a multiplier of 1.0. Lifts of 6 give 2.0. The cap at 8 keeps one inflated estimate from taking over.
- `action` and `fix` say whether someone will do something. `open` mostly says whether the title is clickable, so it is a weaker signal for "what should I look at". Use `open` only when the other two are missing.
- Do not add `action` and `fix` together: most `fix` positives are also `action` positives.
- `stale` (the text changed after scoring), `unscored`, and `not_available` all get 1.0. None of them is a low score.
- Old scores can carry a probability but a `null` lift. Treat that as unscored. An old `pending_input` row with `open` 0.6 looks strong but says little about today.
- `inbox-ranking-outcomes-list` gives each outcome's horizon and base rate when you need to explain a number.

### `freshness`

Use `updated_at`:

| Days since update | Multiplier |
| ----------------- | ---------- |
| under 2           | 1.3        |
| 2 to 7            | 1.0        |
| 7 to 21           | 0.7        |
| over 21           | 0.4        |

A report that keeps getting updated is live work.
Widen the bands when the person asks for a longer window.

### `interest_bonus`

Match each report's title and summary against the interest profile from Step 1.

- +2 for each matched theme, up to two themes.
- Count a title match in full and a summary-only match at half.
- Scale by theme weight: `strength: high` and `last_seen` in the last 3 days counts in full, `medium` or older counts at about two thirds, `low` at about one third.
- +2 when the report names an object from `computed.owned` or `computed.watched` by name or id.
- +1 when a `source_product` is in `computed.products.works_in`.
- +2 for the theme or topic the person asked to focus on in this request.

### `needs_me_bonus`

- +1.5 for `is_suggested_reviewer: true`.
- +1.5 when the person answers for the claim (it came back in the `assignee: "mine"` pool).
- +1 for an open pull request with `review_decision: approved`, because it is close to done.
- +0.5 for `status: pending_input` when the report is routed to them.

## Worked examples

Values are illustrative.

**Fresh themed report with a strong model score.**
P2, updated 1 day ago, `action` lift 9.1 and `fix` lift 4.7, scored yesterday, title matches a high-strength theme, suggested reviewer.
`3 × (0.5 + 0.5 × 6.9 / 2) × 1.3 + 2 + 1.5 = 3 × 2.23 × 1.3 + 3.5 ≈ 12.2`.

**Old routed report with a stale score.**
P2, `pending_input`, updated 30 days ago, `open` probability 0.6 with `null` lifts, suggested reviewer, no theme match.
`3 × 1.0 × 0.4 + 1.5 + 0.5 = 3.2`.
It ranks far below the first example, which matches what the person would pick.

**High-priority report owned by someone else.**
P1, updated 19 days ago, `working`, lifts 5.9 and 2.6 scored 2 days ago, weak theme match.
`4 × (0.5 + 0.5 × 4.25 / 2) × 0.7 + 1 ≈ 5.4`.
It belongs in the list if the person is the reviewer or the theme is strong; otherwise it is a "someone is on it" mention.

## Signals of noise

- The same scout files a near-identical title every day: a digest. Keep the newest.
- A report matches a theme only through one generic word in a long summary: discount it.
- Low lifts on all three outcomes, low priority, and no personal link: a candidate to leave out, not to dismiss. Leaving it out of the list is enough.
