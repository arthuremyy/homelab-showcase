import psutil
import docker
import threading
import time
import logging
import platform
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# Interfaces to show on frontend (host physical + VPN)
HOST_INTERFACES = {"enp4s0", "tailscale0"}
# Primary interface for rate calculation in the network card
PRIMARY_INTERFACE = "enp4s0"
# Known interface IPs (since we can't easily look them up from inside a container)
INTERFACE_IPS = {
    "enp4s0": os.environ.get("HOST_IP", "192.168.1.10"),
    "tailscale0": os.environ.get("TAILSCALE_IP", "100.64.0.1"),
}


def _parse_proc_net_dev(pid=1):
    """Parse /proc/<pid>/net/dev to get real host network counters.
    Returns dict: {iface_name: {rx_bytes, tx_bytes, rx_packets, tx_packets}}
    """
    result = {}
    try:
        with open(f"/proc/{pid}/net/dev", "r") as f:
            for line in f:
                line = line.strip()
                if ":" not in line or line.startswith("Inter") or line.startswith("face"):
                    continue
                iface, data = line.split(":", 1)
                iface = iface.strip()
                parts = data.split()
                if len(parts) >= 10:
                    result[iface] = {
                        "rx_bytes": int(parts[0]),
                        "rx_packets": int(parts[1]),
                        "tx_bytes": int(parts[8]),
                        "tx_packets": int(parts[9]),
                    }
    except (FileNotFoundError, PermissionError) as e:
        logger.warning(f"Cannot read /proc/{pid}/net/dev: {e}")
    return result


class MetricsCollector:
    """Collecteur de métriques avec threads en arrière-plan."""

    def __init__(self):
        self._lock = threading.Lock()
        self._system_data = {}
        self._container_data = []
        self._running = False
        self._prev_net = None
        self._prev_net_time = None
        self._prev_disk_io = None
        self._prev_disk_time = None

        # Cache statique (calculé une seule fois)
        self._static = None
        self._disk_partitions = None
        self._disk_partitions_time = 0
        self._interfaces_cache = None
        self._interfaces_time = 0
        self._processes_cache = {"by_cpu": [], "by_memory": []}
        self._processes_time = 0

        try:
            self._docker = docker.from_env()
        except Exception:
            self._docker = None
            logger.warning("Docker client unavailable")

    def start(self):
        self._running = True
        threading.Thread(target=self._system_loop, daemon=True).start()
        threading.Thread(target=self._docker_loop, daemon=True).start()
        logger.info("Metrics collector started")

    def stop(self):
        self._running = False

    def get_current(self):
        with self._lock:
            return {**self._system_data, "containers": list(self._container_data)}

    # ── System metrics loop (every 1s) ──

    def _system_loop(self):
        psutil.cpu_percent(percpu=True)
        time.sleep(0.5)
        while self._running:
            try:
                data = self._collect_system()
                with self._lock:
                    self._system_data = data
            except Exception as e:
                logger.error(f"System collection error: {e}")
            time.sleep(1)

    # ── Docker stats loop (every 12s) ──

    def _docker_loop(self):
        time.sleep(1)
        while self._running:
            try:
                containers = self._collect_containers()
                with self._lock:
                    self._container_data = containers
            except Exception as e:
                logger.error(f"Docker collection error: {e}")
            time.sleep(12)

    # ── System data collection ──

    def _get_static(self):
        """Infos statiques du systeme, calculees une seule fois."""
        if self._static is None:
            hostname = os.environ.get("HOST_HOSTNAME", platform.node())
            os_str = f"{platform.system()} {platform.release()}"
            cores = psutil.cpu_count(logical=False) or 1
            threads = psutil.cpu_count(logical=True) or 1
            self._static = {"hostname": hostname, "os": os_str, "cores": cores, "threads": threads}
        return self._static

    # Exclude Docker internal bind mounts and virtual filesystems
    _DISK_EXCLUDE_MOUNTS = {"/etc/resolv.conf", "/etc/hostname", "/etc/hosts"}
    _DISK_EXCLUDE_FS = {"tmpfs", "devtmpfs", "devfs", "squashfs", "overlay"}

    def _get_disk_partitions(self, now):
        """Partitions disque, mises a jour toutes les 60s."""
        if self._disk_partitions is None or (now - self._disk_partitions_time) > 60:
            disks = []
            seen_devices = set()
            for part in psutil.disk_partitions(all=False):
                # Skip Docker internal mounts and virtual FS
                if part.mountpoint in self._DISK_EXCLUDE_MOUNTS:
                    continue
                if part.fstype in self._DISK_EXCLUDE_FS:
                    continue
                try:
                    u = psutil.disk_usage(part.mountpoint)
                    # Skip duplicate devices (same physical disk)
                    dev_key = (part.device, u.total)
                    if dev_key in seen_devices:
                        continue
                    seen_devices.add(dev_key)
                    disks.append({
                        "mount": part.mountpoint, "device": part.device, "fs": part.fstype,
                        "total_gb": round(u.total / (1024**3), 1),
                        "used_gb": round(u.used / (1024**3), 1),
                        "percent": round(u.percent, 1),
                    })
                except (PermissionError, OSError):
                    continue
            self._disk_partitions = disks
            self._disk_partitions_time = now
        else:
            # Mettre a jour seulement l'usage (rapide)
            for d in self._disk_partitions:
                try:
                    u = psutil.disk_usage(d["mount"])
                    d["used_gb"] = round(u.used / (1024**3), 1)
                    d["percent"] = round(u.percent, 1)
                except (PermissionError, OSError):
                    pass
        return self._disk_partitions

    def _get_interfaces(self, now, net_dev):
        """Interfaces réseau host via /proc/1/net/dev, mises à jour toutes les 10s."""
        if self._interfaces_cache is None or (now - self._interfaces_time) > 10:
            interfaces = []
            for name in HOST_INTERFACES:
                if name not in net_dev:
                    continue
                counters = net_dev[name]
                # Try to get IP from /proc/1 namespace - check operstate
                up = True
                try:
                    with open(f"/sys/class/net/{name}/operstate", "r") as f:
                        up = f.read().strip() == "up"
                except Exception:
                    pass
                # Get IP from known config
                ip = INTERFACE_IPS.get(name, "N/A")
                # Get link speed
                speed = 0
                try:
                    with open(f"/sys/class/net/{name}/speed", "r") as f:
                        speed = int(f.read().strip())
                except Exception:
                    pass
                interfaces.append({
                    "name": name,
                    "ip": ip,
                    "up": up,
                    "speed": speed,
                    "rx_bytes": counters["rx_bytes"],
                    "tx_bytes": counters["tx_bytes"],
                    "rx_gb": round(counters["rx_bytes"] / (1024**3), 2),
                    "tx_gb": round(counters["tx_bytes"] / (1024**3), 2),
                })
            self._interfaces_cache = interfaces
            self._interfaces_time = now
        return self._interfaces_cache

    def _get_processes(self, now):
        """Top processus, mis a jour toutes les 30s.

        30s et non 6s : avec pid:"host", chaque passage de process_iter lit des
        processus hôte que le profil AppArmor docker-default refuse (compté comme
        ptrace). C est inoffensif (AccessDenied est attrapé) mais générait ~14k
        lignes de refus par jour dans le journal systemd.
        """
        if (now - self._processes_time) < 30:
            return self._processes_cache

        procs_cpu, procs_mem = [], []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "memory_info"]):
            try:
                info = p.info
                if info["cpu_percent"] and info["cpu_percent"] > 0:
                    procs_cpu.append(info)
                if info["memory_percent"] and info["memory_percent"] > 0.1:
                    procs_mem.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        procs_cpu.sort(key=lambda x: x.get("cpu_percent", 0), reverse=True)
        procs_mem.sort(key=lambda x: x.get("memory_percent", 0), reverse=True)

        self._processes_cache = {
            "by_cpu": [{"name": p["name"], "pid": p["pid"], "cpu": round(p["cpu_percent"], 1)} for p in procs_cpu[:8]],
            "by_memory": [
                {"name": p["name"], "pid": p["pid"], "mem_mb": round(p["memory_info"].rss / (1024 * 1024), 1), "percent": round(p["memory_percent"], 1)}
                for p in procs_mem[:8]
            ],
        }
        self._processes_time = now
        return self._processes_cache

    def _collect_system(self):
        now = time.time()
        static = self._get_static()

        # CPU (rapide, ~0ms)
        cpu_overall = psutil.cpu_percent(percpu=False)
        cpu_per_core = psutil.cpu_percent(percpu=True)
        cpu_freq = psutil.cpu_freq()

        # Memory (rapide, ~0ms)
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()

        # Disks (cache 60s pour partitions, usage mis a jour)
        disks = self._get_disk_partitions(now)
        primary = next((d for d in disks if "/mnt/data" in d["mount"]), disks[0] if disks else None)

        # Disk I/O rates
        dio = psutil.disk_io_counters()
        dr, dw = 0.0, 0.0
        if self._prev_disk_io and self._prev_disk_time:
            dt = now - self._prev_disk_time
            if dt > 0:
                dr = (dio.read_bytes - self._prev_disk_io.read_bytes) / dt / (1024 * 1024)
                dw = (dio.write_bytes - self._prev_disk_io.write_bytes) / dt / (1024 * 1024)
        self._prev_disk_io = dio
        self._prev_disk_time = now

        # Network rates from /proc/1/net/dev (host namespace via pid:host)
        net_dev = _parse_proc_net_dev(pid=1)
        primary_net = net_dev.get(PRIMARY_INTERFACE, {})
        net_rx = primary_net.get("rx_bytes", 0)
        net_tx = primary_net.get("tx_bytes", 0)
        nd, nu = 0.0, 0.0
        if self._prev_net and self._prev_net_time:
            dt = now - self._prev_net_time
            if dt > 0:
                nd = (net_rx - self._prev_net["rx"]) / dt / (1024 * 1024)
                nu = (net_tx - self._prev_net["tx"]) / dt / (1024 * 1024)
        self._prev_net = {"rx": net_rx, "tx": net_tx}
        self._prev_net_time = now

        # Interfaces (cache 10s)
        interfaces = self._get_interfaces(now, net_dev)

        # Temperature — séparer CPU et disque
        temp = None
        temperatures = {}
        try:
            all_temps = psutil.sensors_temperatures()
            if all_temps:
                CPU_SENSORS  = {'coretemp', 'k10temp', 'zenpower', 'cpu_thermal', 'acpitz', 'cpu-thermal'}
                DISK_SENSORS = {'nvme', 'drivetemp', 'ahci', 'hddtemp'}
                for sensor_name, entries in all_temps.items():
                    if not entries:
                        continue
                    key = sensor_name.lower()
                    val = round(entries[0].current, 1)
                    rec = {"sensor": sensor_name, "value": val}
                    if any(k in key for k in CPU_SENSORS):
                        temperatures['cpu'] = rec
                    elif any(k in key for k in DISK_SENSORS):
                        temperatures['disk'] = rec
                    elif 'other' not in temperatures:
                        temperatures['other'] = rec
                # temp backward-compat: prefer CPU, fallback disk/other
                temp = temperatures.get('cpu') or temperatures.get('disk') or temperatures.get('other')
        except Exception:
            pass

        # Processes (cache 6s)
        processes = self._get_processes(now)

        # Uptime
        boot = psutil.boot_time()
        up_s = int(now - boot)
        d, rem = divmod(up_s, 86400)
        h, rem = divmod(rem, 3600)
        m, _ = divmod(rem, 60)
        uptime_str = (f"{d}j " if d else "") + f"{h}h {m}min"

        return {
            "timestamp": int(now),
            "system": {
                "hostname": static["hostname"],
                "os": static["os"],
                "uptime": uptime_str,
                "uptime_seconds": up_s,
                "load": [round(x, 2) for x in psutil.getloadavg()],
            },
            "cpu": {
                "percent": round(cpu_overall, 1),
                "per_core": [round(c, 1) for c in cpu_per_core],
                "cores": static["cores"],
                "threads": static["threads"],
                "freq_mhz": round(cpu_freq.current) if cpu_freq else 0,
            },
            "temperature": temp,
            "temperatures": temperatures,
            "memory": {
                "total_gb": round(mem.total / (1024**3), 1),
                "used_gb": round(mem.used / (1024**3), 1),
                "percent": round(mem.percent, 1),
                "swap_total_gb": round(swap.total / (1024**3), 1),
                "swap_used_gb": round(swap.used / (1024**3), 1),
                "swap_percent": round(swap.percent, 1),
            },
            "disk": {
                "total_gb": primary["total_gb"] if primary else 0,
                "used_gb": primary["used_gb"] if primary else 0,
                "percent": primary["percent"] if primary else 0,
                "mount": primary["mount"] if primary else "/",
            },
            "disks": disks,
            "disk_io": {"read_mb": round(max(dr, 0), 2), "write_mb": round(max(dw, 0), 2)},
            "network": {
                "interface": PRIMARY_INTERFACE,
                "download_mb": round(max(nd, 0), 2),
                "upload_mb": round(max(nu, 0), 2),
                "total_recv_gb": round(net_rx / (1024**3), 2),
                "total_sent_gb": round(net_tx / (1024**3), 2),
            },
            "interfaces": interfaces,
            "processes": processes,
        }

    # ── Docker container collection (parallel) ──

    def _collect_containers(self):
        if not self._docker:
            return []
        try:
            containers = self._docker.containers.list(all=True)

            def fetch_one(c):
                info = {
                    "name": c.name,
                    "image": c.image.tags[0] if c.image.tags else c.attrs.get("Config", {}).get("Image", "unknown"),
                    "state": c.attrs["State"]["Status"],
                    "status": c.status,
                    "cpu_percent": 0.0,
                    "memory_mb": 0.0,
                    "memory_percent": 0.0,
                }
                if c.status != "running":
                    return info
                try:
                    s = c.stats(stream=False)
                    # CPU
                    cd = s["cpu_stats"]["cpu_usage"]["total_usage"] - s["precpu_stats"]["cpu_usage"]["total_usage"]
                    sd = s["cpu_stats"]["system_cpu_usage"] - s["precpu_stats"]["system_cpu_usage"]
                    nc = s["cpu_stats"].get("online_cpus", 1)
                    info["cpu_percent"] = round((cd / sd) * nc * 100, 1) if sd > 0 else 0.0
                    # Memory (cgroup v2: subtract inactive_file; v1: subtract cache)
                    mem_stats = s["memory_stats"].get("stats", {})
                    usage_raw = s["memory_stats"].get("usage", 0)
                    cache = mem_stats.get("cache", 0) or mem_stats.get("inactive_file", 0)
                    mu = usage_raw - cache
                    ml = s["memory_stats"].get("limit", 1)
                    info["memory_mb"] = round(max(mu, 0) / (1024 * 1024), 1)
                    info["memory_percent"] = round(max(mu, 0) / ml * 100, 1) if ml > 0 else 0.0
                except Exception:
                    pass
                return info

            results = []
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = {pool.submit(fetch_one, c): c for c in containers}
                for f in as_completed(futures, timeout=20):
                    try:
                        results.append(f.result())
                    except Exception:
                        pass

            results.sort(key=lambda x: x["name"])
            return results
        except Exception as e:
            logger.error(f"Container collection error: {e}")
            return []
