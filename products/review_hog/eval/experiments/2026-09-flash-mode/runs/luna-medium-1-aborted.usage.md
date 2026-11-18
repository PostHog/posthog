scanned 68 messages, 68 $ai_generation events in window

| stage family          | model           | calls | input     | cache read | output | reasoning | gateway $ | effort |
| --------------------- | --------------- | ----- | --------- | ---------- | ------ | --------- | --------- | ------ |
| perspective_selection | claude-sonnet-5 | 1     | 5,981     | 0          | 1,420  | 0         | $0.03     | xhigh  |
| review                | gpt-5.6-luna    | 67    | 4,243,571 | 3,556,854  | 28,069 | 16,043    | $0.24     | medium |

| stage                 | model           | calls | input   | cache read | cache write | output | reasoning | gateway $ |
| --------------------- | --------------- | ----- | ------- | ---------- | ----------- | ------ | --------- | --------- |
| issues-review-p1-c1   | gpt-5.6-luna    | 10    | 637,480 | 546,147    | 0           | 3,224  | 1,631     | $0.03     |
| issues-review-p1-c2   | gpt-5.6-luna    | 7     | 490,340 | 392,386    | 0           | 3,763  | 2,113     | $0.03     |
| issues-review-p1-c3   | gpt-5.6-luna    | 7     | 404,636 | 327,844    | 0           | 2,779  | 1,583     | $0.03     |
| issues-review-p2-c1   | gpt-5.6-luna    | 8     | 452,394 | 379,434    | 0           | 3,610  | 1,965     | $0.03     |
| issues-review-p2-c2   | gpt-5.6-luna    | 7     | 436,159 | 348,699    | 0           | 4,099  | 2,781     | $0.03     |
| issues-review-p2-c3   | gpt-5.6-luna    | 11    | 726,319 | 631,364    | 0           | 3,790  | 2,153     | $0.04     |
| issues-review-p3-c1   | gpt-5.6-luna    | 8     | 462,734 | 385,922    | 0           | 2,723  | 1,362     | $0.03     |
| issues-review-p3-c2   | gpt-5.6-luna    | 9     | 633,509 | 545,058    | 0           | 4,081  | 2,455     | $0.03     |
| perspective_selection | claude-sonnet-5 | 1     | 5,981   | 0          | 0           | 1,420  | 0         | $0.03     |

```text
sample keys: ['$ai_effort', '$ai_reasoning_tokens'] effort: xhigh
sample effort by stage: {'perspective_selection': 'xhigh', 'issues-review-p1-c3': 'medium', 'issues-review-p1-c2': 'medium', 'issues-review-p1-c1': 'medium', 'issues-review-p2-c1': 'medium', 'issues-review-p2-c3': 'medium', 'issues-review-p2-c2': 'medium', 'issues-review-p3-c1': 'medium', 'issues-review-p3-c2': 'medium'}
```
