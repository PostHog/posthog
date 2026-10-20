scanned 529 messages, 529 $ai_generation events in window

| stage family          | model           | calls | input      | cache read | output  | reasoning | gateway $ | effort |
| --------------------- | --------------- | ----- | ---------- | ---------- | ------- | --------- | --------- | ------ |
| blind-spot            | gpt-5.6-luna    | 101   | 12,375,089 | 11,598,986 | 81,314  | 65,837    | $0.48     | xhigh  |
| dedup                 | claude-sonnet-5 | 1     | 12,109     | 0          | 22,282  | 0         | $0.25     | xhigh  |
| perspective_selection | claude-sonnet-5 | 1     | 5,981      | 0          | 500     | 0         | $0.02     | xhigh  |
| review                | gpt-5.6-luna    | 269   | 39,182,547 | 36,865,390 | 207,611 | 157,396   | $1.63     | xhigh  |
| validation            | gpt-5.6-luna    | 157   | 22,251,401 | 20,492,590 | 87,471  | 49,935    | $1.11     | xhigh  |

| stage                 | model           | calls | input      | cache read | cache write | output | reasoning | gateway $ |
| --------------------- | --------------- | ----- | ---------- | ---------- | ----------- | ------ | --------- | --------- |
| blind-spots-c1        | gpt-5.6-luna    | 23    | 2,677,462  | 2,493,161  | 0           | 18,048 | 14,395    | $0.11     |
| blind-spots-c2        | gpt-5.6-luna    | 28    | 3,819,690  | 3,611,311  | 0           | 27,904 | 23,115    | $0.15     |
| blind-spots-c3        | gpt-5.6-luna    | 25    | 2,844,855  | 2,662,288  | 0           | 18,205 | 14,936    | $0.11     |
| blind-spots-c4        | gpt-5.6-luna    | 25    | 3,033,082  | 2,832,226  | 0           | 17,157 | 13,391    | $0.12     |
| dedup                 | claude-sonnet-5 | 1     | 12,109     | 0          | 0           | 22,282 | 0         | $0.25     |
| issues-review-p1-c1   | gpt-5.6-luna    | 31    | 4,284,619  | 4,041,262  | 0           | 16,854 | 11,024    | $0.15     |
| issues-review-p1-c2   | gpt-5.6-luna    | 29    | 3,683,486  | 3,471,656  | 0           | 25,849 | 21,041    | $0.14     |
| issues-review-p1-c3   | gpt-5.6-luna    | 30    | 3,654,923  | 3,463,109  | 0           | 21,895 | 17,774    | $0.13     |
| issues-review-p2-c1   | gpt-5.6-luna    | 51    | 10,342,618 | 9,675,551  | 0           | 38,857 | 29,037    | $0.55     |
| issues-review-p2-c2   | gpt-5.6-luna    | 33    | 5,668,542  | 5,397,826  | 0           | 30,012 | 23,588    | $0.20     |
| issues-review-p2-c3   | gpt-5.6-luna    | 27    | 3,401,095  | 3,203,715  | 0           | 15,281 | 11,369    | $0.12     |
| issues-review-p3-c1   | gpt-5.6-luna    | 16    | 1,734,709  | 1,556,131  | 0           | 15,136 | 9,805     | $0.09     |
| issues-review-p3-c2   | gpt-5.6-luna    | 33    | 4,594,749  | 4,380,646  | 0           | 32,129 | 25,397    | $0.17     |
| issues-review-p3-c3   | gpt-5.6-luna    | 19    | 1,817,806  | 1,675,494  | 0           | 11,598 | 8,361     | $0.08     |
| perspective_selection | claude-sonnet-5 | 1     | 5,981      | 0          | 0           | 500    | 0         | $0.02     |
| validation-c1         | gpt-5.6-luna    | 57    | 8,247,628  | 7,521,480  | 0           | 26,659 | 15,343    | $0.44     |
| validation-c2         | gpt-5.6-luna    | 53    | 8,919,655  | 8,217,126  | 0           | 35,026 | 19,365    | $0.48     |
| validation-c3         | gpt-5.6-luna    | 20    | 2,092,647  | 1,930,841  | 0           | 14,367 | 8,318     | $0.09     |
| validation-c4         | gpt-5.6-luna    | 27    | 2,991,471  | 2,823,143  | 0           | 11,419 | 6,909     | $0.10     |

```text
sample keys: ['$ai_effort', '$ai_reasoning_tokens'] effort: xhigh
sample effort by stage: {'perspective_selection': 'xhigh', 'issues-review-p1-c1': 'xhigh', 'issues-review-p2-c1': 'xhigh', 'issues-review-p1-c3': 'xhigh', 'issues-review-p1-c2': 'xhigh', 'issues-review-p2-c2': 'xhigh', 'issues-review-p2-c3': 'xhigh', 'issues-review-p3-c1': 'xhigh', 'issues-review-p3-c2': 'xhigh', 'issues-review-p3-c3': 'xhigh', 'blind-spots-c3': 'xhigh', 'blind-spots-c1': 'xhigh', 'blind-spots-c4': 'xhigh', 'blind-spots-c2': 'xhigh', 'dedup': 'xhigh', 'validation-c2': 'xhigh', 'validation-c4': 'xhigh', 'validation-c3': 'xhigh', 'validation-c1': 'xhigh'}
```
