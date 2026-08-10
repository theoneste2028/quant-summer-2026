"""
Week 7 — News Pipeline: the same data in SQL and in MongoDB
===========================================================
CS 217. Company news is the half of the data that does *not* fit tables well:
each article is a nested document with a provider object, a canonical URL
object, a thumbnail with a variable-length list of resolutions, and a list of
related tickers whose length differs per article.

To compare the two models honestly, the SAME articles are loaded into both
stores, each modelled the way that store wants:

  SQLite   `news` (one row per article, nested objects flattened to columns)
           + `news_tickers` (junction table, because one article can mention
           several tickers — a many-to-many that a single table cannot hold)

  MongoDB  one document per article, stored essentially as it arrived

Then the same seven questions are asked of both. Five are the "equivalent
lookups" the brief calls for; the last two are the ones that expose where each
model starts to hurt.

Run:
    python news_pipeline.py              # fetch, load both stores, compare
    python news_pipeline.py --offline    # reuse cached JSON, no network
"""
from __future__ import annotations
import os, sys, json, time, sqlite3, argparse
import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DB_PATH = os.path.join(REPO, "data", "portfolio.db")
CACHE = os.path.join(HERE, "results", "news_cache.json")
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")

NEWS_DDL = """
CREATE TABLE IF NOT EXISTS news (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    publisher    TEXT,
    content_type TEXT,
    pub_date     TEXT,
    link         TEXT,
    summary      TEXT
);
-- One article can mention several tickers, so the relationship is
-- many-to-many and needs its own table. In the document store this is a single
-- array field on the article; here it costs a second table and a join.
CREATE TABLE IF NOT EXISTS news_tickers (
    news_id TEXT NOT NULL REFERENCES news(id),
    ticker  TEXT NOT NULL,
    PRIMARY KEY (news_id, ticker)
);
CREATE INDEX IF NOT EXISTS idx_news_pubdate ON news(pub_date);
"""


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------
def mongo_db(uri=MONGO_URI, name="quant_summer"):
    """Return (db, backend). Real MongoDB when reachable, else mongomock.

    The pymongo API calls below are identical either way; mongomock exists so
    the comparison is reproducible on a machine without a mongod running.
    """
    try:
        import pymongo
        client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=800)
        client.admin.command("ping")
        return client[name], f"MongoDB at {uri}"
    except Exception:
        try:
            import mongomock
            return mongomock.MongoClient()[name], "mongomock (in-process)"
        except ImportError:
            raise RuntimeError(
                "No MongoDB reachable and mongomock is not installed.\n"
                "  brew install mongodb-community && brew services start mongodb-community\n"
                "  or: pip install mongomock")


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------
def fetch_news(tickers, offline=False) -> list[dict]:
    """Fetch raw news documents, caching them so --offline can replay."""
    if offline:
        if not os.path.exists(CACHE):
            raise FileNotFoundError(f"no cache at {CACHE}; run online once first")
        with open(CACHE) as fh:
            return json.load(fh)

    import yfinance as yf
    docs, seen = [], set()
    for t in tickers:
        try:
            items = yf.Ticker(t).news or []
        except Exception as e:
            print(f"  ! {t}: {type(e).__name__}")
            continue
        for it in items:
            c = it.get("content") or {}
            aid = it.get("id") or c.get("id")
            if not aid or aid in seen:
                # The same article legitimately shows up under several tickers;
                # record the extra ticker rather than storing it twice.
                if aid:
                    for d in docs:
                        if d["_id"] == aid and t not in d["tickers"]:
                            d["tickers"].append(t)
                continue
            seen.add(aid)
            docs.append({
                "_id": aid,
                "tickers": [t],
                "title": c.get("title"),
                "summary": c.get("summary") or c.get("description"),
                "content_type": c.get("contentType"),
                "pub_date": c.get("pubDate"),
                "provider": c.get("provider") or {},
                "canonical_url": c.get("canonicalUrl") or {},
                "thumbnail": c.get("thumbnail") or {},
                "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            })
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w") as fh:
        json.dump(docs, fh, indent=1, default=str)
    return docs


# Company-name aliases, because an article about Alphabet rarely prints
# "GOOGL" in the headline. Only names distinctive enough not to collide.
ALIASES = {
    "GOOGL": ["alphabet", "google"], "MU": ["micron"], "NVDA": ["nvidia"],
    "PL": ["planet labs"], "ONDS": ["ondas"], "EOSE": ["eos energy"],
    "NBIS": ["nebius"], "TQQQ": ["proshares ultrapro"], "ASTS": ["ast spacemobile"],
    "OPEN": ["opendoor"], "IREN": ["iren limited"], "AGX": ["argan"],
}


def enrich_mentions(docs, universe) -> int:
    """Tag each article with every portfolio ticker its text mentions.

    Yahoo's per-ticker feeds are disjoint — an article fetched under GOOGL is
    never also returned under MU — so without this step every article has
    exactly one ticker and the many-to-many comparison is vacuous. Entity
    tagging is ordinary ETL enrichment, and it is what actually creates the
    array-valued field the document store is being judged on.

    Bare symbols shorter than three characters are not matched: 'PL', 'MU' and
    'T' collide with ordinary words and punctuation far too often. Those names
    are reached through their aliases instead.
    """
    import re
    patterns = {}
    for t in universe:
        alts = [re.escape(a) for a in ALIASES.get(t, [])]
        if len(t) >= 3:
            alts.append(re.escape(t))
        if alts:
            patterns[t] = re.compile(r"\b(" + "|".join(alts) + r")\b", re.IGNORECASE)

    added = 0
    for d in docs:
        text = f"{d.get('title') or ''} {d.get('summary') or ''}"
        for t, pat in patterns.items():
            if t not in d["tickers"] and pat.search(text):
                d["tickers"].append(t)
                added += 1
    return added


# ---------------------------------------------------------------------------
# Load — relational
# ---------------------------------------------------------------------------
def load_sqlite(con, docs) -> tuple[int, int]:
    """Flatten documents into `news` + `news_tickers`, one transaction."""
    con.executescript(NEWS_DDL)
    before = con.execute("SELECT COUNT(*) FROM news").fetchone()[0]
    before_t = con.execute("SELECT COUNT(*) FROM news_tickers").fetchone()[0]
    cur = con.cursor()
    try:
        cur.execute("BEGIN")
        for d in docs:
            cur.execute(
                """INSERT OR IGNORE INTO news
                   (id,title,publisher,content_type,pub_date,link,summary)
                   VALUES (?,?,?,?,?,?,?)""",
                (d["_id"], d.get("title") or "(untitled)",
                 (d.get("provider") or {}).get("displayName"),
                 d.get("content_type"), d.get("pub_date"),
                 (d.get("canonical_url") or {}).get("url"),
                 (d.get("summary") or "")[:2000]))
            for t in d.get("tickers", []):
                cur.execute("INSERT OR IGNORE INTO news_tickers VALUES (?,?)",
                            (d["_id"], t))
        con.commit()
    except Exception:
        con.rollback()
        raise
    return (con.execute("SELECT COUNT(*) FROM news").fetchone()[0] - before,
            con.execute("SELECT COUNT(*) FROM news_tickers").fetchone()[0] - before_t)


def load_mongo(db, docs) -> int:
    """Upsert documents as-is. _id is the article id, so re-running is a no-op."""
    coll = db["news"]
    n = 0
    for d in docs:
        res = coll.replace_one({"_id": d["_id"]}, d, upsert=True)
        if res.upserted_id is not None:
            n += 1
    coll.create_index("tickers")
    coll.create_index("pub_date")
    return n


# ---------------------------------------------------------------------------
# The seven questions, asked of both stores
# ---------------------------------------------------------------------------
def comparisons(con, db, ticker="GOOGL", keyword="AI"):
    coll = db["news"]
    out = []

    # 1. Latest 5 articles for one ticker.
    sql = """SELECT n.title, n.pub_date FROM news n
             JOIN news_tickers nt ON nt.news_id = n.id
             WHERE nt.ticker = ? ORDER BY n.pub_date DESC LIMIT 5"""
    a = [tuple(r) for r in con.execute(sql, (ticker,))]
    b = [(d["title"], d["pub_date"]) for d in
         coll.find({"tickers": ticker}, {"title": 1, "pub_date": 1})
             .sort("pub_date", -1).limit(5)]
    out.append(("1. Latest 5 articles for " + ticker,
                sql.strip(),
                f'db.news.find({{"tickers": "{ticker}"}})\n'
                f'       .sort("pub_date", -1).limit(5)',
                a, b))

    # 2. Article count per ticker (top 5).
    sql = """SELECT ticker, COUNT(*) n FROM news_tickers
             GROUP BY ticker ORDER BY n DESC, ticker LIMIT 5"""
    a = [tuple(r) for r in con.execute(sql)]
    b = [(d["_id"], d["n"]) for d in coll.aggregate([
        {"$unwind": "$tickers"},
        {"$group": {"_id": "$tickers", "n": {"$sum": 1}}},
        {"$sort": {"n": -1, "_id": 1}}, {"$limit": 5}])]
    out.append(("2. Article count per ticker (top 5)",
                sql.strip(),
                'db.news.aggregate([{"$unwind": "$tickers"},\n'
                '  {"$group": {"_id": "$tickers", "n": {"$sum": 1}}},\n'
                '  {"$sort": {"n": -1}}, {"$limit": 5}])',
                a, b))

    # 3. Articles published in a window.
    lo = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)).strftime("%Y-%m-%d")
    sql = "SELECT COUNT(*) FROM news WHERE pub_date >= ?"
    a = [tuple(r) for r in con.execute(sql, (lo,))]
    b = [(coll.count_documents({"pub_date": {"$gte": lo}}),)]
    out.append((f"3. Articles published since {lo}",
                sql.strip(),
                f'db.news.count_documents({{"pub_date": {{"$gte": "{lo}"}}}})',
                a, b))

    # 4. Distinct publishers, with counts.
    sql = """SELECT publisher, COUNT(*) n FROM news
             WHERE publisher IS NOT NULL
             GROUP BY publisher ORDER BY n DESC, publisher LIMIT 5"""
    a = [tuple(r) for r in con.execute(sql)]
    b = [(d["_id"], d["n"]) for d in coll.aggregate([
        {"$match": {"provider.displayName": {"$ne": None}}},
        {"$group": {"_id": "$provider.displayName", "n": {"$sum": 1}}},
        {"$sort": {"n": -1, "_id": 1}}, {"$limit": 5}])]
    out.append(("4. Top publishers by article count",
                sql.strip(),
                'db.news.aggregate([\n'
                '  {"$group": {"_id": "$provider.displayName", "n": {"$sum": 1}}},\n'
                '  {"$sort": {"n": -1}}, {"$limit": 5}])',
                a, b))

    # 5. Keyword in the title.
    sql = "SELECT COUNT(*) FROM news WHERE title LIKE ?"
    a = [tuple(r) for r in con.execute(sql, (f"%{keyword}%",))]
    b = [(coll.count_documents({"title": {"$regex": keyword, "$options": "i"}}),)]
    out.append((f"5. Titles mentioning {keyword!r}",
                sql.strip(),
                f'db.news.count_documents({{"title": {{"$regex": "{keyword}"}}}})',
                a, b))

    # 6. Articles mentioning MORE THAN ONE portfolio ticker.
    #    SQL needs the junction table plus GROUP BY/HAVING; Mongo asks the array
    #    its own length. This is the shape difference, not a performance one.
    sql = """SELECT COUNT(*) FROM (
               SELECT news_id FROM news_tickers
               GROUP BY news_id HAVING COUNT(*) > 1)"""
    a = [tuple(r) for r in con.execute(sql)]
    b = [(coll.count_documents({"$expr": {"$gt": [{"$size": "$tickers"}, 1]}}),)]
    out.append(("6. Articles mentioning >1 portfolio ticker",
                sql.strip(),
                'db.news.count_documents(\n'
                '  {"$expr": {"$gt": [{"$size": "$tickers"}, 1]}})',
                a, b))

    # 7. A field the relational schema never modelled: how many articles carry
    #    a thumbnail with more than one stored resolution? The document store
    #    answers it; SQL cannot, because flattening dropped the sub-document.
    n_res = coll.count_documents(
        {"$expr": {"$gt": [{"$size": {"$ifNull": ["$thumbnail.resolutions", []]}}, 1]}})
    out.append(("7. Articles whose thumbnail has >1 resolution",
                "-- not answerable: `thumbnail.resolutions` was dropped when the\n"
                "-- document was flattened into columns. Answering it needs a\n"
                "-- schema migration and a re-load of the source data.",
                'db.news.count_documents({"$expr":\n'
                '  {"$gt": [{"$size": "$thumbnail.resolutions"}, 1]}})',
                None, [(n_res,)]))
    return out


def print_comparisons(rows):
    for title, sql, mongo, a, b in rows:
        print(f"\n{'='*78}\n{title}\n{'='*78}")
        print("--- SQL " + "-" * 70)
        print("  " + sql.replace("\n", "\n  "))
        print(f"  => {a if a is not None else '(cannot be answered)'}")
        print("--- MongoDB " + "-" * 66)
        print("  " + mongo.replace("\n", "\n  "))
        print(f"  => {b}")
        if a is not None:
            same = a == b
            print(f"  MATCH: {'yes' if same else 'NO — ' + str((a, b))}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="replay cached news")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--ticker", default="GOOGL")
    ap.add_argument("--limit-tickers", type=int, default=12)
    a = ap.parse_args()

    con = sqlite3.connect(a.db)
    con.execute("PRAGMA foreign_keys = ON")
    # Currently-held names first, most-traded first within that. Picking
    # tickers alphabetically instead gives a set of unrelated small caps whose
    # news never overlaps, which makes the multi-ticker comparison vacuous.
    tickers = [r[0] for r in con.execute("""
        SELECT ticker FROM trades GROUP BY ticker
        HAVING SUM(CASE side WHEN 'BUY' THEN quantity ELSE -quantity END) > 1e-9
        ORDER BY COUNT(*) DESC""")][:a.limit_tickers]
    if a.ticker not in tickers:
        tickers.append(a.ticker)

    t0 = time.perf_counter()
    print(f"Fetching news for {len(tickers)} tickers "
          f"({'cached' if a.offline else 'live'}) ...")
    docs = fetch_news(tickers, offline=a.offline)
    print(f"  {len(docs)} distinct articles in {time.perf_counter()-t0:.1f}s")

    universe = [r[0] for r in con.execute("SELECT ticker FROM securities")]
    n_tags = enrich_mentions(docs, universe)
    multi = sum(1 for d in docs if len(d["tickers"]) > 1)
    print(f"  enrichment: +{n_tags} ticker mentions found in article text "
          f"({multi} articles now reference more than one ticker)")

    n_news, n_link = load_sqlite(con, docs)
    db, backend = mongo_db()
    n_mongo = load_mongo(db, docs)
    tot_sql = con.execute("SELECT COUNT(*) FROM news").fetchone()[0]
    print(f"  SQLite : +{n_news} articles, +{n_link} links  (total {tot_sql})")
    print(f"  Mongo  : +{n_mongo} documents (total {db['news'].count_documents({})})"
          f"  [backend: {backend}]")
    if "mongomock" in backend:
        print("           note: mongomock is in-process and starts empty each run,"
              " so its\n           totals reflect this batch only, unlike the"
              " persistent SQLite file.")

    # Idempotency: loading the identical batch again must add nothing.
    again_sql, _ = load_sqlite(con, docs)
    again_mongo = load_mongo(db, docs)
    print(f"  re-load: SQLite +{again_sql}, Mongo +{again_mongo}  "
          f"({'idempotent' if again_sql == 0 and again_mongo == 0 else 'NOT IDEMPOTENT'})")

    print_comparisons(comparisons(con, db, ticker=a.ticker))
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
