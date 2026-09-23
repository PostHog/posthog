scanned 846 messages, 846 $ai_generation events in window

| stage family  | model                 | calls | input      | cache read | output  | reasoning | gateway $ | effort    |
| ------------- | --------------------- | ----- | ---------- | ---------- | ------- | --------- | --------- | --------- |
| blind-spot    | zai-org/glm-5.3-flash | 96    | 5,848,831  | 5,597,696  | 266,126 | 257,636   | $0.34     | high      |
| capture-probe | zai-org/glm-5.3-flash | 1     | 16         | 0          | 8       | 8         | $0.00     | None      |
| dedup         | claude-sonnet-5       | 1     | 24,287     | 0          | 25,256  | 0         | $0.30     | xhigh     |
| review        | zai-org/glm-5.3-flash | 289   | 15,357,957 | 14,295,040 | 385,796 | 350,552   | $0.78     | high      |
| validation    | zai-org/glm-5.3-flash | 459   | 28,059,620 | 27,309,824 | 117,713 | 73,988    | $0.99     | None,high |

| stage               | model                 | calls | input      | cache read | cache write | output  | reasoning | gateway $ |
| ------------------- | --------------------- | ----- | ---------- | ---------- | ----------- | ------- | --------- | --------- |
| blind-spots-c1      | zai-org/glm-5.3-flash | 24    | 1,337,901  | 1,285,888  | 0           | 70,659  | 68,347    | $0.08     |
| blind-spots-c2      | zai-org/glm-5.3-flash | 35    | 2,222,071  | 2,142,464  | 0           | 130,657 | 127,688   | $0.14     |
| blind-spots-c3      | zai-org/glm-5.3-flash | 6     | 293,765    | 246,528    | 0           | 17,396  | 16,728    | $0.02     |
| blind-spots-c4      | zai-org/glm-5.3-flash | 31    | 1,995,094  | 1,922,816  | 0           | 47,414  | 44,873    | $0.09     |
| capture-probe       | zai-org/glm-5.3-flash | 1     | 16         | 0          | 0           | 8       | 8         | $0.00     |
| dedup               | claude-sonnet-5       | 1     | 24,287     | 0          | 0           | 25,256  | 0         | $0.30     |
| issues-review-p1-c1 | zai-org/glm-5.3-flash | 26    | 1,283,599  | 1,131,520  | 0           | 34,775  | 30,743    | $0.07     |
| issues-review-p1-c2 | zai-org/glm-5.3-flash | 52    | 3,240,974  | 3,030,784  | 0           | 97,869  | 92,779    | $0.17     |
| issues-review-p1-c3 | zai-org/glm-5.3-flash | 23    | 1,346,176  | 1,216,000  | 0           | 24,481  | 22,094    | $0.07     |
| issues-review-p1-c4 | zai-org/glm-5.3-flash | 25    | 1,161,700  | 1,100,800  | 0           | 13,704  | 11,417    | $0.05     |
| issues-review-p2-c1 | zai-org/glm-5.3-flash | 28    | 1,655,807  | 1,585,152  | 0           | 45,473  | 41,744    | $0.08     |
| issues-review-p2-c2 | zai-org/glm-5.3-flash | 11    | 583,973    | 520,704    | 0           | 30,394  | 28,164    | $0.04     |
| issues-review-p2-c3 | zai-org/glm-5.3-flash | 7     | 315,077    | 275,200    | 0           | 11,634  | 10,205    | $0.02     |
| issues-review-p2-c4 | zai-org/glm-5.3-flash | 29    | 1,479,251  | 1,425,152  | 0           | 30,885  | 27,952    | $0.07     |
| issues-review-p3-c1 | zai-org/glm-5.3-flash | 19    | 1,082,577  | 972,288    | 0           | 22,826  | 19,868    | $0.06     |
| issues-review-p3-c2 | zai-org/glm-5.3-flash | 27    | 1,533,336  | 1,477,888  | 0           | 60,965  | 56,854    | $0.08     |
| issues-review-p3-c3 | zai-org/glm-5.3-flash | 4     | 160,189    | 122,368    | 0           | 3,948   | 2,909     | $0.01     |
| issues-review-p3-c4 | zai-org/glm-5.3-flash | 38    | 1,515,298  | 1,437,184  | 0           | 8,842   | 5,823     | $0.06     |
| validation-c1       | zai-org/glm-5.3-flash | 105   | 6,468,329  | 6,230,784  | 0           | 26,727  | 13,274    | $0.24     |
| validation-c2       | zai-org/glm-5.3-flash | 251   | 19,643,462 | 19,316,224 | 0           | 75,058  | 52,689    | $0.67     |
| validation-c3       | zai-org/glm-5.3-flash | 80    | 1,159,085  | 1,047,296  | 0           | 7,465   | 3,697     | $0.05     |
| validation-c4       | zai-org/glm-5.3-flash | 23    | 788,744    | 715,520    | 0           | 8,463   | 4,328     | $0.04     |

```text
sample keys: ['$ai_effort', '$ai_reasoning_tokens'] effort: high
sample effort by stage: {'issues-review-p1-c3': 'high', 'issues-review-p1-c1': 'high', 'issues-review-p1-c4': 'high', 'issues-review-p1-c2': 'high', 'issues-review-p2-c1': 'high', 'issues-review-p2-c2': 'high', 'issues-review-p2-c3': 'high', 'capture-probe': None, 'issues-review-p2-c4': 'high', 'issues-review-p3-c1': 'high', 'issues-review-p3-c2': 'high', 'issues-review-p3-c3': 'high', 'issues-review-p3-c4': 'high', 'blind-spots-c1': 'high', 'blind-spots-c3': 'high', 'blind-spots-c4': 'high', 'blind-spots-c2': 'high', 'dedup': 'xhigh', 'validation-c1': 'high', 'validation-c2': 'high', 'validation-c4': 'high', 'validation-c3': None}
```
