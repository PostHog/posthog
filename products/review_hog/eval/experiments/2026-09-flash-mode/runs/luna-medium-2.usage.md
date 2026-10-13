scanned 155 messages, 155 $ai_generation events in window

| stage family          | model           | calls | input     | cache read | output | reasoning | gateway $ | effort |
| --------------------- | --------------- | ----- | --------- | ---------- | ------ | --------- | --------- | ------ |
| blind-spot            | gpt-5.6-luna    | 29    | 1,710,161 | 1,406,697  | 10,756 | 5,864     | $0.10     | medium |
| dedup                 | claude-sonnet-5 | 1     | 6,784     | 0          | 9,307  | 0         | $0.11     | xhigh  |
| perspective_selection | claude-sonnet-5 | 1     | 5,981     | 0          | 577    | 0         | $0.02     | xhigh  |
| review                | gpt-5.6-luna    | 83    | 5,724,638 | 4,906,166  | 32,338 | 17,709    | $0.30     | medium |
| validation            | gpt-5.6-luna    | 41    | 2,323,482 | 2,035,903  | 12,682 | 4,931     | $0.11     | medium |

| stage                 | model           | calls | input     | cache read | cache write | output | reasoning | gateway $ |
| --------------------- | --------------- | ----- | --------- | ---------- | ----------- | ------ | --------- | --------- |
| blind-spots-c1        | gpt-5.6-luna    | 8     | 530,229   | 444,940    | 0           | 2,506  | 1,282     | $0.03     |
| blind-spots-c2        | gpt-5.6-luna    | 9     | 561,960   | 478,010    | 0           | 3,686  | 2,164     | $0.03     |
| blind-spots-c3        | gpt-5.6-luna    | 6     | 324,093   | 252,507    | 0           | 2,076  | 1,091     | $0.02     |
| blind-spots-c4        | gpt-5.6-luna    | 6     | 293,879   | 231,240    | 0           | 2,488  | 1,327     | $0.02     |
| dedup                 | claude-sonnet-5 | 1     | 6,784     | 0          | 0           | 9,307  | 0         | $0.11     |
| issues-review-p1-c1   | gpt-5.6-luna    | 7     | 474,834   | 382,513    | 0           | 2,606  | 1,095     | $0.03     |
| issues-review-p1-c2   | gpt-5.6-luna    | 7     | 472,378   | 386,799    | 0           | 3,192  | 1,812     | $0.03     |
| issues-review-p1-c3   | gpt-5.6-luna    | 12    | 793,708   | 691,463    | 0           | 3,800  | 2,128     | $0.04     |
| issues-review-p2-c1   | gpt-5.6-luna    | 9     | 570,129   | 488,940    | 0           | 4,177  | 2,516     | $0.03     |
| issues-review-p2-c2   | gpt-5.6-luna    | 14    | 1,232,887 | 1,114,696  | 0           | 5,017  | 2,746     | $0.05     |
| issues-review-p2-c3   | gpt-5.6-luna    | 8     | 443,418   | 365,077    | 0           | 3,438  | 1,880     | $0.03     |
| issues-review-p3-c1   | gpt-5.6-luna    | 10    | 684,338   | 596,678    | 0           | 3,737  | 2,038     | $0.03     |
| issues-review-p3-c2   | gpt-5.6-luna    | 6     | 388,454   | 305,365    | 0           | 3,246  | 1,843     | $0.03     |
| issues-review-p3-c3   | gpt-5.6-luna    | 10    | 664,492   | 574,635    | 0           | 3,125  | 1,651     | $0.03     |
| perspective_selection | claude-sonnet-5 | 1     | 5,981     | 0          | 0           | 577    | 0         | $0.02     |
| validation-c1         | gpt-5.6-luna    | 11    | 557,449   | 492,808    | 0           | 2,988  | 904       | $0.03     |
| validation-c2         | gpt-5.6-luna    | 15    | 1,079,229 | 974,113    | 0           | 5,852  | 2,868     | $0.05     |
| validation-c3         | gpt-5.6-luna    | 7     | 290,422   | 237,907    | 0           | 1,994  | 670       | $0.02     |
| validation-c4         | gpt-5.6-luna    | 8     | 396,382   | 331,075    | 0           | 1,848  | 489       | $0.02     |

```text
sample keys: ['$ai_effort', '$ai_reasoning_tokens'] effort: xhigh
sample effort by stage: {'perspective_selection': 'xhigh', 'issues-review-p1-c3': 'medium', 'issues-review-p1-c2': 'medium', 'issues-review-p1-c1': 'medium', 'issues-review-p2-c1': 'medium', 'issues-review-p2-c2': 'medium', 'issues-review-p2-c3': 'medium', 'issues-review-p3-c1': 'medium', 'issues-review-p3-c2': 'medium', 'issues-review-p3-c3': 'medium', 'blind-spots-c1': 'medium', 'blind-spots-c3': 'medium', 'blind-spots-c4': 'medium', 'blind-spots-c2': 'medium', 'dedup': 'xhigh', 'validation-c4': 'medium', 'validation-c1': 'medium', 'validation-c2': 'medium', 'validation-c3': 'medium'}
```
