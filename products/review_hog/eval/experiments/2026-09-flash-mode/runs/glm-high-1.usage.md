scanned 381 messages, 381 $ai_generation events in window

| stage family | model                 | calls | input      | cache read | output  | reasoning | gateway $ | effort |
| ------------ | --------------------- | ----- | ---------- | ---------- | ------- | --------- | --------- | ------ |
| blind-spot   | zai-org/glm-5.3-flash | 100   | 5,704,489  | 5,474,048  | 193,706 | 184,436   | $0.30     | high   |
| review       | zai-org/glm-5.3-flash | 281   | 16,100,991 | 15,073,792 | 434,778 | 400,577   | $0.82     | high   |

| stage               | model                 | calls | input     | cache read | cache write | output  | reasoning | gateway $ |
| ------------------- | --------------------- | ----- | --------- | ---------- | ----------- | ------- | --------- | --------- |
| blind-spots-c1      | zai-org/glm-5.3-flash | 26    | 1,515,561 | 1,455,616  | 0           | 34,150  | 31,417    | $0.07     |
| blind-spots-c2      | zai-org/glm-5.3-flash | 30    | 2,067,614 | 1,991,680  | 0           | 120,633 | 118,596   | $0.13     |
| blind-spots-c3      | zai-org/glm-5.3-flash | 22    | 1,179,138 | 1,128,960  | 0           | 23,519  | 21,189    | $0.05     |
| blind-spots-c4      | zai-org/glm-5.3-flash | 22    | 942,176   | 897,792    | 0           | 15,404  | 13,234    | $0.04     |
| issues-review-p1-c1 | zai-org/glm-5.3-flash | 23    | 1,259,844 | 1,196,288  | 0           | 39,377  | 35,924    | $0.07     |
| issues-review-p1-c2 | zai-org/glm-5.3-flash | 32    | 1,984,105 | 1,908,736  | 0           | 92,176  | 88,300    | $0.11     |
| issues-review-p1-c3 | zai-org/glm-5.3-flash | 8     | 360,732   | 319,488    | 0           | 12,923  | 11,292    | $0.02     |
| issues-review-p1-c4 | zai-org/glm-5.3-flash | 40    | 1,876,565 | 1,784,576  | 0           | 27,961  | 23,959    | $0.08     |
| issues-review-p2-c1 | zai-org/glm-5.3-flash | 33    | 2,092,811 | 2,025,216  | 0           | 52,290  | 48,594    | $0.10     |
| issues-review-p2-c2 | zai-org/glm-5.3-flash | 24    | 1,594,275 | 1,523,968  | 0           | 103,227 | 100,090   | $0.11     |
| issues-review-p2-c3 | zai-org/glm-5.3-flash | 8     | 364,806   | 216,576    | 0           | 11,863  | 10,520    | $0.03     |
| issues-review-p2-c4 | zai-org/glm-5.3-flash | 45    | 2,627,338 | 2,513,920  | 0           | 26,675  | 23,702    | $0.11     |
| issues-review-p3-c1 | zai-org/glm-5.3-flash | 18    | 926,142   | 867,072    | 0           | 17,647  | 14,889    | $0.04     |
| issues-review-p3-c2 | zai-org/glm-5.3-flash | 16    | 1,037,123 | 914,944    | 0           | 23,460  | 20,354    | $0.06     |
| issues-review-p3-c3 | zai-org/glm-5.3-flash | 7     | 306,537   | 266,240    | 0           | 8,380   | 6,754     | $0.02     |
| issues-review-p3-c4 | zai-org/glm-5.3-flash | 27    | 1,670,713 | 1,536,768  | 0           | 18,799  | 16,199    | $0.08     |

```text
sample keys: ['$ai_effort', '$ai_reasoning_tokens'] effort: high
sample effort by stage: {'issues-review-p1-c4': 'high', 'issues-review-p1-c1': 'high', 'issues-review-p1-c3': 'high', 'issues-review-p1-c2': 'high', 'issues-review-p2-c1': 'high', 'issues-review-p2-c2': 'high', 'issues-review-p2-c3': 'high', 'issues-review-p2-c4': 'high', 'issues-review-p3-c1': 'high', 'issues-review-p3-c2': 'high', 'issues-review-p3-c3': 'high', 'issues-review-p3-c4': 'high', 'blind-spots-c3': 'high', 'blind-spots-c4': 'high', 'blind-spots-c2': 'high', 'blind-spots-c1': 'high'}
```
