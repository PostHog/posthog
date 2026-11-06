window start=2026-08-25T17:44:21+00:00 end=2026-08-25T18:04:12+00:00 runs=17

| stage      | model       | runs | turns | fresh in | cache read | cache write | output | list $ |
| ---------- | ----------- | ---- | ----- | -------- | ---------- | ----------- | ------ | ------ |
| blind-spot | gpt-5.6-sol | 4    | 4     | 22,450   | 226,513    | 0           | 1,597  | $0.27  |
| blind-spot | unknown     | 1    | 0     | 0        | 0          | 0           | 0      | —      |
| review     | gpt-5.6-sol | 8    | 8     | 50,323   | 486,892    | 0           | 6,269  | $0.68  |
| validation | gpt-5.6-sol | 4    | 14    | 44,680   | 1,124,093  | 0           | 4,947  | $0.93  |
| **total**  |             | 17   | 26    | 117,453  | 1,837,498  | 0           | 12,813 |        |

| stage      | model       | run      | turns | fresh in | cache read | output | wall s |
| ---------- | ----------- | -------- | ----- | -------- | ---------- | ------ | ------ |
| review     | gpt-5.6-sol | c42e1299 | 1     | 7,230    | 55,199     | 650    | 161    |
| review     | gpt-5.6-sol | 77803ed8 | 1     | 6,060    | 55,317     | 678    | 125    |
| review     | gpt-5.6-sol | ec2c61ce | 1     | 2,584    | 70,606     | 828    | 176    |
| review     | gpt-5.6-sol | ff8ef0b1 | 1     | 2,096    | 67,801     | 910    | 223    |
| review     | gpt-5.6-sol | be0b6c41 | 1     | 9,320    | 56,284     | 1,327  | 187    |
| review     | gpt-5.6-sol | f3773979 | 1     | 5,090    | 64,880     | 840    | 216    |
| review     | gpt-5.6-sol | 73a0b497 | 1     | 7,613    | 58,884     | 664    | 145    |
| review     | gpt-5.6-sol | d9037fa4 | 1     | 10,330   | 57,921     | 372    | 175    |
| blind-spot | gpt-5.6-sol | 2e971d73 | 1     | 9,170    | 43,373     | 552    | 169    |
| blind-spot | gpt-5.6-sol | 4d4159c0 | 1     | 934      | 65,407     | 404    | 164    |
| blind-spot | unknown     | f9c7497b | 0     | 0        | 0          | 0      | 8      |
| blind-spot | gpt-5.6-sol | e020a6c0 | 1     | 2,564    | 63,589     | 351    | 204    |
| blind-spot | gpt-5.6-sol | cd6d2253 | 1     | 9,782    | 54,144     | 290    | 121    |
| validation | gpt-5.6-sol | 448f3b47 | 7     | 21,203   | 737,627    | 2,127  | 323    |
| validation | gpt-5.6-sol | 59122a54 | 3     | 5,810    | 158,247    | 1,462  | 305    |
| validation | gpt-5.6-sol | 16168b67 | 1     | 3,394    | 58,538     | 423    | 186    |
| validation | gpt-5.6-sol | 23536433 | 3     | 14,273   | 169,681    | 935    | 176    |
