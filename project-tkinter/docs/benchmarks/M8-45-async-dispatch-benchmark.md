# M8#45 Async Dispatch Benchmark

## Setup
- python: `3.11.9`
- batches: `60`
- segments_per_batch: `3`
- synthetic_translate_delay_s: `0.0900`
- dispatch_interval_s: `0.0000`

## Results

| io_concurrency | mean_s | min_s | max_s | speedup_vs_1x |
|---:|---:|---:|---:|---:|
| 1 | 5.4342 | 5.4330 | 5.4356 | 1.0000x |
| 2 | 2.7183 | 2.7180 | 2.7186 | 1.9991x |
| 4 | 1.3601 | 1.3596 | 1.3610 | 3.9954x |

## Raw Runs

| io_concurrency | repeat | elapsed_s | batches | segments |
|---:|---:|---:|---:|---:|
| 1 | 1 | 5.4356 | 60 | 180 |
| 1 | 2 | 5.4340 | 60 | 180 |
| 1 | 3 | 5.4330 | 60 | 180 |
| 2 | 1 | 2.7186 | 60 | 180 |
| 2 | 2 | 2.7182 | 60 | 180 |
| 2 | 3 | 2.7180 | 60 | 180 |
| 4 | 1 | 1.3596 | 60 | 180 |
| 4 | 2 | 1.3610 | 60 | 180 |
| 4 | 3 | 1.3597 | 60 | 180 |
