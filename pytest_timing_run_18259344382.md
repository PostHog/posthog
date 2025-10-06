# Pytest Execution Time Analysis - Run 18259344382

## Configuration

- Runner: 4-core
- Pytest xdist: `-n auto` (4 workers)
- Total jobs: 50 Django test jobs

## Summary Statistics

### Persons-on-Events OFF (40 jobs)

- Active jobs with tests: 37/40
- Min execution time: 160.91s (~2.7 min)
- Max execution time: 350.45s (~5.8 min)
- Mean: 233.63s (~3.9 min)
- Median: 229.29s (~3.8 min)
- Total pytest time: 146.58 minutes

### Persons-on-Events ON (10 jobs)

- Jobs: 10
- Min execution time: 139.67s (~2.3 min)
- Max execution time: 281.30s (~4.7 min)
- Mean: 180.22s (~3.0 min)
- Median: 174.42s (~2.9 min)
- Total pytest time: 30.04 minutes

### Overall

- Total jobs: 50
- Total pytest execution time: 176.62 minutes (~2.9 hours)
- Average per job: 211.94s (~3.5 min)

## Top 10 Slowest Jobs

1. Job 6/40 (POE off): 350.45s (~5.8 min)
2. Job 17/40 (POE off): 306.52s (~5.1 min)
3. Job 37/40 (POE off): 305.14s (~5.1 min)
4. Job 5/40 (POE off): 300.16s (~5.0 min)
5. Job 14/40 (POE off): 299.11s (~5.0 min)
6. Job 5/10 (POE on): 281.30s (~4.7 min)
7. Job 11/40 (POE off): 281.23s (~4.7 min)
8. Job 29/40 (POE off): 265.22s (~4.4 min)
9. Job 13/40 (POE off): 262.57s (~4.4 min)
10. Job 10/40 (POE off): 254.05s (~4.2 min)

## Jobs with No/Skipped Tests Only

- Job 36/40: 50.40s (skipped tests only)
- Job 39/40: 51.05s
- Job 40/40: 49.06s (no tests ran)

## Full Results

### Persons-on-Events OFF (1-40)

| Job   | Time              |
| ----- | ----------------- |
| 1/40  | 181.54s           |
| 2/40  | 199.48s           |
| 3/40  | 192.37s           |
| 4/40  | 196.45s           |
| 5/40  | 300.16s           |
| 6/40  | 350.45s           |
| 7/40  | 220.80s           |
| 8/40  | 237.99s           |
| 9/40  | 207.28s           |
| 10/40 | 254.05s           |
| 11/40 | 281.23s           |
| 12/40 | 225.61s           |
| 13/40 | 262.57s           |
| 14/40 | 299.11s           |
| 15/40 | 246.43s           |
| 16/40 | 229.29s           |
| 17/40 | 306.52s           |
| 18/40 | 208.34s           |
| 19/40 | 246.07s           |
| 20/40 | 248.09s           |
| 21/40 | 223.93s           |
| 22/40 | 228.94s           |
| 23/40 | 229.39s           |
| 24/40 | 239.84s           |
| 25/40 | 205.72s           |
| 26/40 | 244.18s           |
| 27/40 | 232.36s           |
| 28/40 | 229.09s           |
| 29/40 | 265.22s           |
| 30/40 | 179.97s           |
| 31/40 | 191.13s           |
| 32/40 | 239.33s           |
| 33/40 | 188.69s           |
| 34/40 | 160.91s           |
| 35/40 | 198.81s           |
| 36/40 | 50.40s (skipped)  |
| 37/40 | 305.14s           |
| 38/40 | 187.82s           |
| 39/40 | 51.05s            |
| 40/40 | 49.06s (no tests) |

### Persons-on-Events ON (1-10)

| Job   | Time    |
| ----- | ------- |
| 1/10  | 191.94s |
| 2/10  | 186.73s |
| 3/10  | 187.42s |
| 4/10  | 151.38s |
| 5/10  | 281.30s |
| 6/10  | 166.12s |
| 7/10  | 174.42s |
| 8/10  | 154.57s |
| 9/10  | 168.67s |
| 10/10 | 139.67s |

## Key Observations

1. **Wide variance in execution times**: Jobs range from ~2.3 minutes to ~5.8 minutes
2. **POE OFF jobs are slower on average**: Mean of 233.63s vs 180.22s for POE ON
3. **Most jobs fall in 3-4 minute range**: Median times are 229.29s (POE off) and 174.42s (POE on)
4. **Total cumulative pytest time**: Nearly 3 hours across all 50 jobs
5. **Test distribution imbalance**: Some jobs have no tests (36/40, 39/40, 40/40), while others run for 5+ minutes
