import sqlite3
import threading
import time
import logging

logger = logging.getLogger(__name__)


class MetricsDB:
    """Base SQLite pour l'historique des métriques."""

    def __init__(self, path: str = "/data/metrics.db"):
        self.path = path
        self._conn = None
        self._lock = threading.Lock()

    def _get_conn(self):
        if self._conn is None:
            self._conn = sqlite3.connect(self.path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def init(self):
        conn = self._get_conn()
        conn.execute(
            """CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                cpu REAL DEFAULT 0,
                memory REAL DEFAULT 0,
                swap REAL DEFAULT 0,
                disk REAL DEFAULT 0,
                net_down REAL DEFAULT 0,
                net_up REAL DEFAULT 0,
                disk_read REAL DEFAULT 0,
                disk_write REAL DEFAULT 0,
                load1 REAL DEFAULT 0,
                containers INTEGER DEFAULT 0
            )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON snapshots(ts)")
        conn.commit()
        logger.info(f"Database initialized: {self.path}")

    def save(self, data: dict):
        if not data:
            return
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO snapshots (ts, cpu, memory, swap, disk, net_down, net_up, disk_read, disk_write, load1, containers) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    int(time.time()),
                    data.get("cpu", {}).get("percent", 0),
                    data.get("memory", {}).get("percent", 0),
                    data.get("memory", {}).get("swap_percent", 0),
                    data.get("disk", {}).get("percent", 0),
                    data.get("network", {}).get("download_mb", 0),
                    data.get("network", {}).get("upload_mb", 0),
                    data.get("disk_io", {}).get("read_mb", 0),
                    data.get("disk_io", {}).get("write_mb", 0),
                    data.get("system", {}).get("load", [0])[0] if data.get("system", {}).get("load") else 0,
                    len(data.get("containers", [])),
                ),
            )
            conn.commit()

    def get_history(self, period: str) -> dict:
        config = {
            "1h":  {"seconds": 3600,    "bucket": 30},
            "6h":  {"seconds": 21600,   "bucket": 180},
            "24h": {"seconds": 86400,   "bucket": 720},
            "7d":  {"seconds": 604800,  "bucket": 3600},
            "30d": {"seconds": 2592000, "bucket": 14400},
        }
        cfg = config.get(period, config["1h"])
        since = int(time.time()) - cfg["seconds"]
        bucket = cfg["bucket"]

        with self._lock:
            conn = self._get_conn()
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT
                    (ts / ?) * ? as t,
                    ROUND(AVG(cpu), 1) as cpu,
                    ROUND(AVG(memory), 1) as memory,
                    ROUND(AVG(swap), 1) as swap,
                    ROUND(AVG(disk), 1) as disk,
                    ROUND(AVG(net_down), 2) as net_down,
                    ROUND(AVG(net_up), 2) as net_up,
                    ROUND(AVG(disk_read), 2) as disk_read,
                    ROUND(AVG(disk_write), 2) as disk_write,
                    ROUND(AVG(load1), 2) as load1
                FROM snapshots
                WHERE ts > ?
                GROUP BY t
                ORDER BY t ASC""",
                (bucket, bucket, since),
            ).fetchall()
            conn.row_factory = None

        return {"period": period, "count": len(rows), "data": [dict(r) for r in rows]}

    def cleanup(self, days: int = 30):
        cutoff = int(time.time()) - (days * 86400)
        with self._lock:
            conn = self._get_conn()
            cur = conn.execute("DELETE FROM snapshots WHERE ts < ?", (cutoff,))
            conn.commit()
            deleted = cur.rowcount
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} old records")
        return deleted
