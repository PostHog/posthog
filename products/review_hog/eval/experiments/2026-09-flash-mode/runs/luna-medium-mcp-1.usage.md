# Luna medium without inlined skill bodies: gateway usage

All 190 requests have captured prices. Total model cost: **$0.60319142**.

Ten requests ($0.02285444) lacked a stage label. Their exact session ID matches the completed `validation-c4` TaskRun.
The [attribution audit](luna-medium-mcp-1.stage_attribution.json) binds the [raw capture](luna-medium-mcp-1.ai_usage.raw.json) and [normalized ledger](luna-medium-mcp-1.ai_usage.json) by SHA-256.
Only those ten stage labels change; every captured token counter and price remains intact.

| Stage family          | Model           | Effort | Calls | Input     | Cache read | Cache write | Output | Reasoning | Gateway $   |
| --------------------- | --------------- | ------ | ----- | --------- | ---------- | ----------- | ------ | --------- | ----------- |
| blind-spot            | gpt-5.6-luna    | medium | 33    | 1,763,259 | 1,492,748  | 0           | 11,245 | 6,818     | $0.09745116 |
| dedup                 | claude-sonnet-5 | xhigh  | 1     | 6,843     | 0          | 0           | 4,966  | 0         | $0.06334600 |
| perspective_selection | claude-sonnet-5 | xhigh  | 1     | 5,981     | 0          | 0           | 1,508  | 0         | $0.02704200 |
| review                | gpt-5.6-luna    | medium | 93    | 5,675,141 | 4,989,625  | 0           | 30,308 | 17,893    | $0.27326530 |
| validation            | gpt-5.6-luna    | medium | 62    | 3,293,580 | 2,973,828  | 0           | 15,550 | 6,311     | $0.14208696 |

| Stage                 | Model           | Effort | Calls | Input     | Cache read | Cache write | Output | Reasoning | Gateway $   |
| --------------------- | --------------- | ------ | ----- | --------- | ---------- | ----------- | ------ | --------- | ----------- |
| blind-spots-c1        | gpt-5.6-luna    | medium | 7     | 354,297   | 292,195    | 0           | 1,640  | 721       | $0.02023230 |
| blind-spots-c2        | gpt-5.6-luna    | medium | 12    | 790,398   | 700,009    | 0           | 5,621  | 4,030     | $0.03882318 |
| blind-spots-c3        | gpt-5.6-luna    | medium | 7     | 339,921   | 276,354    | 0           | 2,281  | 1,252     | $0.02097768 |
| blind-spots-c4        | gpt-5.6-luna    | medium | 7     | 278,643   | 224,190    | 0           | 1,703  | 815       | $0.01741800 |
| dedup                 | claude-sonnet-5 | xhigh  | 1     | 6,843     | 0          | 0           | 4,966  | 0         | $0.06334600 |
| issues-review-p1-c1   | gpt-5.6-luna    | medium | 16    | 1,061,816 | 963,839    | 0           | 4,157  | 2,223     | $0.04386058 |
| issues-review-p1-c2   | gpt-5.6-luna    | medium | 12    | 743,385   | 651,756    | 0           | 4,328  | 2,721     | $0.03655452 |
| issues-review-p1-c3   | gpt-5.6-luna    | medium | 13    | 755,035   | 667,351    | 0           | 3,350  | 1,628     | $0.03490382 |
| issues-review-p2-c1   | gpt-5.6-luna    | medium | 9     | 508,956   | 433,666    | 0           | 3,212  | 1,770     | $0.02758572 |
| issues-review-p2-c2   | gpt-5.6-luna    | medium | 16    | 1,099,741 | 993,871    | 0           | 4,720  | 2,983     | $0.04671542 |
| issues-review-p2-c3   | gpt-5.6-luna    | medium | 8     | 387,681   | 320,181    | 0           | 3,716  | 2,575     | $0.02436282 |
| issues-review-p3-c1   | gpt-5.6-luna    | medium | 11    | 678,418   | 590,489    | 0           | 3,494  | 1,933     | $0.03358838 |
| issues-review-p3-c2   | gpt-5.6-luna    | medium | 8     | 440,109   | 368,472    | 0           | 3,331  | 2,060     | $0.02569404 |
| perspective_selection | claude-sonnet-5 | xhigh  | 1     | 5,981     | 0          | 0           | 1,508  | 0         | $0.02704200 |
| validation-c1         | gpt-5.6-luna    | medium | 16    | 831,966   | 747,884    | 0           | 4,745  | 2,198     | $0.03746808 |
| validation-c2         | gpt-5.6-luna    | medium | 19    | 1,165,003 | 1,069,220  | 0           | 5,610  | 2,479     | $0.04727300 |
| validation-c3         | gpt-5.6-luna    | medium | 17    | 850,093   | 775,602    | 0           | 3,401  | 1,139     | $0.03449144 |
| validation-c4         | gpt-5.6-luna    | medium | 10    | 446,518   | 381,122    | 0           | 1,794  | 495       | $0.02285444 |

Costs cover gateway model generations only. Modal infrastructure, smoke checks, aborted attempts, and judging are excluded.
