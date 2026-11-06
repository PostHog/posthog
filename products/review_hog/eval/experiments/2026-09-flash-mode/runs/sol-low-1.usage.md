scanned 96 messages, 96 $ai_generation events in window

| stage family          | model           | calls | input     | cache read | output | reasoning | gateway $ | effort |
| --------------------- | --------------- | ----- | --------- | ---------- | ------ | --------- | --------- | ------ |
| blind-spot            | gpt-5.6-sol     | 19    | 1,017,416 | 755,155    | 5,735  | 3,021     | $1.47     | low    |
| dedup                 | claude-sonnet-5 | 1     | 6,124     | 0          | 6,931  | 0         | $0.08     | xhigh  |
| perspective_selection | claude-sonnet-5 | 1     | 5,981     | 0          | 1,448  | 0         | $0.03     | xhigh  |
| review                | gpt-5.6-sol     | 44    | 2,524,126 | 1,962,753  | 14,100 | 6,113     | $3.31     | low    |
| validation            | gpt-5.6-sol     | 31    | 1,860,905 | 1,645,930  | 8,877  | 3,135     | $1.70     | low    |

| stage                 | model           | calls | input     | cache read | cache write | output | reasoning | gateway $ |
| --------------------- | --------------- | ----- | --------- | ---------- | ----------- | ------ | --------- | --------- |
| blind-spots-c1        | gpt-5.6-sol     | 4     | 225,252   | 155,797    | 0           | 1,292  | 711       | $0.37     |
| blind-spots-c2        | gpt-5.6-sol     | 5     | 315,083   | 234,972    | 0           | 2,075  | 1,299     | $0.46     |
| blind-spots-c3        | gpt-5.6-sol     | 5     | 247,915   | 189,545    | 0           | 1,176  | 538       | $0.33     |
| blind-spots-c4        | gpt-5.6-sol     | 5     | 229,166   | 174,841    | 0           | 1,192  | 473       | $0.31     |
| dedup                 | claude-sonnet-5 | 1     | 6,124     | 0          | 0           | 6,931  | 0         | $0.08     |
| issues-review-p1-c1   | gpt-5.6-sol     | 6     | 357,039   | 285,583    | 0           | 1,541  | 486       | $0.43     |
| issues-review-p1-c2   | gpt-5.6-sol     | 4     | 219,334   | 153,941    | 0           | 1,415  | 646       | $0.35     |
| issues-review-p1-c3   | gpt-5.6-sol     | 4     | 194,989   | 132,947    | 0           | 1,237  | 571       | $0.33     |
| issues-review-p2-c1   | gpt-5.6-sol     | 4     | 217,712   | 153,443    | 0           | 1,175  | 418       | $0.34     |
| issues-review-p2-c2   | gpt-5.6-sol     | 5     | 308,221   | 231,022    | 0           | 2,215  | 1,125     | $0.45     |
| issues-review-p2-c3   | gpt-5.6-sol     | 7     | 353,134   | 295,046    | 0           | 1,622  | 792       | $0.38     |
| issues-review-p3-c1   | gpt-5.6-sol     | 6     | 353,680   | 280,506    | 0           | 2,196  | 981       | $0.45     |
| issues-review-p3-c2   | gpt-5.6-sol     | 8     | 520,017   | 430,265    | 0           | 2,699  | 1,094     | $0.59     |
| perspective_selection | claude-sonnet-5 | 1     | 5,981     | 0          | 0           | 1,448  | 0         | $0.03     |
| validation-c1         | gpt-5.6-sol     | 9     | 505,903   | 428,369    | 0           | 2,707  | 883       | $0.54     |
| validation-c2         | gpt-5.6-sol     | 18    | 1,198,450 | 1,106,349  | 0           | 5,190  | 1,974     | $0.91     |
| validation-c3         | gpt-5.6-sol     | 4     | 156,552   | 111,212    | 0           | 980    | 278       | $0.25     |

```text
sample keys: ['$ai_effort', '$ai_reasoning_tokens'] effort: xhigh
sample effort by stage: {'perspective_selection': 'xhigh', 'issues-review-p1-c1': 'low', 'issues-review-p1-c3': 'low', 'issues-review-p2-c1': 'low', 'issues-review-p1-c2': 'low', 'issues-review-p2-c2': 'low', 'issues-review-p2-c3': 'low', 'issues-review-p3-c1': 'low', 'issues-review-p3-c2': 'low', 'blind-spots-c2': 'low', 'blind-spots-c4': 'low', 'blind-spots-c1': 'low', 'blind-spots-c3': 'low', 'dedup': 'xhigh', 'validation-c1': 'low', 'validation-c2': 'low', 'validation-c3': 'low'}
```
