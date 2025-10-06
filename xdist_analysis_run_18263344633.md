# pytest-xdist Analysis: Run 18263344633

## Configuration

- Runner: 4-core
- xdist workers: `-n 2` (fixed 2 workers per shard)
- Status: Cancelled (after 28/60 jobs completed successfully)

## Summary Statistics

| Run             | Config           | Jobs   | Avg Time    | Median      | Min       | Max         | Stdev      |
| --------------- | ---------------- | ------ | ----------- | ----------- | --------- | ----------- | ---------- |
| 18249440656     | 2-core, no xdist | -      | 256.47s     | -           | -         | -           | -          |
| 18259344382     | 4-core, -n auto  | -      | 211.94s     | -           | -         | -           | -          |
| **18263344633** | **4-core, -n 2** | **28** | **199.49s** | **205.91s** | **8.25s** | **343.95s** | **84.86s** |

## Performance Improvements

- **vs 2-core no xdist**: 22.2% faster (56.98s saved per job)
- **vs 4-core -n auto**: 5.9% faster (12.45s saved per job)

## Breakdown by Test Suite

| Suite        | Jobs | Avg Time | Median  | Range             |
| ------------ | ---- | -------- | ------- | ----------------- |
| Core POE-off | 16   | 208.53s  | 220.68s | 32.65s - 321.09s  |
| Core POE-on  | 5    | 160.38s  | 149.48s | 122.92s - 226.71s |
| Temporal     | 7    | 206.76s  | 254.65s | 8.25s - 343.95s   |

## Individual Job Times (sorted by duration)

| Job                  | Tests | Time (s) |
| -------------------- | ----- | -------- |
| Temporal (5/10)      | 56    | 343.95   |
| Core POE-off (17/40) | 110   | 321.09   |
| Core POE-off (29/40) | 646   | 300.13   |
| Temporal (7/10)      | 63    | 299.50   |
| Core POE-off (26/40) | 420   | 277.99   |
| Temporal (4/10)      | 190   | 275.48   |
| Core POE-off (22/40) | 569   | 258.66   |
| Temporal (6/10)      | 132   | 254.65   |
| Core POE-off (18/40) | 194   | 247.61   |
| Core POE-off (7/40)  | 605   | 243.99   |
| Core POE-off (21/40) | 357   | 239.96   |
| Core POE-off (25/40) | 259   | 228.20   |
| Core POE-on (3/10)   | 222   | 226.71   |
| Core POE-off (4/40)  | 760   | 213.15   |
| Core POE-off (2/40)  | 49    | 198.67   |
| Core POE-off (3/40)  | 202   | 194.08   |
| Core POE-off (30/40) | 374   | 191.11   |
| Core POE-off (31/40) | 434   | 184.81   |
| Core POE-on (6/10)   | 249   | 163.80   |
| Core POE-off (34/40) | 436   | 156.52   |
| Temporal (1/10)      | 97    | 151.19   |
| Core POE-on (8/10)   | 200   | 149.48   |
| Core POE-on (4/10)   | 106   | 139.00   |
| Core POE-on (10/10)  | 257   | 122.92   |
| Temporal (3/10)      | 15    | 114.27   |
| Core POE-off (39/40) | 208   | 47.78    |
| Core POE-off (1/40)  | 10    | 32.65    |
| Temporal (9/10)      | 165   | 8.25     |

## Failed/Cancelled Jobs

- **Cancelled**: Core POE-off (6/40) - run was cancelled before completion
- **Failed**: Core POE-off (37/40) - `test_alter_mutation_single_command` failed (179 passed, 1 failed in 366.41s)

## Analysis

### Key Findings

1. **Fixed -n 2 shows consistent improvement**: Using `-n 2` (2 xdist workers) on 4-core runners provides a 5.9% improvement over `-n auto`, suggesting that limiting parallelism may reduce overhead or resource contention.

2. **Wide variance in execution times**: Standard deviation of 84.86s indicates significant variation across shards. Some shards complete in under 10s while others take over 340s, suggesting uneven test distribution.

3. **Temporal tests show highest variance**: Temporal suite has the widest range (8.25s - 343.95s), indicating potential issues with test balancing or some extremely slow tests.

4. **Core POE-on tests are fastest**: Average 160.38s vs 208.53s for POE-off, likely due to fewer tests per shard.

### Recommendations

1. **Continue with -n 2**: The fixed worker count provides better performance than auto-detection on 4-core runners.

2. **Investigate slow shards**: Jobs like Temporal (5/10) at 343.95s and Core POE-off (17/40) at 321.09s need investigation for test balancing.

3. **Test distribution**: Consider re-balancing shards to reduce variance and improve overall pipeline time (wall clock time is limited by the slowest shard).
