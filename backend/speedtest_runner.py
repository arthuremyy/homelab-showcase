"""
SpeedTest runner – lancement manuel uniquement.
Deux cibles : host (connexion directe) et vpn (via container gluetun).
"""
import subprocess
import json
import threading
import time
import logging

logger = logging.getLogger("speedtest")

SPEEDTEST_CMD = ["speedtest", "--format=json", "--accept-license", "--accept-gdpr"]

# Commande d'installation dans gluetun (Alpine/busybox)
GLUETUN_INSTALL = (
    "cd /tmp && "
    "wget -q https://install.speedtest.net/app/cli/ookla-speedtest-1.2.0-linux-x86_64.tgz -O st.tgz && "
    "tar xzf st.tgz && "
    "mv speedtest /usr/local/bin/ && "
    "rm -f st.tgz speedtest.md NOTICE"
)


class SpeedTestRunner:
    def __init__(self, docker_client=None):
        self._lock = threading.Lock()
        self._docker = docker_client
        self._results = {
            "host": {"status": "idle", "data": None, "error": None, "timestamp": None},
            "vpn":  {"status": "idle", "data": None, "error": None, "timestamp": None},
        }

    def get_status(self):
        with self._lock:
            return {k: {**v} for k, v in self._results.items()}

    def run_test(self, target: str) -> dict:
        """Demarre un speedtest. Retourne erreur si deja en cours."""
        if target not in ("host", "vpn"):
            return {"ok": False, "error": "Cible invalide (host ou vpn)"}

        with self._lock:
            if self._results[target]["status"] == "running":
                return {"ok": False, "error": "Test deja en cours"}
            self._results[target]["status"] = "running"
            self._results[target]["error"] = None

        threading.Thread(target=self._execute, args=(target,), daemon=True).start()
        return {"ok": True}

    # ── Execution en arriere-plan ──

    def _execute(self, target: str):
        try:
            result = self._run_host() if target == "host" else self._run_vpn()
            with self._lock:
                self._results[target]["status"] = "done"
                self._results[target]["data"] = result
                self._results[target]["timestamp"] = int(time.time())
            logger.info(f"Speedtest {target} OK: {result['download']} Mbps down, {result['upload']} Mbps up, {result['ping']} ms")
        except Exception as e:
            logger.error(f"Speedtest {target} error: {e}")
            with self._lock:
                self._results[target]["status"] = "error"
                self._results[target]["error"] = str(e)
                self._results[target]["timestamp"] = int(time.time())

    def _run_host(self):
        """Speedtest depuis le container dashboard-api (connexion directe)."""
        proc = subprocess.run(SPEEDTEST_CMD, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "speedtest a echoue")
        return self._parse(json.loads(proc.stdout))

    def _run_vpn(self):
        """Speedtest via exec dans le container gluetun (tunnel VPN)."""
        if not self._docker:
            raise RuntimeError("Docker non disponible")

        try:
            ct = self._docker.containers.get("gluetun")
        except Exception:
            raise RuntimeError("Container gluetun introuvable")

        if ct.status != "running":
            raise RuntimeError("Gluetun n'est pas demarre")

        # Installer speedtest si absent
        chk = ct.exec_run("ls /usr/local/bin/speedtest")
        if chk.exit_code != 0:
            logger.info("Installation de speedtest dans gluetun...")
            res = ct.exec_run(["sh", "-c", GLUETUN_INSTALL], demux=True)
            if res.exit_code != 0:
                stderr = res.output[1].decode(errors="replace") if res.output[1] else ""
                raise RuntimeError(f"Installation echouee dans gluetun: {stderr}")
            logger.info("Speedtest installe dans gluetun")

        # Lancer le test
        res = ct.exec_run(SPEEDTEST_CMD, demux=True)
        if res.exit_code != 0:
            stderr = res.output[1].decode(errors="replace") if res.output[1] else ""
            raise RuntimeError(f"Speedtest VPN echoue: {stderr}")

        stdout = res.output[0].decode() if res.output[0] else ""
        return self._parse(json.loads(stdout))

    @staticmethod
    def _parse(raw: dict) -> dict:
        """Extrait les metriques utiles du JSON Ookla."""
        return {
            "ping": round(raw["ping"]["latency"], 1),
            "download": round(raw["download"]["bandwidth"] * 8 / 1e6, 2),
            "upload": round(raw["upload"]["bandwidth"] * 8 / 1e6, 2),
            "server": raw["server"]["name"],
            "location": raw["server"]["location"],
            "isp": raw.get("isp", ""),
            "ip": raw.get("interface", {}).get("externalIp", ""),
        }
