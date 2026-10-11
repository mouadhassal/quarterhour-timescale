"""Reproduce the support case end to end against a local TimescaleDB container.

    docker run -d --name tsdb -e POSTGRES_PASSWORD=demo -p 5433:5432 timescale/timescaledb:latest-pg16
    python data/fetch.py
    python run_case.py            # writes CASE_OUTPUT.md with every query, plan and timing

Uses `docker exec tsdb psql`, so nothing but Docker and Python is needed.
"""
import csv
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "CASE_OUTPUT.md"
log: list[str] = []


def psql(sql: str, title: str | None = None, show=True) -> str:
    r = subprocess.run(["docker", "exec", "-i", "tsdb", "psql", "-U", "postgres", "-v", "ON_ERROR_STOP=1",
                        "-X", "-q", "-P", "pager=off"], input=sql, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(r.stderr)
    if title and show:
        log.append(f"### {title}\n\n```sql\n{sql.strip()}\n```\n\n```\n{r.stdout.strip()}\n```\n")
    return r.stdout


def load():
    rows = []
    with (ROOT / "data" / "prices.csv").open() as f:
        for rec in csv.DictReader(f):
            ts = datetime.fromtimestamp(int(rec["timestamp_utc"]), timezone.utc).isoformat()
            for z in ("ee", "fi", "lv", "lt"):
                if rec[z]:
                    rows.append(f"{ts},{z},{rec[z]}")
    psql("DROP MATERIALIZED VIEW IF EXISTS prices_hourly CASCADE; DROP TABLE IF EXISTS prices CASCADE;"
         "CREATE TABLE prices (ts timestamptz NOT NULL, zone text NOT NULL, eur_mwh double precision NOT NULL);")
    psql("COPY prices FROM STDIN WITH (FORMAT csv);\n" + "\n".join(rows) + "\n\\.\n")
    return len(rows)


QUERY = """
SELECT zone, date_trunc('hour', ts) AS hour, avg(eur_mwh) AS avg_price, max(eur_mwh) AS peak
FROM prices
WHERE ts >= '2026-07-01' AND ts < '2026-10-01' AND zone = 'ee'
GROUP BY 1, 2 ORDER BY 2;"""


def main():
    n = load()
    log.insert(0, f"# Case output\n\nLoaded {n:,} rows (4 zones x 35,040 quarter-hours).\n")
    psql("ANALYZE prices; SELECT pg_size_pretty(pg_total_relation_size('prices')) AS plain_table_size;",
         "1. Plain table: size")
    psql("EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON, SUMMARY ON)" + QUERY,
         "2. Plain table: the dashboard query (one zone, hourly, last quarter)")
    psql("CREATE INDEX ON prices (zone, ts DESC); ANALYZE prices;"
         "EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, SUMMARY ON)" + QUERY
         + ";\nSELECT pg_size_pretty(pg_total_relation_size('prices')) AS plain_table_with_index;",
         "3. Plain table + (zone, ts) index")
    # Convert to a hypertable (data migrated in place), 7-day chunks
    psql("SELECT create_hypertable('prices', by_range('ts', INTERVAL '7 days'), migrate_data => true);"
         "ANALYZE prices;"
         "SELECT count(*) AS chunks, pg_size_pretty(hypertable_size('prices')) AS size FROM show_chunks('prices');"
         "SELECT count(*) AS indexes_per_chunk FROM pg_indexes"
         " WHERE schemaname || '.' || tablename = (SELECT show_chunks('prices') LIMIT 1)::text;",
         "4. Hypertable with 7-day chunks")
    psql("EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, SUMMARY ON)" + QUERY.replace("date_trunc('hour', ts)", "time_bucket('1 hour', ts)"),
         "5. Hypertable: chunk exclusion on the same query")
    psql("""CREATE MATERIALIZED VIEW prices_hourly WITH (timescaledb.continuous) AS
SELECT zone, time_bucket('1 hour', ts) AS hour, avg(eur_mwh) AS avg_price, max(eur_mwh) AS peak, count(*) AS n
FROM prices GROUP BY 1, 2 WITH DATA;
SELECT add_continuous_aggregate_policy('prices_hourly', start_offset => INTERVAL '3 days',
       end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '15 minutes');""",
         "6. Continuous aggregate for hourly roll-ups, refreshed every 15 minutes")
    psql("""EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, SUMMARY ON)
SELECT zone, hour, avg_price, peak FROM prices_hourly
WHERE hour >= '2026-07-01' AND hour < '2026-10-01' AND zone = 'ee' ORDER BY hour;""",
         "7. The dashboard query on the continuous aggregate")
    psql("""SELECT count(*) AS hours_where_quarter_hours_disagree
FROM prices_hourly WHERE n <> 4;""", "8. Sanity check: every hour has exactly 4 quarter-hours")
    psql("""SELECT pg_size_pretty(hypertable_size('prices')) AS before_compression;
ALTER TABLE prices SET (timescaledb.compress, timescaledb.compress_segmentby = 'zone',
                        timescaledb.compress_orderby = 'ts DESC');
SELECT count(compress_chunk(c)) AS chunks_compressed FROM show_chunks('prices', older_than => INTERVAL '30 days') c;
SELECT pg_size_pretty(before_compression_total_bytes) AS before, pg_size_pretty(after_compression_total_bytes) AS after,
       round(before_compression_total_bytes::numeric / nullif(after_compression_total_bytes, 0), 1) AS ratio
FROM hypertable_compression_stats('prices');""",
         "9. Compression, segmented by zone")
    psql("EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, SUMMARY ON)" + QUERY.replace("date_trunc('hour', ts)", "time_bucket('1 hour', ts)"),
         "10. The raw query again, now on compressed chunks")
    psql("""DROP TABLE IF EXISTS prices_90;
CREATE TABLE prices_90 (ts timestamptz NOT NULL, zone text NOT NULL, eur_mwh double precision NOT NULL);
SELECT create_hypertable('prices_90', by_range('ts', INTERVAL '90 days'), create_default_indexes => false);
CREATE INDEX ON prices_90 (zone, ts DESC);
INSERT INTO prices_90 SELECT * FROM prices;
ANALYZE prices_90;
SELECT count(*) AS chunks, pg_size_pretty(hypertable_size('prices_90')) AS size_uncompressed FROM show_chunks('prices_90');""",
         "11. Same data with 90-day chunks and no duplicate default index")
    psql("EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, SUMMARY ON)"
         + QUERY.replace("FROM prices", "FROM prices_90").replace("date_trunc('hour', ts)", "time_bucket('1 hour', ts)"),
         "12. The raw query on 90-day chunks")
    OUT.write_text("\n".join(log), encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
