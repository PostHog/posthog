scanned 85 messages, 85 $ai_generation events in window

| stage family          | model           | calls | input     | cache read | output | reasoning | gateway $ | effort |
| --------------------- | --------------- | ----- | --------- | ---------- | ------ | --------- | --------- | ------ |
| blind-spot            | gpt-5.6-luna    | 17    | 753,481   | 549,946    | 3,817  | 1,792     | $0.06     | low    |
| dedup                 | claude-sonnet-5 | 1     | 4,643     | 0          | 618    | 0         | $0.02     | xhigh  |
| perspective_selection | claude-sonnet-5 | 1     | 5,981     | 0          | 526    | 0         | $0.02     | xhigh  |
| review                | gpt-5.6-luna    | 43    | 2,140,430 | 1,614,449  | 11,467 | 4,948     | $0.15     | low    |
| validation            | gpt-5.6-luna    | 23    | 996,347   | 839,542    | 5,987  | 1,416     | $0.06     | low    |

| stage                 | model           | calls | input   | cache read | cache write | output | reasoning | gateway $ |
| --------------------- | --------------- | ----- | ------- | ---------- | ----------- | ------ | --------- | --------- |
| blind-spots-c1        | gpt-5.6-luna    | 5     | 244,811 | 187,470    | 0           | 1,234  | 498       | $0.02     |
| blind-spots-c2        | gpt-5.6-luna    | 4     | 187,301 | 136,861    | 0           | 889    | 407       | $0.01     |
| blind-spots-c3        | gpt-5.6-luna    | 3     | 124,649 | 76,685     | 0           | 704    | 390       | $0.01     |
| blind-spots-c4        | gpt-5.6-luna    | 5     | 196,720 | 148,930    | 0           | 990    | 497       | $0.01     |
| dedup                 | claude-sonnet-5 | 1     | 4,643   | 0          | 0           | 618    | 0         | $0.02     |
| issues-review-p1-c1   | gpt-5.6-luna    | 6     | 291,912 | 236,020    | 0           | 1,302  | 621       | $0.02     |
| issues-review-p1-c2   | gpt-5.6-luna    | 4     | 198,030 | 141,222    | 0           | 1,259  | 615       | $0.02     |
| issues-review-p1-c3   | gpt-5.6-luna    | 7     | 362,235 | 288,870    | 0           | 1,521  | 514       | $0.02     |
| issues-review-p2-c1   | gpt-5.6-luna    | 4     | 194,382 | 139,111    | 0           | 1,143  | 430       | $0.02     |
| issues-review-p2-c2   | gpt-5.6-luna    | 4     | 204,961 | 145,646    | 0           | 1,375  | 666       | $0.02     |
| issues-review-p2-c3   | gpt-5.6-luna    | 7     | 359,904 | 298,425    | 0           | 1,751  | 764       | $0.02     |
| issues-review-p3-c1   | gpt-5.6-luna    | 3     | 143,895 | 89,707     | 0           | 1,019  | 474       | $0.01     |
| issues-review-p3-c2   | gpt-5.6-luna    | 5     | 259,009 | 198,831    | 0           | 1,206  | 547       | $0.02     |
| issues-review-p3-c3   | gpt-5.6-luna    | 3     | 126,102 | 76,617     | 0           | 891    | 317       | $0.01     |
| perspective_selection | claude-sonnet-5 | 1     | 5,981   | 0          | 0           | 526    | 0         | $0.02     |
| validation-c1         | gpt-5.6-luna    | 5     | 206,294 | 157,784    | 0           | 1,257  | 230       | $0.01     |
| validation-c2         | gpt-5.6-luna    | 10    | 465,659 | 409,715    | 0           | 2,840  | 619       | $0.02     |
| validation-c3         | gpt-5.6-luna    | 8     | 324,394 | 272,043    | 0           | 1,890  | 567       | $0.02     |

```text
sample keys: ['$ai_effort', '$ai_reasoning_tokens'] effort: xhigh
sample effort by stage: {'perspective_selection': 'xhigh', 'issues-review-p2-c1': 'low', 'issues-review-p1-c2': 'low', 'issues-review-p1-c3': 'low', 'issues-review-p1-c1': 'low', 'issues-review-p2-c3': 'low', 'issues-review-p2-c2': 'low', 'issues-review-p3-c2': 'low', 'issues-review-p3-c1': 'low', 'issues-review-p3-c3': 'low', 'blind-spots-c3': 'low', 'blind-spots-c4': 'low', 'blind-spots-c1': 'low', 'blind-spots-c2': 'low', 'dedup': 'xhigh', 'validation-c1': 'low', 'validation-c2': 'low', 'validation-c3': 'low'}
```
