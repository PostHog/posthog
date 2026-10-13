scanned 546 messages, 546 $ai_generation events in window

Accounting audit: 537 priced generations total **$3.15126478**.
Nine validation requests failed with the captured LiteLLM HTTP 404 error before a response stream started.
Their costs remain null in the raw JSON; zero token counters represent omitted usage fields in the captured errors.
The calls column includes those nine requests (six in validation-c1, three in validation-c2); dollar totals sum only priced generations.
Independent Kafka reads match all 546 records, with no unpriced successful generation.
See [the request-error ledger](luna-xhigh-2.request_errors.json) for the per-event source-based classification and its limits.
These totals are captured generation costs, not a provider-invoice reconciliation.

| stage family          | model           | calls | input      | cache read | output  | reasoning | gateway $ | effort |
| --------------------- | --------------- | ----- | ---------- | ---------- | ------- | --------- | --------- | ------ |
| blind-spot            | gpt-5.6-luna    | 114   | 14,318,934 | 13,533,288 | 82,892  | 64,774    | $0.53     | xhigh  |
| dedup                 | claude-sonnet-5 | 1     | 9,078      | 0          | 17,601  | 0         | $0.19     | xhigh  |
| perspective_selection | claude-sonnet-5 | 1     | 5,981      | 0          | 569     | 0         | $0.02     | xhigh  |
| review                | gpt-5.6-luna    | 274   | 38,614,774 | 36,719,171 | 188,311 | 141,525   | $1.34     | xhigh  |
| validation            | gpt-5.6-luna    | 156   | 21,253,246 | 19,466,840 | 82,671  | 47,553    | $1.07     | xhigh  |

| stage                 | model           | calls | input     | cache read | cache write | output | reasoning | gateway $ |
| --------------------- | --------------- | ----- | --------- | ---------- | ----------- | ------ | --------- | --------- |
| blind-spots-c1        | gpt-5.6-luna    | 39    | 5,444,585 | 5,218,899  | 0           | 28,122 | 22,819    | $0.18     |
| blind-spots-c2        | gpt-5.6-luna    | 24    | 3,276,031 | 3,047,448  | 0           | 25,514 | 21,195    | $0.14     |
| blind-spots-c3        | gpt-5.6-luna    | 23    | 1,824,015 | 1,715,644  | 0           | 10,764 | 8,023     | $0.07     |
| blind-spots-c4        | gpt-5.6-luna    | 28    | 3,774,303 | 3,551,297  | 0           | 18,492 | 12,737    | $0.14     |
| dedup                 | claude-sonnet-5 | 1     | 9,078     | 0          | 0           | 17,601 | 0         | $0.19     |
| issues-review-p1-c1   | gpt-5.6-luna    | 21    | 2,334,497 | 2,163,654  | 0           | 15,123 | 11,239    | $0.10     |
| issues-review-p1-c2   | gpt-5.6-luna    | 33    | 5,474,372 | 5,213,774  | 0           | 23,869 | 18,438    | $0.19     |
| issues-review-p1-c3   | gpt-5.6-luna    | 22    | 2,510,680 | 2,317,679  | 0           | 14,701 | 11,184    | $0.10     |
| issues-review-p2-c1   | gpt-5.6-luna    | 27    | 3,421,825 | 3,225,379  | 0           | 22,870 | 18,222    | $0.13     |
| issues-review-p2-c2   | gpt-5.6-luna    | 46    | 7,753,266 | 7,504,993  | 0           | 29,015 | 22,427    | $0.23     |
| issues-review-p2-c3   | gpt-5.6-luna    | 34    | 4,793,509 | 4,589,232  | 0           | 21,217 | 15,619    | $0.16     |
| issues-review-p3-c1   | gpt-5.6-luna    | 18    | 1,966,177 | 1,799,665  | 0           | 13,518 | 9,847     | $0.09     |
| issues-review-p3-c2   | gpt-5.6-luna    | 35    | 4,523,084 | 4,321,845  | 0           | 29,225 | 22,439    | $0.16     |
| issues-review-p3-c3   | gpt-5.6-luna    | 38    | 5,837,364 | 5,582,950  | 0           | 18,773 | 12,110    | $0.19     |
| perspective_selection | claude-sonnet-5 | 1     | 5,981     | 0          | 0           | 569    | 0         | $0.02     |
| validation-c1         | gpt-5.6-luna    | 60    | 8,398,555 | 7,693,720  | 0           | 27,473 | 15,878    | $0.43     |
| validation-c2         | gpt-5.6-luna    | 53    | 7,978,437 | 7,264,370  | 0           | 30,454 | 18,300    | $0.45     |
| validation-c3         | gpt-5.6-luna    | 22    | 2,592,944 | 2,412,731  | 0           | 14,328 | 7,448     | $0.10     |
| validation-c4         | gpt-5.6-luna    | 21    | 2,283,310 | 2,096,019  | 0           | 10,416 | 5,927     | $0.09     |

```text
sample keys: ['$ai_effort', '$ai_reasoning_tokens'] effort: xhigh
sample effort by stage: {'perspective_selection': 'xhigh', 'issues-review-p1-c1': 'xhigh', 'issues-review-p2-c1': 'xhigh', 'issues-review-p1-c2': 'xhigh', 'issues-review-p1-c3': 'xhigh', 'issues-review-p2-c2': 'xhigh', 'issues-review-p2-c3': 'xhigh', 'issues-review-p3-c2': 'xhigh', 'issues-review-p3-c1': 'xhigh', 'issues-review-p3-c3': 'xhigh', 'blind-spots-c3': 'xhigh', 'blind-spots-c1': 'xhigh', 'blind-spots-c4': 'xhigh', 'blind-spots-c2': 'xhigh', 'dedup': 'xhigh', 'validation-c2': 'xhigh', 'validation-c4': 'xhigh', 'validation-c3': 'xhigh', 'validation-c1': 'xhigh'}
```
