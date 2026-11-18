# Truth sensitivity of the arm ranking

Truth-sensitivity of the arm ranking. Writes findings/SENSITIVITY.md.  
A fresh = per-finding 3-skeptic majority (as judged)  
B pooled = registry-matched findings take the majority of ALL fresh votes cast on their cluster in this experiment  
C august = clusters with >=2 August verdicts take August's majority (tie -> fresh); others fresh  
D serious = A, counting only must_fix / should_fix as real  
E adjudicated = A with the 14 contested clusters replaced by the 3-adjudicator panel (findings/<S>.truth.adjudicated.json)  
F adjudicated serious = E, counting only must_fix / should_fix as real

## A

| arm                   | real per run | posted real per run | posted noise per run | validator precision | validator recall | $ per real (reviewer side) | $ per posted real |
| --------------------- | -----------: | ------------------: | -------------------: | ------------------- | ---------------- | -------------------------: | ----------------: |
| GLM 5.3 Flash @ high  |          8.0 |                 7.5 |                  6.0 | 15/27 (56%)         | 15/16 (94%)      |                      $0.31 |             $0.33 |
| GPT 5.6 Luna @ low    |          3.0 |                 3.0 |                  4.5 | 6/15 (40%)          | 6/6 (100%)       |                      $0.10 |             $0.10 |
| GPT 5.6 Sol @ low     |          6.5 |                 6.5 |                  0.5 | 13/14 (93%)         | 13/13 (100%)     |                      $1.08 |             $1.08 |
| GPT 5.6 Luna @ medium |          5.5 |                 5.5 |                  4.0 | 11/19 (58%)         | 11/11 (100%)     |                      $0.11 |             $0.11 |
| GPT 5.6 Luna @ xhigh  |         15.5 |                15.5 |                  4.0 | 31/39 (79%)         | 31/31 (100%)     |                      $0.21 |             $0.21 |

## B

| arm                   | real per run | posted real per run | posted noise per run | validator precision | validator recall | $ per real (reviewer side) | $ per posted real |
| --------------------- | -----------: | ------------------: | -------------------: | ------------------- | ---------------- | -------------------------: | ----------------: |
| GLM 5.3 Flash @ high  |         10.0 |                 7.5 |                  6.0 | 15/27 (56%)         | 15/20 (75%)      |                      $0.25 |             $0.33 |
| GPT 5.6 Luna @ low    |          5.0 |                 4.5 |                  3.0 | 9/15 (60%)          | 9/10 (90%)       |                      $0.06 |             $0.07 |
| GPT 5.6 Sol @ low     |          6.5 |                 6.5 |                  0.5 | 13/14 (93%)         | 13/13 (100%)     |                      $1.08 |             $1.08 |
| GPT 5.6 Luna @ medium |          5.5 |                 5.5 |                  4.0 | 11/19 (58%)         | 11/11 (100%)     |                      $0.11 |             $0.11 |
| GPT 5.6 Luna @ xhigh  |         15.0 |                15.0 |                  4.5 | 30/39 (77%)         | 30/30 (100%)     |                      $0.22 |             $0.22 |

## C

| arm                   | real per run | posted real per run | posted noise per run | validator precision | validator recall | $ per real (reviewer side) | $ per posted real |
| --------------------- | -----------: | ------------------: | -------------------: | ------------------- | ---------------- | -------------------------: | ----------------: |
| GLM 5.3 Flash @ high  |          7.5 |                 6.5 |                  7.0 | 13/27 (48%)         | 13/15 (87%)      |                      $0.33 |             $0.38 |
| GPT 5.6 Luna @ low    |          2.0 |                 2.0 |                  5.5 | 4/15 (27%)          | 4/4 (100%)       |                      $0.15 |             $0.15 |
| GPT 5.6 Sol @ low     |          2.0 |                 2.0 |                  5.0 | 4/14 (29%)          | 4/4 (100%)       |                      $3.50 |             $3.50 |
| GPT 5.6 Luna @ medium |          2.0 |                 2.0 |                  7.5 | 4/19 (21%)          | 4/4 (100%)       |                      $0.30 |             $0.30 |
| GPT 5.6 Luna @ xhigh  |          9.5 |                 9.5 |                 10.0 | 19/39 (49%)         | 19/19 (100%)     |                      $0.35 |             $0.35 |

## D

| arm                   | real per run | posted real per run | posted noise per run | validator precision | validator recall | $ per real (reviewer side) | $ per posted real |
| --------------------- | -----------: | ------------------: | -------------------: | ------------------- | ---------------- | -------------------------: | ----------------: |
| GLM 5.3 Flash @ high  |          2.0 |                 2.0 |                 11.5 | 4/27 (15%)          | 4/4 (100%)       |                      $1.24 |             $1.24 |
| GPT 5.6 Luna @ low    |          2.5 |                 2.5 |                  5.0 | 5/15 (33%)          | 5/5 (100%)       |                      $0.12 |             $0.12 |
| GPT 5.6 Sol @ low     |          4.0 |                 4.0 |                  3.0 | 8/14 (57%)          | 8/8 (100%)       |                      $1.75 |             $1.75 |
| GPT 5.6 Luna @ medium |          5.5 |                 5.5 |                  4.0 | 11/19 (58%)         | 11/11 (100%)     |                      $0.11 |             $0.11 |
| GPT 5.6 Luna @ xhigh  |         14.0 |                14.0 |                  5.5 | 28/39 (72%)         | 28/28 (100%)     |                      $0.24 |             $0.24 |

## E

| arm                   | real per run | posted real per run | posted noise per run | validator precision | validator recall | $ per real (reviewer side) | $ per posted real |
| --------------------- | -----------: | ------------------: | -------------------: | ------------------- | ---------------- | -------------------------: | ----------------: |
| GLM 5.3 Flash @ high  |          9.5 |                 7.0 |                  6.5 | 14/27 (52%)         | 14/19 (74%)      |                      $0.26 |             $0.36 |
| GPT 5.6 Luna @ low    |          3.5 |                 3.0 |                  4.5 | 6/15 (40%)          | 6/7 (86%)        |                      $0.09 |             $0.10 |
| GPT 5.6 Sol @ low     |          5.0 |                 4.5 |                  2.5 | 9/14 (64%)          | 9/10 (90%)       |                      $1.40 |             $1.56 |
| GPT 5.6 Luna @ medium |          4.5 |                 4.5 |                  5.0 | 9/19 (47%)          | 9/9 (100%)       |                      $0.13 |             $0.13 |
| GPT 5.6 Luna @ xhigh  |         13.5 |                13.0 |                  6.5 | 26/39 (67%)         | 26/27 (96%)      |                      $0.25 |             $0.26 |

## F

| arm                   | real per run | posted real per run | posted noise per run | validator precision | validator recall | $ per real (reviewer side) | $ per posted real |
| --------------------- | -----------: | ------------------: | -------------------: | ------------------- | ---------------- | -------------------------: | ----------------: |
| GLM 5.3 Flash @ high  |          3.0 |                 2.5 |                 11.0 | 5/27 (19%)          | 5/6 (83%)        |                      $0.83 |             $0.99 |
| GPT 5.6 Luna @ low    |          3.0 |                 2.5 |                  5.0 | 5/15 (33%)          | 5/6 (83%)        |                      $0.10 |             $0.12 |
| GPT 5.6 Sol @ low     |          4.0 |                 3.5 |                  3.5 | 7/14 (50%)          | 7/8 (88%)        |                      $1.75 |             $2.00 |
| GPT 5.6 Luna @ medium |          4.0 |                 4.0 |                  5.5 | 8/19 (42%)          | 8/8 (100%)       |                      $0.15 |             $0.15 |
| GPT 5.6 Luna @ xhigh  |         11.5 |                11.0 |                  8.5 | 22/39 (56%)         | 22/23 (96%)      |                      $0.29 |             $0.30 |
