window start=2026-08-25T20:44:08+00:00 end=2026-08-25T21:35:43+00:00 runs=20

| stage      | model       | runs | turns | fresh in | cache read | cache write | output | list $ |
| ---------- | ----------- | ---- | ----- | -------- | ---------- | ----------- | ------ | ------ |
| blind-spot | gpt-5.6-sol | 4    | 4     | 15,853   | 244,882    | 0           | 1,545  | $0.25  |
| review     | gpt-5.6-sol | 13   | 9     | 53,185   | 556,282    | 0           | 5,780  | $0.72  |
| validation | gpt-5.6-sol | 3    | 7     | 25,645   | 344,639    | 0           | 2,832  | $0.39  |
| **total**  |             | 20   | 20    | 94,683   | 1,145,803  | 0           | 10,157 |        |

| stage      | model       | run      | turns | fresh in | cache read | output | wall s |
| ---------- | ----------- | -------- | ----- | -------- | ---------- | ------ | ------ |
| review     | gpt-5.6-sol | cb31dfd3 | 1     | 2,603    | 61,583     | 140    | 114    |
| review     | gpt-5.6-sol | 272aef28 | 0     | 0        | 0          | 0      | 1843   |
| review     | gpt-5.6-sol | 6f708675 | 0     | 0        | 0          | 0      | 1842   |
| review     | gpt-5.6-sol | c241a10a | 1     | 4,685    | 69,228     | 1,221  | 241    |
| review     | gpt-5.6-sol | f8be273d | 1     | 9,317    | 68,376     | 468    | 228    |
| review     | gpt-5.6-sol | 1f1c3838 | 0     | 0        | 0          | 0      | 1835   |
| review     | gpt-5.6-sol | 5e27ae73 | 0     | 0        | 0          | 0      | 1834   |
| review     | gpt-5.6-sol | 465fd5f2 | 1     | 6,566    | 54,882     | 828    | 112    |
| review     | gpt-5.6-sol | 97bd6c4e | 1     | 6,049    | 52,993     | 904    | 111    |
| review     | gpt-5.6-sol | ea52480f | 1     | 9,317    | 52,749     | 469    | 138    |
| review     | gpt-5.6-sol | 2df32828 | 1     | 8,160    | 64,115     | 829    | 215    |
| review     | gpt-5.6-sol | 9422ed15 | 1     | 4,435    | 76,294     | 463    | 166    |
| review     | gpt-5.6-sol | 8104e9db | 1     | 2,053    | 56,062     | 458    | 192    |
| blind-spot | gpt-5.6-sol | ed7bc0b7 | 1     | 2,954    | 68,747     | 375    | 149    |
| blind-spot | gpt-5.6-sol | 60503378 | 1     | 3,277    | 58,150     | 555    | 174    |
| blind-spot | gpt-5.6-sol | 15455db2 | 1     | 4,360    | 49,210     | 230    | 125    |
| blind-spot | gpt-5.6-sol | 8a5f0f57 | 1     | 5,262    | 68,775     | 385    | 143    |
| validation | gpt-5.6-sol | 11f32c23 | 3     | 7,381    | 159,189    | 1,109  | 200    |
| validation | gpt-5.6-sol | e35b3eb3 | 2     | 7,290    | 82,996     | 885    | 155    |
| validation | gpt-5.6-sol | 1ca43be0 | 2     | 10,974   | 102,454    | 838    | 849    |
