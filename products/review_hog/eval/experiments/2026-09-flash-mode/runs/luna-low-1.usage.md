scanned 90 messages, 90 $ai_generation events in window

| stage family          | model           | calls | input     | cache read | output | reasoning | gateway $ | effort |
| --------------------- | --------------- | ----- | --------- | ---------- | ------ | --------- | --------- | ------ |
| blind-spot            | gpt-5.6-luna    | 18    | 838,727   | 627,106    | 3,949  | 1,813     | $0.06     | low    |
| dedup                 | claude-sonnet-5 | 1     | 5,040     | 0          | 12     | 0         | $0.01     | xhigh  |
| perspective_selection | claude-sonnet-5 | 1     | 5,981     | 0          | 1,546  | 0         | $0.03     | xhigh  |
| review                | gpt-5.6-luna    | 42    | 2,105,668 | 1,623,562  | 11,376 | 4,518     | $0.14     | low    |
| validation            | gpt-5.6-luna    | 28    | 1,201,476 | 1,034,905  | 6,872  | 1,335     | $0.06     | low    |

| stage                 | model           | calls | input   | cache read | cache write | output | reasoning | gateway $ |
| --------------------- | --------------- | ----- | ------- | ---------- | ----------- | ------ | --------- | --------- |
| blind-spots-c1        | gpt-5.6-luna    | 5     | 256,542 | 198,652    | 0           | 1,157  | 524       | $0.02     |
| blind-spots-c2        | gpt-5.6-luna    | 4     | 201,201 | 144,852    | 0           | 939    | 530       | $0.02     |
| blind-spots-c3        | gpt-5.6-luna    | 3     | 124,355 | 76,935     | 0           | 792    | 387       | $0.01     |
| blind-spots-c4        | gpt-5.6-luna    | 6     | 256,629 | 206,667    | 0           | 1,061  | 372       | $0.02     |
| dedup                 | claude-sonnet-5 | 1     | 5,040   | 0          | 0           | 12     | 0         | $0.01     |
| issues-review-p1-c1   | gpt-5.6-luna    | 4     | 186,854 | 132,013    | 0           | 930    | 354       | $0.01     |
| issues-review-p1-c2   | gpt-5.6-luna    | 4     | 207,294 | 145,624    | 0           | 1,257  | 492       | $0.02     |
| issues-review-p1-c3   | gpt-5.6-luna    | 7     | 324,221 | 263,475    | 0           | 1,635  | 649       | $0.02     |
| issues-review-p2-c1   | gpt-5.6-luna    | 6     | 317,729 | 253,256    | 0           | 1,568  | 431       | $0.02     |
| issues-review-p2-c2   | gpt-5.6-luna    | 4     | 210,111 | 148,679    | 0           | 1,527  | 878       | $0.02     |
| issues-review-p2-c3   | gpt-5.6-luna    | 6     | 289,420 | 232,836    | 0           | 1,519  | 662       | $0.02     |
| issues-review-p3-c1   | gpt-5.6-luna    | 4     | 201,474 | 140,567    | 0           | 1,194  | 384       | $0.02     |
| issues-review-p3-c2   | gpt-5.6-luna    | 7     | 368,565 | 307,112    | 0           | 1,746  | 668       | $0.02     |
| perspective_selection | claude-sonnet-5 | 1     | 5,981   | 0          | 0           | 1,546  | 0         | $0.03     |
| validation-c1         | gpt-5.6-luna    | 9     | 378,803 | 323,114    | 0           | 2,030  | 376       | $0.02     |
| validation-c2         | gpt-5.6-luna    | 10    | 438,106 | 381,338    | 0           | 2,898  | 529       | $0.02     |
| validation-c3         | gpt-5.6-luna    | 9     | 384,567 | 330,453    | 0           | 1,944  | 430       | $0.02     |

```text
sample keys: ['$ai_effort', '$ai_reasoning_tokens'] effort: xhigh
sample effort by stage: {'perspective_selection': 'xhigh', 'issues-review-p2-c1': 'low', 'issues-review-p1-c1': 'low', 'issues-review-p1-c2': 'low', 'issues-review-p1-c3': 'low', 'issues-review-p2-c3': 'low', 'issues-review-p3-c1': 'low', 'issues-review-p2-c2': 'low', 'issues-review-p3-c2': 'low', 'blind-spots-c4': 'low', 'blind-spots-c1': 'low', 'blind-spots-c2': 'low', 'blind-spots-c3': 'low', 'dedup': 'xhigh', 'validation-c2': 'low', 'validation-c1': 'low', 'validation-c3': 'low'}
```
