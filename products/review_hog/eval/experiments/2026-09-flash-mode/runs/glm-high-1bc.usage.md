Composite of two runs on the same report and commit. Reviewer side (selection, review wave, blind-spot) from `glm-high-1b`, whose validation died on a broken local image build. Dedup + validation from `glm-high-1c`, which reused 1b's cached GLM reviewer results (identical 46 raw → 36 deduped findings). 1b's own dedup ($0.22, 2 calls) is excluded because its output was never validated.

| stage family          | model                 | calls | input      | cache read | output  | reasoning | gateway $ | effort |
| --------------------- | --------------------- | ----- | ---------- | ---------- | ------- | --------- | --------- | ------ |
| blind-spot            | zai-org/glm-5.3-flash | 130   | 8,054,575  | 7,732,224  | 359,160 | 347,581   | $0.46     | high   |
| perspective_selection | claude-sonnet-5       | 1     | 5,981      | 0          | 1,662   | 0         | $0.03     | xhigh  |
| review                | zai-org/glm-5.3-flash | 223   | 13,810,506 | 13,007,872 | 355,508 | 328,470   | $0.69     | high   |
| dedup                 | claude-sonnet-5       | 1     | 17,085     | 0          | 8,680   | 0         | $0.12     | xhigh  |
| validation            | zai-org/glm-5.3-flash | 433   | 36,801,972 | 35,972,608 | 117,494 | 70,688    | $1.26     | high   |
