scanned 434 messages, 434 $ai_generation events in window

| stage family | model                 | calls | input      | cache read | output  | reasoning | gateway $ | effort |
| ------------ | --------------------- | ----- | ---------- | ---------- | ------- | --------- | --------- | ------ |
| dedup        | claude-sonnet-5       | 1     | 17,085     | 0          | 8,680   | 0         | $0.12     | xhigh  |
| validation   | zai-org/glm-5.3-flash | 433   | 36,801,972 | 35,972,608 | 117,494 | 70,688    | $1.26     | high   |

| stage         | model                 | calls | input      | cache read | cache write | output | reasoning | gateway $ |
| ------------- | --------------------- | ----- | ---------- | ---------- | ----------- | ------ | --------- | --------- |
| dedup         | claude-sonnet-5       | 1     | 17,085     | 0          | 0           | 8,680  | 0         | $0.12     |
| validation-c1 | zai-org/glm-5.3-flash | 65    | 3,453,587  | 3,295,232  | 0           | 20,314 | 8,914     | $0.13     |
| validation-c2 | zai-org/glm-5.3-flash | 321   | 31,699,783 | 31,298,048 | 0           | 80,430 | 51,885    | $1.04     |
| validation-c3 | zai-org/glm-5.3-flash | 29    | 1,011,081  | 910,592    | 0           | 7,962  | 3,934     | $0.05     |
| validation-c4 | zai-org/glm-5.3-flash | 18    | 637,521    | 468,736    | 0           | 8,788  | 5,955     | $0.04     |

```text
sample keys: ['$ai_effort', '$ai_reasoning_tokens'] effort: xhigh
sample effort by stage: {'dedup': 'xhigh', 'validation-c2': 'high', 'validation-c3': 'high', 'validation-c4': 'high', 'validation-c1': 'high'}
```
