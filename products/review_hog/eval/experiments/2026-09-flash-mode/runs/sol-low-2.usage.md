scanned 117 messages, 117 $ai_generation events in window

| stage family          | model           | calls | input     | cache read | output | reasoning | gateway $ | effort |
| --------------------- | --------------- | ----- | --------- | ---------- | ------ | --------- | --------- | ------ |
| blind-spot            | gpt-5.6-sol     | 25    | 1,331,656 | 1,053,065  | 7,322  | 3,361     | $1.68     | low    |
| dedup                 | claude-sonnet-5 | 1     | 7,566     | 0          | 4,271  | 0         | $0.06     | xhigh  |
| perspective_selection | claude-sonnet-5 | 1     | 5,981     | 0          | 1,550  | 0         | $0.03     | xhigh  |
| review                | gpt-5.6-sol     | 57    | 3,218,677 | 2,565,678  | 17,241 | 7,426     | $3.98     | low    |
| validation            | gpt-5.6-sol     | 33    | 1,790,139 | 1,570,135  | 8,751  | 2,929     | $1.68     | low    |

| stage                 | model           | calls | input   | cache read | cache write | output | reasoning | gateway $ |
| --------------------- | --------------- | ----- | ------- | ---------- | ----------- | ------ | --------- | --------- |
| blind-spots-c1        | gpt-5.6-sol     | 7     | 420,804 | 339,441    | 0           | 2,112  | 983       | $0.50     |
| blind-spots-c2        | gpt-5.6-sol     | 5     | 280,844 | 207,315    | 0           | 2,236  | 1,321     | $0.42     |
| blind-spots-c3        | gpt-5.6-sol     | 7     | 358,910 | 291,983    | 0           | 1,930  | 720       | $0.42     |
| blind-spots-c4        | gpt-5.6-sol     | 6     | 271,098 | 214,326    | 0           | 1,044  | 337       | $0.33     |
| dedup                 | claude-sonnet-5 | 1     | 7,566   | 0          | 0           | 4,271  | 0         | $0.06     |
| issues-review-p1-c1   | gpt-5.6-sol     | 8     | 511,209 | 425,013    | 0           | 2,333  | 1,010     | $0.56     |
| issues-review-p1-c2   | gpt-5.6-sol     | 5     | 270,576 | 200,668    | 0           | 2,127  | 1,030     | $0.40     |
| issues-review-p1-c3   | gpt-5.6-sol     | 7     | 364,380 | 294,483    | 0           | 1,748  | 646       | $0.43     |
| issues-review-p2-c1   | gpt-5.6-sol     | 5     | 290,985 | 216,468    | 0           | 1,379  | 535       | $0.41     |
| issues-review-p2-c2   | gpt-5.6-sol     | 5     | 306,231 | 229,393    | 0           | 2,416  | 1,252     | $0.45     |
| issues-review-p2-c3   | gpt-5.6-sol     | 7     | 376,001 | 312,195    | 0           | 1,606  | 758       | $0.41     |
| issues-review-p3-c1   | gpt-5.6-sol     | 7     | 387,292 | 319,902    | 0           | 2,098  | 805       | $0.44     |
| issues-review-p3-c2   | gpt-5.6-sol     | 5     | 299,647 | 224,293    | 0           | 1,995  | 943       | $0.43     |
| issues-review-p3-c3   | gpt-5.6-sol     | 8     | 412,356 | 343,263    | 0           | 1,539  | 447       | $0.44     |
| perspective_selection | claude-sonnet-5 | 1     | 5,981   | 0          | 0           | 1,550  | 0         | $0.03     |
| validation-c1         | gpt-5.6-sol     | 11    | 575,292 | 503,034    | 0           | 3,327  | 1,366     | $0.56     |
| validation-c2         | gpt-5.6-sol     | 14    | 895,110 | 800,014    | 0           | 3,574  | 918       | $0.77     |
| validation-c3         | gpt-5.6-sol     | 8     | 319,737 | 267,087    | 0           | 1,850  | 645       | $0.35     |

```text
sample keys: ['$ai_effort', '$ai_reasoning_tokens'] effort: xhigh
sample effort by stage: {'perspective_selection': 'xhigh', 'issues-review-p1-c2': 'low', 'issues-review-p1-c1': 'low', 'issues-review-p2-c1': 'low', 'issues-review-p1-c3': 'low', 'issues-review-p2-c3': 'low', 'issues-review-p2-c2': 'low', 'issues-review-p3-c1': 'low', 'issues-review-p3-c2': 'low', 'issues-review-p3-c3': 'low', 'blind-spots-c2': 'low', 'blind-spots-c4': 'low', 'blind-spots-c1': 'low', 'blind-spots-c3': 'low', 'dedup': 'xhigh', 'validation-c2': 'low', 'validation-c3': 'low', 'validation-c1': 'low'}
```
