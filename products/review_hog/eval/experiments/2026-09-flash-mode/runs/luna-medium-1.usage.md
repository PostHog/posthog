scanned 151 messages, 151 $ai_generation events in window

| stage family          | model           | calls | input     | cache read | output | reasoning | gateway $ | effort |
| --------------------- | --------------- | ----- | --------- | ---------- | ------ | --------- | --------- | ------ |
| blind-spot            | gpt-5.6-luna    | 28    | 1,601,352 | 1,307,086  | 11,752 | 7,028     | $0.10     | medium |
| dedup                 | claude-sonnet-5 | 1     | 6,686     | 0          | 2,102  | 0         | $0.03     | xhigh  |
| perspective_selection | claude-sonnet-5 | 1     | 5,981     | 0          | 1,330  | 0         | $0.03     | xhigh  |
| review                | gpt-5.6-luna    | 65    | 4,254,203 | 3,574,796  | 27,958 | 16,321    | $0.24     | medium |
| validation            | gpt-5.6-luna    | 56    | 3,247,730 | 2,929,509  | 15,970 | 6,730     | $0.14     | medium |

| stage                 | model           | calls | input     | cache read | cache write | output | reasoning | gateway $ |
| --------------------- | --------------- | ----- | --------- | ---------- | ----------- | ------ | --------- | --------- |
| blind-spots-c1        | gpt-5.6-luna    | 7     | 422,503   | 346,692    | 0           | 2,718  | 1,587     | $0.03     |
| blind-spots-c2        | gpt-5.6-luna    | 6     | 374,514   | 295,404    | 0           | 3,175  | 1,996     | $0.03     |
| blind-spots-c3        | gpt-5.6-luna    | 8     | 456,852   | 380,997    | 0           | 2,801  | 1,567     | $0.03     |
| blind-spots-c4        | gpt-5.6-luna    | 7     | 347,483   | 283,993    | 0           | 3,058  | 1,878     | $0.02     |
| dedup                 | claude-sonnet-5 | 1     | 6,686     | 0          | 0           | 2,102  | 0         | $0.03     |
| issues-review-p1-c1   | gpt-5.6-luna    | 9     | 585,438   | 501,663    | 0           | 2,874  | 1,219     | $0.03     |
| issues-review-p1-c2   | gpt-5.6-luna    | 9     | 583,584   | 491,370    | 0           | 3,926  | 2,428     | $0.03     |
| issues-review-p1-c3   | gpt-5.6-luna    | 6     | 331,552   | 259,916    | 0           | 2,391  | 1,247     | $0.02     |
| issues-review-p2-c1   | gpt-5.6-luna    | 10    | 724,593   | 619,489    | 0           | 4,161  | 2,368     | $0.04     |
| issues-review-p2-c2   | gpt-5.6-luna    | 8     | 555,968   | 469,134    | 0           | 4,064  | 2,626     | $0.03     |
| issues-review-p2-c3   | gpt-5.6-luna    | 8     | 457,391   | 376,117    | 0           | 3,133  | 1,919     | $0.03     |
| issues-review-p3-c1   | gpt-5.6-luna    | 5     | 277,641   | 208,693    | 0           | 2,631  | 1,534     | $0.02     |
| issues-review-p3-c2   | gpt-5.6-luna    | 10    | 738,036   | 648,414    | 0           | 4,778  | 2,980     | $0.04     |
| perspective_selection | claude-sonnet-5 | 1     | 5,981     | 0          | 0           | 1,330  | 0         | $0.03     |
| validation-c1         | gpt-5.6-luna    | 14    | 838,492   | 751,854    | 0           | 3,686  | 1,230     | $0.04     |
| validation-c2         | gpt-5.6-luna    | 19    | 1,254,297 | 1,164,836  | 0           | 5,462  | 2,297     | $0.05     |
| validation-c3         | gpt-5.6-luna    | 15    | 704,408   | 638,284    | 0           | 4,607  | 2,476     | $0.03     |
| validation-c4         | gpt-5.6-luna    | 8     | 450,533   | 374,535    | 0           | 2,215  | 727       | $0.03     |

```text
sample keys: ['$ai_effort', '$ai_reasoning_tokens'] effort: xhigh
sample effort by stage: {'perspective_selection': 'xhigh', 'issues-review-p2-c1': 'medium', 'issues-review-p1-c3': 'medium', 'issues-review-p1-c2': 'medium', 'issues-review-p1-c1': 'medium', 'issues-review-p2-c3': 'medium', 'issues-review-p2-c2': 'medium', 'issues-review-p3-c2': 'medium', 'issues-review-p3-c1': 'medium', 'blind-spots-c4': 'medium', 'blind-spots-c3': 'medium', 'blind-spots-c2': 'medium', 'blind-spots-c1': 'medium', 'dedup': 'xhigh', 'validation-c3': 'medium', 'validation-c2': 'medium', 'validation-c4': 'medium', 'validation-c1': 'medium'}
```
