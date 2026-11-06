scanned 300 messages, 300 $ai_generation events in window

| stage family          | model           | calls | input      | cache read | output  | reasoning | gateway $ | effort |
| --------------------- | --------------- | ----- | ---------- | ---------- | ------- | --------- | --------- | ------ |
| blind-spot            | gpt-5.6-sol     | 44    | 2,738,410  | 2,372,882  | 19,415  | 13,219    | $2.80     | medium |
| dedup                 | claude-sonnet-5 | 1     | 8,677      | 0          | 13,414  | 0         | $0.15     | xhigh  |
| perspective_selection | claude-sonnet-5 | 1     | 5,981      | 0          | 506     | 0         | $0.02     | xhigh  |
| review                | gpt-5.6-sol     | 121   | 8,269,099  | 7,372,485  | 44,873  | 27,426    | $7.43     | medium |
| validation            | claude-opus-5   | 133   | 16,645,719 | 15,829,016 | 117,047 | 0         | $15.80    | xhigh  |
