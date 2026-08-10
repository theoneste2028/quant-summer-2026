"""
Week 8 — Load the NYC Yellow Taxi dataset into SQLite
=====================================================
CS 217. Source: NYC TLC trip records, January 2024 (~2.96M rows, 48 MB Parquet).
    https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2024-01.parquet
    https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv

The table is created with NO indexes beyond the implicit rowid. That is the
point: the benchmark measures what indexes buy, so the baseline has to be a
table that has none.

Run:
    python load_taxi.py            # download if needed, then load
    python load_taxi.py --force    # rebuild from scratch
"""
from __future__ import annotations
import os, sys, time, sqlite3, argparse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DATA = os.path.join(REPO, "data", "taxi")
DB_PATH = os.path.join(DATA, "taxi.db")
PARQUET = os.path.join(DATA, "yellow_tripdata_2024-01.parquet")
ZONES_CSV = os.path.join(DATA, "taxi_zone_lookup.csv")

PARQUET_URL = ("https://d37ci6vzurychx.cloudfront.net/trip-data/"
               "yellow_tripdata_2024-01.parquet")
ZONES_URL = "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv"

# Deliberately no indexes. Week 8 adds them and measures the difference.
DDL = """
DROP TABLE IF EXISTS trips;
CREATE TABLE trips (
    trip_id        INTEGER PRIMARY KEY,
    vendor_id      INTEGER,
    pickup_ts      TEXT    NOT NULL,   -- ISO 'YYYY-MM-DD HH:MM:SS'
    dropoff_ts     TEXT,
    passenger_count INTEGER,
    trip_distance  REAL,
    pu_location_id INTEGER,
    do_location_id INTEGER,
    payment_type   INTEGER,
    fare_amount    REAL,
    tip_amount     REAL,
    total_amount   REAL
);
DROP TABLE IF EXISTS zones;
CREATE TABLE zones (
    location_id INTEGER PRIMARY KEY,
    borough     TEXT,
    zone        TEXT,
    service_zone TEXT
);
"""

COLS = ["VendorID", "tpep_pickup_datetime", "tpep_dropoff_datetime",
        "passenger_count", "trip_distance", "PULocationID", "DOLocationID",
        "payment_type", "fare_amount", "tip_amount", "total_amount"]


def download(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    print(f"  downloading {os.path.basename(path)} ...")
    urllib.request.urlretrieve(url, path)


def load(db_path=DB_PATH, force=False, batch_rows=200_000):
    import pyarrow.parquet as pq
    import csv

    if os.path.exists(db_path) and not force:
        con = sqlite3.connect(db_path)
        try:
            n = con.execute("SELECT COUNT(*) FROM trips").fetchone()[0]
            if n > 0:
                print(f"trips already loaded: {n:,} rows ({db_path})")
                con.close()
                return n
        except sqlite3.OperationalError:
            pass
        con.close()

    download(PARQUET_URL, PARQUET)
    download(ZONES_URL, ZONES_CSV)

    t0 = time.perf_counter()
    con = sqlite3.connect(db_path)
    con.executescript(DDL)
    # Bulk-load pragmas: this is a rebuildable analytics copy, not the system of
    # record, so trading durability for load speed is the right call here.
    con.execute("PRAGMA journal_mode = OFF")
    con.execute("PRAGMA synchronous = OFF")

    pf = pq.ParquetFile(PARQUET)
    total = 0
    for batch in pf.iter_batches(batch_size=batch_rows, columns=COLS):
        d = batch.to_pydict()
        rows = zip(
            d["VendorID"],
            [str(x)[:19] if x is not None else None for x in d["tpep_pickup_datetime"]],
            [str(x)[:19] if x is not None else None for x in d["tpep_dropoff_datetime"]],
            d["passenger_count"], d["trip_distance"],
            d["PULocationID"], d["DOLocationID"], d["payment_type"],
            d["fare_amount"], d["tip_amount"], d["total_amount"])
        rows = [r for r in rows if r[1]]          # pickup_ts is NOT NULL
        con.executemany(
            """INSERT INTO trips (vendor_id,pickup_ts,dropoff_ts,passenger_count,
                                  trip_distance,pu_location_id,do_location_id,
                                  payment_type,fare_amount,tip_amount,total_amount)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""", rows)
        total += len(rows)
        print(f"    {total:,} rows", end="\r", flush=True)
    con.commit()

    with open(ZONES_CSV) as fh:
        r = csv.DictReader(fh)
        con.executemany("INSERT OR REPLACE INTO zones VALUES (?,?,?,?)",
                        [(int(x["LocationID"]), x["Borough"], x["Zone"],
                          x["service_zone"]) for x in r])
    con.commit()

    n = con.execute("SELECT COUNT(*) FROM trips").fetchone()[0]
    z = con.execute("SELECT COUNT(*) FROM zones").fetchone()[0]
    size = os.path.getsize(db_path) / 1e6
    print(f"\nloaded {n:,} trips and {z} zones in "
          f"{time.perf_counter()-t0:.1f}s  ({size:.0f} MB, no indexes)")
    con.close()
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--db", default=DB_PATH)
    a = ap.parse_args()
    load(a.db, force=a.force)
