scanned 356 messages, 356 $ai_generation events in window

| stage family          | model                 | calls | input      | cache read | output  | reasoning | gateway $ | effort |
| --------------------- | --------------------- | ----- | ---------- | ---------- | ------- | --------- | --------- | ------ |
| blind-spot            | zai-org/glm-5.3-flash | 130   | 8,054,575  | 7,732,224  | 359,160 | 347,581   | $0.46     | high   |
| dedup                 | claude-sonnet-5       | 2     | 34,170     | 0          | 15,231  | 0         | $0.22     | xhigh  |
| perspective_selection | claude-sonnet-5       | 1     | 5,981      | 0          | 1,662   | 0         | $0.03     | xhigh  |
| review                | zai-org/glm-5.3-flash | 223   | 13,810,506 | 13,007,872 | 355,508 | 328,470   | $0.69     | high   |

| stage                 | model                 | calls | input     | cache read | cache write | output  | reasoning | gateway $ |
| --------------------- | --------------------- | ----- | --------- | ---------- | ----------- | ------- | --------- | --------- |
| blind-spots-c1        | zai-org/glm-5.3-flash | 39    | 2,301,139 | 2,230,528  | 0           | 60,978  | 57,497    | $0.11     |
| blind-spots-c2        | zai-org/glm-5.3-flash | 50    | 3,393,676 | 3,304,192  | 0           | 231,873 | 227,630   | $0.23     |
| blind-spots-c3        | zai-org/glm-5.3-flash | 10    | 484,943   | 425,216    | 0           | 21,305  | 20,599    | $0.03     |
| blind-spots-c4        | zai-org/glm-5.3-flash | 31    | 1,874,817 | 1,772,288  | 0           | 45,004  | 41,855    | $0.09     |
| dedup                 | claude-sonnet-5       | 2     | 34,170    | 0          | 0           | 15,231  | 0         | $0.22     |
| issues-review-p1-c1   | zai-org/glm-5.3-flash | 44    | 2,654,622 | 2,580,224  | 0           | 54,880  | 50,765    | $0.12     |
| issues-review-p1-c2   | zai-org/glm-5.3-flash | 47    | 3,061,884 | 2,903,808  | 0           | 104,057 | 99,073    | $0.16     |
| issues-review-p1-c3   | zai-org/glm-5.3-flash | 21    | 1,329,468 | 1,249,280  | 0           | 21,591  | 19,449    | $0.06     |
| issues-review-p2-c1   | zai-org/glm-5.3-flash | 16    | 835,570   | 774,144    | 0           | 19,704  | 17,186    | $0.04     |
| issues-review-p2-c2   | zai-org/glm-5.3-flash | 22    | 1,421,684 | 1,343,744  | 0           | 71,065  | 68,241    | $0.09     |
| issues-review-p2-c3   | zai-org/glm-5.3-flash | 10    | 514,823   | 420,864    | 0           | 16,131  | 14,638    | $0.03     |
| issues-review-p3-c1   | zai-org/glm-5.3-flash | 12    | 601,145   | 542,976    | 0           | 9,424   | 6,425     | $0.03     |
| issues-review-p3-c2   | zai-org/glm-5.3-flash | 44    | 3,078,017 | 2,922,240  | 0           | 51,234  | 46,859    | $0.14     |
| issues-review-p3-c3   | zai-org/glm-5.3-flash | 7     | 313,293   | 270,592    | 0           | 7,422   | 5,834     | $0.02     |
| perspective_selection | claude-sonnet-5       | 1     | 5,981     | 0          | 0           | 1,662   | 0         | $0.03     |

```text
sample keys: ['$ai_effort', '$ai_reasoning_tokens'] effort: xhigh
sample effort by stage: {'perspective_selection': 'xhigh', 'issues-review-p1-c1': 'high', 'issues-review-p1-c2': 'high', 'issues-review-p2-c1': 'high', 'issues-review-p1-c3': 'high', 'issues-review-p2-c2': 'high', 'issues-review-p2-c3': 'high', 'issues-review-p3-c1': 'high', 'issues-review-p3-c2': 'high', 'issues-review-p3-c3': 'high', 'blind-spots-c4': 'high', 'blind-spots-c3': 'high', 'blind-spots-c2': 'high', 'blind-spots-c1': 'high', 'dedup': 'xhigh'}
```
