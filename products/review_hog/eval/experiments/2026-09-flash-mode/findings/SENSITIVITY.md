# Truth sensitivity of the arm ranking

Truth-sensitivity of the arm ranking. Writes findings/SENSITIVITY.md.  
A fresh = per-finding 3-skeptic majority (as judged)  
B pooled = registry-matched findings take the majority of ALL fresh votes cast on their cluster in this experiment  
C august = clusters with >=2 August verdicts take August's majority (tie -> fresh); others fresh  
D serious = A, counting only must_fix / should_fix as real  
E adjudicated = A with the 14 contested clusters replaced by the 3-adjudicator panel (findings/<S>.truth.adjudicated.json)  
F adjudicated serious = E, counting only must_fix / should_fix as real

## A

| arm                  | real per run | posted real per run | posted noise per run | validator precision | validator recall | $ per real (reviewer side) | $ per posted real |
| -------------------- | -----------: | ------------------: | -------------------: | ------------------- | ---------------- | -------------------------: | ----------------: |
| GLM 5.3 Flash @ high |          8.0 |                 7.5 |                  6.0 | 15/27 (56%)         | 15/16 (94%)      |                      $0.31 |             $0.33 |
| GPT 5.6 Luna @ low   |          3.0 |                 3.0 |                  4.5 | 6/15 (40%)          | 6/6 (100%)       |                      $0.10 |             $0.10 |
| GPT 5.6 Sol @ low    |          6.5 |                 6.5 |                  0.5 | 13/14 (93%)         | 13/13 (100%)     |                      $1.08 |             $1.08 |

## B

| arm                  | real per run | posted real per run | posted noise per run | validator precision | validator recall | $ per real (reviewer side) | $ per posted real |
| -------------------- | -----------: | ------------------: | -------------------: | ------------------- | ---------------- | -------------------------: | ----------------: |
| GLM 5.3 Flash @ high |          8.0 |                 6.5 |                  7.0 | 13/27 (48%)         | 13/16 (81%)      |                      $0.31 |             $0.38 |
| GPT 5.6 Luna @ low   |          3.5 |                 3.0 |                  4.5 | 6/15 (40%)          | 6/7 (86%)        |                      $0.09 |             $0.10 |
| GPT 5.6 Sol @ low    |          4.0 |                 4.0 |                  3.0 | 8/14 (57%)          | 8/8 (100%)       |                      $1.75 |             $1.75 |

## C

| arm                  | real per run | posted real per run | posted noise per run | validator precision | validator recall | $ per real (reviewer side) | $ per posted real |
| -------------------- | -----------: | ------------------: | -------------------: | ------------------- | ---------------- | -------------------------: | ----------------: |
| GLM 5.3 Flash @ high |          7.5 |                 6.5 |                  7.0 | 13/27 (48%)         | 13/15 (87%)      |                      $0.33 |             $0.38 |
| GPT 5.6 Luna @ low   |          2.0 |                 2.0 |                  5.5 | 4/15 (27%)          | 4/4 (100%)       |                      $0.15 |             $0.15 |
| GPT 5.6 Sol @ low    |          2.0 |                 2.0 |                  5.0 | 4/14 (29%)          | 4/4 (100%)       |                      $3.50 |             $3.50 |

## D

| arm                  | real per run | posted real per run | posted noise per run | validator precision | validator recall | $ per real (reviewer side) | $ per posted real |
| -------------------- | -----------: | ------------------: | -------------------: | ------------------- | ---------------- | -------------------------: | ----------------: |
| GLM 5.3 Flash @ high |          2.0 |                 2.0 |                 11.5 | 4/27 (15%)          | 4/4 (100%)       |                      $1.24 |             $1.24 |
| GPT 5.6 Luna @ low   |          2.5 |                 2.5 |                  5.0 | 5/15 (33%)          | 5/5 (100%)       |                      $0.12 |             $0.12 |
| GPT 5.6 Sol @ low    |          4.0 |                 4.0 |                  3.0 | 8/14 (57%)          | 8/8 (100%)       |                      $1.75 |             $1.75 |

## E

| arm                  | real per run | posted real per run | posted noise per run | validator precision | validator recall | $ per real (reviewer side) | $ per posted real |
| -------------------- | -----------: | ------------------: | -------------------: | ------------------- | ---------------- | -------------------------: | ----------------: |
| GLM 5.3 Flash @ high |          9.5 |                 7.0 |                  6.5 | 14/27 (52%)         | 14/19 (74%)      |                      $0.26 |             $0.36 |
| GPT 5.6 Luna @ low   |          3.5 |                 3.0 |                  4.5 | 6/15 (40%)          | 6/7 (86%)        |                      $0.09 |             $0.10 |
| GPT 5.6 Sol @ low    |          5.0 |                 4.5 |                  2.5 | 9/14 (64%)          | 9/10 (90%)       |                      $1.40 |             $1.56 |

## F

| arm                  | real per run | posted real per run | posted noise per run | validator precision | validator recall | $ per real (reviewer side) | $ per posted real |
| -------------------- | -----------: | ------------------: | -------------------: | ------------------- | ---------------- | -------------------------: | ----------------: |
| GLM 5.3 Flash @ high |          3.0 |                 2.5 |                 11.0 | 5/27 (19%)          | 5/6 (83%)        |                      $0.83 |             $0.99 |
| GPT 5.6 Luna @ low   |          3.0 |                 2.5 |                  5.0 | 5/15 (33%)          | 5/6 (83%)        |                      $0.10 |             $0.12 |
| GPT 5.6 Sol @ low    |          4.0 |                 3.5 |                  3.5 | 7/14 (50%)          | 7/8 (88%)        |                      $1.75 |             $2.00 |
