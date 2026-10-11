# Case output

Loaded 140,160 rows (4 zones x 35,040 quarter-hours).

### 1. Plain table: size

```sql
ANALYZE prices; SELECT pg_size_pretty(pg_total_relation_size('prices')) AS plain_table_size;
```

```
plain_table_size 
------------------
 7584 kB
(1 row)
```

### 2. Plain table: the dashboard query (one zone, hourly, last quarter)

```sql
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON, SUMMARY ON)
SELECT zone, date_trunc('hour', ts) AS hour, avg(eur_mwh) AS avg_price, max(eur_mwh) AS peak
FROM prices
WHERE ts >= '2026-07-01' AND ts < '2026-10-01' AND zone = 'ee'
GROUP BY 1, 2 ORDER BY 2;
```

```
QUERY PLAN                                                                                
--------------------------------------------------------------------------------------------------------------------------------------------------------------------------
 Sort (actual time=14.622..14.704 rows=2208 loops=1)
   Sort Key: (date_trunc('hour'::text, ts))
   Sort Method: quicksort  Memory: 217kB
   Buffers: shared hit=947
   ->  HashAggregate (actual time=13.734..14.094 rows=2208 loops=1)
         Group Key: date_trunc('hour'::text, ts)
         Batches: 1  Memory Usage: 913kB
         Buffers: shared hit=944
         ->  Seq Scan on prices (actual time=5.587..11.318 rows=8832 loops=1)
               Filter: ((ts >= '2026-07-01 00:00:00+00'::timestamp with time zone) AND (ts < '2026-10-01 00:00:00+00'::timestamp with time zone) AND (zone = 'ee'::text))
               Rows Removed by Filter: 131328
               Buffers: shared hit=944
 Planning:
   Buffers: shared hit=554
 Planning Time: 3.512 ms
 Execution Time: 15.098 ms
(16 rows)
```

### 3. Plain table + (zone, ts) index

```sql
CREATE INDEX ON prices (zone, ts DESC); ANALYZE prices;EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, SUMMARY ON)
SELECT zone, date_trunc('hour', ts) AS hour, avg(eur_mwh) AS avg_price, max(eur_mwh) AS peak
FROM prices
WHERE ts >= '2026-07-01' AND ts < '2026-10-01' AND zone = 'ee'
GROUP BY 1, 2 ORDER BY 2;;
SELECT pg_size_pretty(pg_total_relation_size('prices')) AS plain_table_with_index;
```

```
QUERY PLAN                                                                                  
------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
 Sort (actual time=5.177..5.253 rows=2208 loops=1)
   Sort Key: (date_trunc('hour'::text, ts))
   Sort Method: quicksort  Memory: 217kB
   Buffers: shared hit=226 read=36
   ->  HashAggregate (actual time=4.425..4.715 rows=2208 loops=1)
         Group Key: date_trunc('hour'::text, ts)
         Batches: 1  Memory Usage: 913kB
         Buffers: shared hit=226 read=36
         ->  Index Scan using prices_zone_ts_idx on prices (actual time=0.037..2.920 rows=8832 loops=1)
               Index Cond: ((zone = 'ee'::text) AND (ts >= '2026-07-01 00:00:00+00'::timestamp with time zone) AND (ts < '2026-10-01 00:00:00+00'::timestamp with time zone))
               Buffers: shared hit=226 read=36
 Planning:
   Buffers: shared hit=177 read=1
 Planning Time: 1.191 ms
 Execution Time: 5.597 ms
(15 rows)

 plain_table_with_index 
------------------------
 12 MB
(1 row)
```

### 4. Hypertable with 7-day chunks

```sql
SELECT create_hypertable('prices', by_range('ts', INTERVAL '7 days'), migrate_data => true);ANALYZE prices;SELECT count(*) AS chunks, pg_size_pretty(hypertable_size('prices')) AS size FROM show_chunks('prices');SELECT count(*) AS indexes_per_chunk FROM pg_indexes WHERE schemaname || '.' || tablename = (SELECT show_chunks('prices') LIMIT 1)::text;
```

```
create_hypertable 
-------------------
 (8,t)
(1 row)

 chunks | size  
--------+-------
     53 | 23 MB
(1 row)

 indexes_per_chunk 
-------------------
                 2
(1 row)
```

### 5. Hypertable: chunk exclusion on the same query

```sql
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, SUMMARY ON)
SELECT zone, time_bucket('1 hour', ts) AS hour, avg(eur_mwh) AS avg_price, max(eur_mwh) AS peak
FROM prices
WHERE ts >= '2026-07-01' AND ts < '2026-10-01' AND zone = 'ee'
GROUP BY 1, 2 ORDER BY 2;
```

```
QUERY PLAN                                                                         
------------------------------------------------------------------------------------------------------------------------------------------------------------
 Finalize GroupAggregate (actual time=0.032..5.162 rows=2208 loops=1)
   Group Key: (time_bucket('01:00:00'::interval, prices.ts))
   Buffers: shared hit=360
   ->  Custom Scan (ChunkAppend) on prices (actual time=0.027..4.145 rows=2208 loops=1)
         Order: time_bucket('01:00:00'::interval, prices.ts)
         Buffers: shared hit=360
         ->  Partial GroupAggregate (actual time=0.026..0.078 rows=24 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_225_chunk.ts)
               Buffers: shared hit=9
               ->  Index Scan Backward using _hyper_8_225_chunk_prices_ts_idx on _hyper_8_225_chunk (actual time=0.015..0.061 rows=96 loops=1)
                     Index Cond: ((ts >= '2026-07-01 00:00:00+00'::timestamp with time zone) AND (ts < '2026-10-01 00:00:00+00'::timestamp with time zone))
                     Filter: (zone = 'ee'::text)
                     Rows Removed by Filter: 288
                     Buffers: shared hit=9
         ->  Partial GroupAggregate (actual time=0.018..0.294 rows=168 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_226_chunk.ts)
               Buffers: shared hit=27
               ->  Index Scan Backward using _hyper_8_226_chunk_prices_zone_ts_idx on _hyper_8_226_chunk (actual time=0.016..0.201 rows=672 loops=1)
                     Index Cond: (zone = 'ee'::text)
                     Buffers: shared hit=27
         ->  Partial GroupAggregate (actual time=0.040..0.488 rows=168 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_227_chunk.ts)
               Buffers: shared hit=27
               ->  Index Scan Backward using _hyper_8_227_chunk_prices_zone_ts_idx on _hyper_8_227_chunk (actual time=0.023..0.373 rows=672 loops=1)
                     Index Cond: (zone = 'ee'::text)
                     Buffers: shared hit=27
         ->  Partial GroupAggregate (actual time=0.078..0.376 rows=168 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_228_chunk.ts)
               Buffers: shared hit=27
               ->  Index Scan Backward using _hyper_8_228_chunk_prices_zone_ts_idx on _hyper_8_228_chunk (actual time=0.074..0.262 rows=672 loops=1)
                     Index Cond: (zone = 'ee'::text)
                     Buffers: shared hit=27
         ->  Partial GroupAggregate (actual time=0.024..0.230 rows=168 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_229_chunk.ts)
               Buffers: shared hit=27
               ->  Index Scan Backward using _hyper_8_229_chunk_prices_zone_ts_idx on _hyper_8_229_chunk (actual time=0.021..0.146 rows=672 loops=1)
                     Index Cond: (zone = 'ee'::text)
                     Buffers: shared hit=27
         ->  Partial GroupAggregate (actual time=0.020..0.225 rows=168 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_230_chunk.ts)
               Buffers: shared hit=27
               ->  Index Scan Backward using _hyper_8_230_chunk_prices_zone_ts_idx on _hyper_8_230_chunk (actual time=0.018..0.147 rows=672 loops=1)
                     Index Cond: (zone = 'ee'::text)
                     Buffers: shared hit=27
         ->  Partial GroupAggregate (actual time=0.017..0.283 rows=168 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_231_chunk.ts)
               Buffers: shared hit=27
               ->  Index Scan Backward using _hyper_8_231_chunk_prices_zone_ts_idx on _hyper_8_231_chunk (actual time=0.015..0.196 rows=672 loops=1)
                     Index Cond: (zone = 'ee'::text)
                     Buffers: shared hit=27
         ->  Partial GroupAggregate (actual time=0.058..0.270 rows=168 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_232_chunk.ts)
               Buffers: shared hit=27
               ->  Index Scan Backward using _hyper_8_232_chunk_prices_zone_ts_idx on _hyper_8_232_chunk (actual time=0.056..0.192 rows=672 loops=1)
                     Index Cond: (zone = 'ee'::text)
                     Buffers: shared hit=27
         ->  Partial GroupAggregate (actual time=0.024..0.233 rows=168 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_233_chunk.ts)
               Buffers: shared hit=27
               ->  Index Scan Backward using _hyper_8_233_chunk_prices_zone_ts_idx on _hyper_8_233_chunk (actual time=0.021..0.151 rows=672 loops=1)
                     Index Cond: (zone = 'ee'::text)
                     Buffers: shared hit=27
         ->  Partial GroupAggregate (actual time=0.026..0.301 rows=168 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_234_chunk.ts)
               Buffers: shared hit=27
               ->  Index Scan Backward using _hyper_8_234_chunk_prices_zone_ts_idx on _hyper_8_234_chunk (actual time=0.023..0.200 rows=672 loops=1)
                     Index Cond: (zone = 'ee'::text)
                     Buffers: shared hit=27
         ->  Partial GroupAggregate (actual time=0.023..0.228 rows=168 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_235_chunk.ts)
               Buffers: shared hit=27
               ->  Index Scan Backward using _hyper_8_235_chunk_prices_zone_ts_idx on _hyper_8_235_chunk (actual time=0.020..0.146 rows=672 loops=1)
                     Index Cond: (zone = 'ee'::text)
                     Buffers: shared hit=27
         ->  Partial GroupAggregate (actual time=0.023..0.398 rows=168 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_236_chunk.ts)
               Buffers: shared hit=27
               ->  Index Scan Backward using _hyper_8_236_chunk_prices_zone_ts_idx on _hyper_8_236_chunk (actual time=0.021..0.285 rows=672 loops=1)
                     Index Cond: (zone = 'ee'::text)
                     Buffers: shared hit=27
         ->  Partial GroupAggregate (actual time=0.075..0.321 rows=168 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_237_chunk.ts)
               Buffers: shared hit=27
               ->  Index Scan Backward using _hyper_8_237_chunk_prices_zone_ts_idx on _hyper_8_237_chunk (actual time=0.045..0.179 rows=672 loops=1)
                     Index Cond: (zone = 'ee'::text)
                     Buffers: shared hit=27
         ->  Partial GroupAggregate (actual time=0.023..0.299 rows=168 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_238_chunk.ts)
               Buffers: shared hit=27
               ->  Index Scan Backward using _hyper_8_238_chunk_prices_zone_ts_idx on _hyper_8_238_chunk (actual time=0.021..0.185 rows=672 loops=1)
                     Index Cond: (zone = 'ee'::text)
                     Buffers: shared hit=27
 Planning:
   Buffers: shared hit=1559 read=1
 Planning Time: 11.126 ms
 Execution Time: 5.629 ms
(96 rows)
```

### 6. Continuous aggregate for hourly roll-ups, refreshed every 15 minutes

```sql
CREATE MATERIALIZED VIEW prices_hourly WITH (timescaledb.continuous) AS
SELECT zone, time_bucket('1 hour', ts) AS hour, avg(eur_mwh) AS avg_price, max(eur_mwh) AS peak, count(*) AS n
FROM prices GROUP BY 1, 2 WITH DATA;
SELECT add_continuous_aggregate_policy('prices_hourly', start_offset => INTERVAL '3 days',
       end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '15 minutes');
```

```
add_continuous_aggregate_policy 
---------------------------------
                            1003
(1 row)
```

### 7. The dashboard query on the continuous aggregate

```sql
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, SUMMARY ON)
SELECT zone, hour, avg_price, peak FROM prices_hourly
WHERE hour >= '2026-07-01' AND hour < '2026-10-01' AND zone = 'ee' ORDER BY hour;
```

```
QUERY PLAN                                                                                    
----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
 Sort (actual time=1.929..2.016 rows=2208 loops=1)
   Sort Key: _materialized_hypertable_9.hour
   Sort Method: quicksort  Memory: 217kB
   Buffers: shared hit=574
   ->  Append (actual time=0.035..1.349 rows=2208 loops=1)
         Buffers: shared hit=571
         ->  Index Scan Backward using _hyper_9_241_chunk__materialized_hypertable_9_zone_hour_idx on _hyper_9_241_chunk (actual time=0.034..0.451 rows=360 loops=1)
               Index Cond: ((zone = 'ee'::text) AND (hour >= '2026-07-01 00:00:00+00'::timestamp with time zone) AND (hour < '2026-10-01 00:00:00+00'::timestamp with time zone))
               Buffers: shared hit=361
         ->  Bitmap Heap Scan on _hyper_9_242_chunk (actual time=0.101..0.497 rows=1680 loops=1)
               Recheck Cond: (zone = 'ee'::text)
               Heap Blocks: exact=56
               Buffers: shared hit=65
               ->  Bitmap Index Scan on _hyper_9_242_chunk__materialized_hypertable_9_zone_hour_idx (actual time=0.089..0.090 rows=1680 loops=1)
                     Index Cond: (zone = 'ee'::text)
                     Buffers: shared hit=9
         ->  Index Scan Backward using _hyper_9_245_chunk__materialized_hypertable_9_zone_hour_idx on _hyper_9_245_chunk (actual time=0.182..0.284 rows=168 loops=1)
               Index Cond: ((zone = 'ee'::text) AND (hour >= '2026-07-01 00:00:00+00'::timestamp with time zone) AND (hour < '2026-10-01 00:00:00+00'::timestamp with time zone))
               Buffers: shared hit=145
 Planning:
   Buffers: shared hit=823
 Planning Time: 5.605 ms
 Execution Time: 2.183 ms
(23 rows)
```

### 8. Sanity check: every hour has exactly 4 quarter-hours

```sql
SELECT count(*) AS hours_where_quarter_hours_disagree
FROM prices_hourly WHERE n <> 4;
```

```
hours_where_quarter_hours_disagree 
------------------------------------
                                  0
(1 row)
```

### 9. Compression, segmented by zone

```sql
SELECT pg_size_pretty(hypertable_size('prices')) AS before_compression;
ALTER TABLE prices SET (timescaledb.compress, timescaledb.compress_segmentby = 'zone',
                        timescaledb.compress_orderby = 'ts DESC');
SELECT count(compress_chunk(c)) AS chunks_compressed FROM show_chunks('prices', older_than => INTERVAL '30 days') c;
SELECT pg_size_pretty(before_compression_total_bytes) AS before, pg_size_pretty(after_compression_total_bytes) AS after,
       round(before_compression_total_bytes::numeric / nullif(after_compression_total_bytes, 0), 1) AS ratio
FROM hypertable_compression_stats('prices');
```

```
before_compression 
--------------------
 23 MB
(1 row)

 chunks_compressed 
-------------------
                50
(1 row)

 before |  after  | ratio 
--------+---------+-------
 22 MB  | 5136 kB |   4.4
(1 row)
```

### 10. The raw query again, now on compressed chunks

```sql
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, SUMMARY ON)
SELECT zone, time_bucket('1 hour', ts) AS hour, avg(eur_mwh) AS avg_price, max(eur_mwh) AS peak
FROM prices
WHERE ts >= '2026-07-01' AND ts < '2026-10-01' AND zone = 'ee'
GROUP BY 1, 2 ORDER BY 2;
```

```
QUERY PLAN                                                                                                          
-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
 Finalize GroupAggregate (actual time=0.308..7.346 rows=2208 loops=1)
   Group Key: (time_bucket('01:00:00'::interval, prices.ts))
   Buffers: shared hit=434
   ->  Custom Scan (ChunkAppend) on prices (actual time=0.304..6.480 rows=2208 loops=1)
         Order: time_bucket('01:00:00'::interval, prices.ts)
         Buffers: shared hit=434
         ->  Partial GroupAggregate (actual time=0.303..0.327 rows=24 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_225_chunk.ts)
               Buffers: shared hit=33
               ->  Custom Scan (ColumnarScan) on _hyper_8_225_chunk (actual time=0.297..0.310 rows=96 loops=1)
                     Vectorized Filter: ((ts >= '2026-07-01 00:00:00+00'::timestamp with time zone) AND (ts < '2026-10-01 00:00:00+00'::timestamp with time zone))
                     Rows Removed by Filter: 576
                     Buffers: shared hit=33
                     ->  Index Scan Backward using _hyper_8_225_chunk_compressed_zone__ts_meta_v2_first_ts__ts_idx on _hyper_8_225_chunk_compressed (actual time=0.032..0.034 rows=1 loops=1)
                           Index Cond: ((zone = 'ee'::text) AND (_ts_meta_v2_first_ts >= '2026-07-01 00:00:00+00'::timestamp with time zone) AND (_ts_meta_v2_last_ts < '2026-10-01 00:00:00+00'::timestamp with time zone))
                           Buffers: shared hit=3
         ->  Partial GroupAggregate (actual time=0.257..0.464 rows=168 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_226_chunk.ts)
               Buffers: shared hit=32
               ->  Custom Scan (ColumnarScan) on _hyper_8_226_chunk (actual time=0.254..0.308 rows=672 loops=1)
                     Buffers: shared hit=32
                     ->  Index Scan Backward using _hyper_8_226_chunk_compressed_zone__ts_meta_v2_first_ts__ts_idx on _hyper_8_226_chunk_compressed (actual time=0.009..0.012 rows=1 loops=1)
                           Index Cond: (zone = 'ee'::text)
                           Buffers: shared hit=3
         ->  Partial GroupAggregate (actual time=0.278..0.433 rows=168 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_227_chunk.ts)
               Buffers: shared hit=32
               ->  Custom Scan (ColumnarScan) on _hyper_8_227_chunk (actual time=0.274..0.324 rows=672 loops=1)
                     Buffers: shared hit=32
                     ->  Index Scan Backward using _hyper_8_227_chunk_compressed_zone__ts_meta_v2_first_ts__ts_idx on _hyper_8_227_chunk_compressed (actual time=0.023..0.025 rows=1 loops=1)
                           Index Cond: (zone = 'ee'::text)
                           Buffers: shared hit=3
         ->  Partial GroupAggregate (actual time=0.216..0.344 rows=168 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_228_chunk.ts)
               Buffers: shared hit=32
               ->  Custom Scan (ColumnarScan) on _hyper_8_228_chunk (actual time=0.210..0.258 rows=672 loops=1)
                     Buffers: shared hit=32
                     ->  Index Scan Backward using _hyper_8_228_chunk_compressed_zone__ts_meta_v2_first_ts__ts_idx on _hyper_8_228_chunk_compressed (actual time=0.016..0.017 rows=1 loops=1)
                           Index Cond: (zone = 'ee'::text)
                           Buffers: shared hit=3
         ->  Partial GroupAggregate (actual time=0.213..0.340 rows=168 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_229_chunk.ts)
               Buffers: shared hit=32
               ->  Custom Scan (ColumnarScan) on _hyper_8_229_chunk (actual time=0.208..0.255 rows=672 loops=1)
                     Buffers: shared hit=32
                     ->  Index Scan Backward using _hyper_8_229_chunk_compressed_zone__ts_meta_v2_first_ts__ts_idx on _hyper_8_229_chunk_compressed (actual time=0.021..0.022 rows=1 loops=1)
                           Index Cond: (zone = 'ee'::text)
                           Buffers: shared hit=3
         ->  Partial GroupAggregate (actual time=0.540..0.791 rows=168 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_230_chunk.ts)
               Buffers: shared hit=32
               ->  Custom Scan (ColumnarScan) on _hyper_8_230_chunk (actual time=0.534..0.587 rows=672 loops=1)
                     Buffers: shared hit=32
                     ->  Index Scan Backward using _hyper_8_230_chunk_compressed_zone__ts_meta_v2_first_ts__ts_idx on _hyper_8_230_chunk_compressed (actual time=0.241..0.243 rows=1 loops=1)
                           Index Cond: (zone = 'ee'::text)
                           Buffers: shared hit=3
         ->  Partial GroupAggregate (actual time=0.391..0.537 rows=168 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_231_chunk.ts)
               Buffers: shared hit=32
               ->  Custom Scan (ColumnarScan) on _hyper_8_231_chunk (actual time=0.387..0.434 rows=672 loops=1)
                     Buffers: shared hit=32
                     ->  Index Scan Backward using _hyper_8_231_chunk_compressed_zone__ts_meta_v2_first_ts__ts_idx on _hyper_8_231_chunk_compressed (actual time=0.014..0.016 rows=1 loops=1)
                           Index Cond: (zone = 'ee'::text)
                           Buffers: shared hit=3
         ->  Partial GroupAggregate (actual time=0.310..0.441 rows=168 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_232_chunk.ts)
               Buffers: shared hit=32
               ->  Custom Scan (ColumnarScan) on _hyper_8_232_chunk (actual time=0.305..0.355 rows=672 loops=1)
                     Buffers: shared hit=32
                     ->  Index Scan Backward using _hyper_8_232_chunk_compressed_zone__ts_meta_v2_first_ts__ts_idx on _hyper_8_232_chunk_compressed (actual time=0.012..0.014 rows=1 loops=1)
                           Index Cond: (zone = 'ee'::text)
                           Buffers: shared hit=3
         ->  Partial GroupAggregate (actual time=0.250..0.397 rows=168 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_233_chunk.ts)
               Buffers: shared hit=32
               ->  Custom Scan (ColumnarScan) on _hyper_8_233_chunk (actual time=0.246..0.299 rows=672 loops=1)
                     Buffers: shared hit=32
                     ->  Index Scan Backward using _hyper_8_233_chunk_compressed_zone__ts_meta_v2_first_ts__ts_idx on _hyper_8_233_chunk_compressed (actual time=0.019..0.021 rows=1 loops=1)
                           Index Cond: (zone = 'ee'::text)
                           Buffers: shared hit=3
         ->  Partial GroupAggregate (actual time=0.262..0.393 rows=168 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_234_chunk.ts)
               Buffers: shared hit=32
               ->  Custom Scan (ColumnarScan) on _hyper_8_234_chunk (actual time=0.258..0.308 rows=672 loops=1)
                     Buffers: shared hit=32
                     ->  Index Scan Backward using _hyper_8_234_chunk_compressed_zone__ts_meta_v2_first_ts__ts_idx on _hyper_8_234_chunk_compressed (actual time=0.030..0.031 rows=1 loops=1)
                           Index Cond: (zone = 'ee'::text)
                           Buffers: shared hit=3
         ->  Partial GroupAggregate (actual time=0.197..0.356 rows=168 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_235_chunk.ts)
               Buffers: shared hit=32
               ->  Custom Scan (ColumnarScan) on _hyper_8_235_chunk (actual time=0.192..0.265 rows=672 loops=1)
                     Buffers: shared hit=32
                     ->  Index Scan Backward using _hyper_8_235_chunk_compressed_zone__ts_meta_v2_first_ts__ts_idx on _hyper_8_235_chunk_compressed (actual time=0.009..0.012 rows=1 loops=1)
                           Index Cond: (zone = 'ee'::text)
                           Buffers: shared hit=3
         ->  Partial GroupAggregate (actual time=0.051..0.402 rows=168 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_236_chunk.ts)
               Buffers: shared hit=27
               ->  Index Scan Backward using _hyper_8_236_chunk_prices_zone_ts_idx on _hyper_8_236_chunk (actual time=0.048..0.313 rows=672 loops=1)
                     Index Cond: (zone = 'ee'::text)
                     Buffers: shared hit=27
         ->  Partial GroupAggregate (actual time=0.032..0.588 rows=168 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_237_chunk.ts)
               Buffers: shared hit=27
               ->  Index Scan Backward using _hyper_8_237_chunk_prices_zone_ts_idx on _hyper_8_237_chunk (actual time=0.027..0.363 rows=672 loops=1)
                     Index Cond: (zone = 'ee'::text)
                     Buffers: shared hit=27
         ->  Partial GroupAggregate (actual time=0.097..0.467 rows=168 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_8_238_chunk.ts)
               Buffers: shared hit=27
               ->  Index Scan Backward using _hyper_8_238_chunk_prices_zone_ts_idx on _hyper_8_238_chunk (actual time=0.093..0.357 rows=672 loops=1)
                     Index Cond: (zone = 'ee'::text)
                     Buffers: shared hit=27
 Planning:
   Buffers: shared hit=3165 read=22
 Planning Time: 23.332 ms
 Execution Time: 8.894 ms
(118 rows)
```

### 11. Same data with 90-day chunks and no duplicate default index

```sql
DROP TABLE IF EXISTS prices_90;
CREATE TABLE prices_90 (ts timestamptz NOT NULL, zone text NOT NULL, eur_mwh double precision NOT NULL);
SELECT create_hypertable('prices_90', by_range('ts', INTERVAL '90 days'), create_default_indexes => false);
CREATE INDEX ON prices_90 (zone, ts DESC);
INSERT INTO prices_90 SELECT * FROM prices;
ANALYZE prices_90;
SELECT count(*) AS chunks, pg_size_pretty(hypertable_size('prices_90')) AS size_uncompressed FROM show_chunks('prices_90');
```

```
create_hypertable 
-------------------
 (10,t)
(1 row)

 chunks | size_uncompressed 
--------+-------------------
      5 | 13 MB
(1 row)
```

### 12. The raw query on 90-day chunks

```sql
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, SUMMARY ON)
SELECT zone, time_bucket('1 hour', ts) AS hour, avg(eur_mwh) AS avg_price, max(eur_mwh) AS peak
FROM prices_90
WHERE ts >= '2026-07-01' AND ts < '2026-10-01' AND zone = 'ee'
GROUP BY 1, 2 ORDER BY 2;
```

```
QUERY PLAN                                                                                     
------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
 Finalize GroupAggregate (actual time=0.041..4.968 rows=2208 loops=1)
   Group Key: (time_bucket('01:00:00'::interval, prices_90.ts))
   Buffers: shared hit=202
   ->  Custom Scan (ChunkAppend) on prices_90 (actual time=0.036..4.018 rows=2208 loops=1)
         Order: time_bucket('01:00:00'::interval, prices_90.ts)
         Buffers: shared hit=202
         ->  Partial GroupAggregate (actual time=0.035..2.401 rows=1560 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_10_249_chunk.ts)
               Buffers: shared hit=110
               ->  Index Scan Backward using _hyper_10_249_chunk_prices_90_zone_ts_idx on _hyper_10_249_chunk (actual time=0.029..1.525 rows=6240 loops=1)
                     Index Cond: ((zone = 'ee'::text) AND (ts >= '2026-07-01 00:00:00+00'::timestamp with time zone) AND (ts < '2026-10-01 00:00:00+00'::timestamp with time zone))
                     Buffers: shared hit=110
         ->  Partial GroupAggregate (actual time=0.043..1.489 rows=648 loops=1)
               Group Key: time_bucket('01:00:00'::interval, _hyper_10_250_chunk.ts)
               Buffers: shared hit=92
               ->  Index Scan Backward using _hyper_10_250_chunk_prices_90_zone_ts_idx on _hyper_10_250_chunk (actual time=0.039..1.015 rows=2592 loops=1)
                     Index Cond: ((zone = 'ee'::text) AND (ts >= '2026-07-01 00:00:00+00'::timestamp with time zone) AND (ts < '2026-10-01 00:00:00+00'::timestamp with time zone))
                     Buffers: shared hit=92
 Planning:
   Buffers: shared hit=780
 Planning Time: 6.116 ms
 Execution Time: 5.235 ms
(22 rows)
```
