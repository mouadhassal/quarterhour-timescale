# A support case, worked end to end: 15-minute electricity prices in TimescaleDB

A small, reproducible exercise written the way I'd answer a customer ticket. The data is real: one year of 15-minute Nordic-Baltic day-ahead prices (EE, FI, LV, LT; Elering open data), 140,160 rows. Every query, plan and number below comes from `run_case.py` against `timescale/timescaledb:latest-pg16` (TimescaleDB 2.30.2) and is saved in [CASE_OUTPUT.md](CASE_OUTPUT.md).

```
docker run -d --name tsdb -e POSTGRES_PASSWORD=demo -p 5433:5432 timescale/timescaledb:latest-pg16
python data/fetch.py && python run_case.py
```

## The ticket

> "We store 15-minute prices for four zones. Our dashboard shows hourly averages per zone for the last quarter. We converted the table to a hypertable as the docs suggest, and the database got **twice as big**. Did we do something wrong, and how do we make the dashboard fast?"

## What I found

| Setup | Chunks | Size | Dashboard query |
|---|---|---|---|
| Plain table, no index | n/a | 7.6 MB | 15.1 ms (sequential scan) |
| Plain table + `(zone, ts)` index | n/a | 12 MB | 5.6 ms (index scan) |
| Hypertable, **7-day chunks**, default `ts` index + `(zone, ts)` | **53** | **23 MB** | 5.6 ms (ChunkAppend, 14 of 53 chunks scanned) |
| Hypertable, **90-day chunks**, `(zone, ts)` only | 5 | 13 MB | 5.2 ms |
| 7-day chunks, **compressed** (segment by zone) | 53 | 5.1 MB (4.4×) | 8.9 ms (ColumnarScan) |
| **Continuous aggregate** (hourly) | n/a | n/a | **2.2 ms** |

*Timings are single runs on a laptop and are in milliseconds because the data set is small. The plan shapes and size ratios are the point, not the absolute times.*

**1. The size doubled because of chunk size and a duplicate index, not because hypertables are big.**
- Each 7-day chunk holds only about 2,600 rows, and each carries **2 indexes**: TimescaleDB's default index on `ts`, plus the customer's `(zone, ts)` index, which already covers time-range queries on one zone.
- 53 small chunks × 2 indexes is where the 23 MB comes from.
- With 90-day chunks and `create_default_indexes => false`, the same data takes 13 MB, about the same as the plain table with its index.

**2. For this dashboard, the right tool is a continuous aggregate.**
- An hourly `time_bucket` aggregate, refreshed every 15 minutes by a policy, answers the query from 2,208 pre-computed hourly rows instead of 8,832 raw ones.
- A sanity check confirms every hour has exactly 4 quarter-hours.

**3. Compress old chunks for storage, not for this query.**
- Segmenting by `zone` compressed the raw data 4.4×.
- The raw hourly query on compressed chunks was slightly *slower* (8.9 vs 5.6 ms), because it decompresses columns. The continuous aggregate makes that irrelevant for the dashboard.

## The reply I'd send

> You didn't do anything wrong, but two defaults don't fit your volume.
>
> 1. **Chunk interval.** At about 400 rows a day, 7-day chunks are tiny. Use 90 days or more (`set_chunk_time_interval`). New chunks pick it up; existing ones can be left as they are or migrated.
> 2. **Duplicate index.** Your `(zone, ts DESC)` index already serves time-range queries per zone. If you never filter by time alone across all zones, create hypertables with `create_default_indexes => false` or drop the default `ts` index; if you do, keep it and accept the size.
> 3. **Dashboard.** Build an hourly continuous aggregate with a refresh policy and point the dashboard at it. That cuts the work per request from 8,832 rows to 2,208.
> 4. **Storage.** Add a compression policy segmented by `zone` for chunks older than a month: about 4× smaller here.
>
> Here are the exact statements and before/after plans for each step: CASE_OUTPUT.md.

---

Mouadh Abderrahmane Assal · More in my [portfolio](https://mouadh.vercel.app/) · [github.com/mouadhassal](https://github.com/mouadhassal)
