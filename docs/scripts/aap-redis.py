#!/usr/bin/env python3
# Example render of /usr/local/bin/aap-redis
# Sources: roles/aap_service/templates/aap-node.py.j2 + aap-redis.py.j2
# Sample values: ansible_user=ec2-user; role-default failover/ready timeouts
# Review only — install_aap_service.yml deploys the live script.

import fnmatch
import json
import logging
import os
import pwd
import subprocess
import sys

import shlex
import time


_CONFIG = json.loads("""{"node_type": "redis", "user": "ec2-user", "start_units": ["redis-tcp"], "stop_units": ["redis-tcp"], "optional_units": [], "discover_patterns": [], "skip_units": []}""")
NODE_TYPE = _CONFIG["node_type"]
SERVICE_NAME = "aap-%s" % NODE_TYPE
AAP_USER = _CONFIG["user"]
START_UNITS = _CONFIG["start_units"]
STOP_UNITS = _CONFIG["stop_units"]
OPTIONAL_UNITS = _CONFIG["optional_units"]
DISCOVER_PATTERNS = _CONFIG["discover_patterns"]
SKIP_UNITS = _CONFIG["skip_units"]
EXECUTION_PLANE = False
LOG = logging.getLogger(SERVICE_NAME)
VALID_ACTIONS = ("start", "stop")

REDIS_CONTAINER = "redis-tcp"
REDIS_FAILOVER_TIMEOUT = 60
REDIS_FAILOVER_POLL = 3
REDIS_READY_TIMEOUT = 120
REDIS_READY_POLL = 3
# Paths inside the redis-tcp container (AAP mounts; TLS-only listener).
REDIS_TLS_CERT = "/var/lib/redis/server.crt"
REDIS_TLS_KEY = "/var/lib/redis/server.key"


def setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def parse_action():
    if len(sys.argv) != 2 or sys.argv[1] not in VALID_ACTIONS:
        print("Usage: %s start|stop" % sys.argv[0], file=sys.stderr)
        sys.exit(2)

    return sys.argv[1]


def aap_context():
    pw = pwd.getpwnam(AAP_USER)
    env = os.environ.copy()
    env["XDG_RUNTIME_DIR"] = "/run/user/%s" % pw.pw_uid
    env["HOME"] = pw.pw_dir
    env["USER"] = AAP_USER

    if EXECUTION_PLANE:
        env["CONTAINER_HOST"] = "unix:///run/user/%s/podman/podman.sock" % pw.pw_uid
        env["CONTAINERS_STORAGE_CONF"] = os.path.join(pw.pw_dir, "aap/containers/storage.conf")

    return pw.pw_uid, pw.pw_dir, env


def systemctl(args, check=True):
    # Wrapper may run as root; Podman units belong to AAP_USER's user manager.
    uid, _, env = aap_context()
    cmd = ["systemctl", "--user"] + args
    LOG.debug("Running as %s: %s", AAP_USER, " ".join(cmd))

    return subprocess.run(
        cmd, env=env, user=uid, group=uid, capture_output=True, text=True, check=check
    )


def unit_path(name):
    _, home, _ = aap_context()
    unit = name if name.endswith(".service") else name + ".service"
    return os.path.join(home, ".config/systemd/user", unit)


def unit_exists(name):
    return os.path.exists(unit_path(name))


def discover_units():
    _, home, _ = aap_context()
    systemd_dir = os.path.join(home, ".config/systemd/user")

    if not os.path.isdir(systemd_dir):
        return []

    found = []

    for filename in sorted(os.listdir(systemd_dir)):
        if not filename.endswith(".service"):
            continue
        stem = filename[:-8]
        for pattern in DISCOVER_PATTERNS:
            if fnmatch.fnmatch(stem, pattern):
                found.append(stem)
                break

    return found


def resolve_units(ordered):
    units = []
    seen = set()

    for unit in ordered:
        if unit in SKIP_UNITS or unit in seen:
            continue
        if unit in OPTIONAL_UNITS and not unit_exists(unit):
            LOG.info("Optional unit %s not present; skipping", unit)
            continue
        if not unit_exists(unit):
            raise FileNotFoundError("Required systemd unit not found: %s.service" % unit)
        units.append(unit)
        seen.add(unit)

    for unit in discover_units():
        if unit not in seen and unit not in SKIP_UNITS:
            units.append(unit)
            seen.add(unit)

    return units


def start_units():
    for unit in resolve_units(START_UNITS):
        LOG.info("Starting %s", unit)
        systemctl(["start", unit])


def stop_units():
    workers = discover_units() if DISCOVER_PATTERNS else []
    base = resolve_units(STOP_UNITS)
    stop_list = workers + [u for u in base if u not in workers]
    seen = set()

    for unit in stop_list:
        if unit in seen:
            continue
        seen.add(unit)
        LOG.info("Stopping %s", unit)
        systemctl(["stop", unit], check=False)

    failed = []

    for unit in stop_list:
        result = systemctl(["is-active", unit], check=False)
        if result.stdout.strip() not in ("inactive", "failed", "unknown"):
            failed.append(unit)

    if failed:
        raise RuntimeError("Failed to stop systemd units: %s" % ", ".join(failed))


def redis_cli(command, host=None, port=None):
    """Run redis-cli inside redis-tcp as ansible_user (TLS).

    Returns CompletedProcess. Pass host (and optional port, default 6379) to
    target another cluster node on the Redis client port — not the cluster bus
    port (@16379 in CLUSTER NODES).
    """
    uid, _, env = aap_context()

    cmd = [
        "podman",
        "exec",
        REDIS_CONTAINER,
        "redis-cli",
        "--tls",
        "--cert",
        REDIS_TLS_CERT,
        "--key",
        REDIS_TLS_KEY,
    ]
    if host:
        cmd.extend(["-h", host, "-p", str(6379 if port is None else port)])
    cmd.extend(shlex.split(command))
    LOG.debug("Running as %s: %s", AAP_USER, " ".join(cmd))

    try:
        return subprocess.run(
            cmd, env=env, user=uid, group=uid, capture_output=True, text=True, check=True
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(
            "redis-cli %r failed (rc=%s)%s"
            % (command, exc.returncode, (": " + detail) if detail else "")
        ) from None


def get_available_replicas():
    """Replicas that are cluster-connected and answer TLS PING."""
    my_id = redis_cli("CLUSTER MYID").stdout.strip()
    replicas = []

    for line in redis_cli("CLUSTER REPLICAS %s" % my_id).stdout.splitlines():
        fields = line.split()
        if len(fields) < 8:
            LOG.debug("Skipping CLUSTER REPLICAS line (too few fields): %s", line)
            continue
        if "fail" in fields[2] or "noaddr" in fields[2]:
            LOG.debug("Skipping replica %s (flags=%s)", fields[1], fields[2])
            continue
        if fields[7] != "connected":
            LOG.debug(
                "Skipping replica %s (link-state=%s)", fields[1], fields[7]
            )
            continue

        addr = fields[1]
        if addr == ":0@0" or not addr or addr.startswith(":"):
            LOG.debug("Skipping replica with unusable address: %s", addr)
            continue

        # ip:6379@16379 — use client port 6379, ignore cluster bus port
        ip_port = addr.split("@", 1)[0]
        if "," in ip_port:
            ip_port = ip_port.split(",")[-1]
        if ":" not in ip_port:
            LOG.debug("Skipping replica address without port: %s", addr)
            continue

        ip, port_s = ip_port.rsplit(":", 1)
        if not (ip and port_s.isdigit()):
            LOG.debug("Skipping replica address parse failure: %s", addr)
            continue
        port = int(port_s)

        try:
            if redis_cli("PING", host=ip, port=port).stdout.strip().upper() != "PONG":
                LOG.warning("Replica %s:%s connected but PING failed; skipping", ip, port)
                continue
        except RuntimeError as exc:
            LOG.warning("Replica %s:%s not available (PING): %s", ip, port, exc)
            continue

        replicas.append((ip, port))

    return replicas


def is_connected():
    """True if CLUSTER NODES shows myself connected with no fail flag."""
    try:
        result = redis_cli("CLUSTER NODES")
    except RuntimeError as exc:
        LOG.info("Redis cluster not connected: %s", exc)
        return False

    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) < 8 or "myself" not in fields[2]:
            continue
        flags = fields[2]
        if "fail" in flags:
            LOG.info("Redis cluster not connected: myself has fail flag: %s", flags)
            return False
        if fields[7] != "connected":
            LOG.info("Redis cluster not connected: myself link-state is %s", fields[7])
            return False
        return True

    LOG.info("Redis cluster not connected: myself not found in CLUSTER NODES")
    return False


def is_active():
    """True if the redis-tcp unit file exists and the unit is active/activating."""
    if not unit_exists(REDIS_CONTAINER):
        return False

    active = systemctl(["is-active", REDIS_CONTAINER], check=False).stdout.strip()
    return active in ("active", "activating")


def is_primary():
    """True if local redis-tcp ROLE is master."""
    text = redis_cli("ROLE").stdout.strip()
    if not text:
        raise RuntimeError("Empty ROLE response from local redis-tcp")

    role = text.splitlines()[0].strip().lower()
    if role not in ("master", "slave"):
        raise RuntimeError("Unexpected ROLE from local redis-tcp: %s" % role)
    return role == "master"


def failover_replica():
    """Fail over this primary to a replica; try each available replica until demoted."""
    if not is_primary():
        LOG.info("Local redis-tcp is no longer primary; skipping CLUSTER FAILOVER")
        return

    replicas = get_available_replicas()
    if not replicas:
        raise RuntimeError(
            "Redis node is primary but has no available connected replica for CLUSTER FAILOVER"
        )

    LOG.info("Failover targets: %s", ", ".join("%s:%s" % r for r in replicas))
    failures = []
    for ip, port in replicas:
        LOG.info("Failing over Redis primary to replica %s:%s", ip, port)
        try:
            redis_cli("CLUSTER FAILOVER", host=ip, port=port)
        except RuntimeError as exc:
            LOG.warning("CLUSTER FAILOVER to %s:%s failed: %s", ip, port, exc)
            failures.append("%s:%s: %s" % (ip, port, exc))
            continue

        deadline = time.time() + REDIS_FAILOVER_TIMEOUT
        while time.time() < deadline:
            try:
                if not is_primary():
                    LOG.info("Failover complete: local demoted (target was %s:%s)", ip, port)
                    return
            except RuntimeError as exc:
                LOG.debug("Waiting for failover: local ROLE check failed: %s", exc)
                time.sleep(REDIS_FAILOVER_POLL)
                continue

            LOG.debug("Waiting for failover: still primary (target %s:%s)", ip, port)
            time.sleep(REDIS_FAILOVER_POLL)

        msg = "timed out after %ss waiting for failover to %s:%s" % (
            REDIS_FAILOVER_TIMEOUT,
            ip,
            port,
        )
        LOG.warning(msg)
        failures.append(msg)

    raise RuntimeError(
        "Redis failover failed after trying %s replica(s): %s"
        % (len(replicas), "; ".join(failures))
    )


def wait_until_connected():
    """After start: wait until PING succeeds and this cluster node is connected."""
    LOG.info(
        "Waiting up to %ss for redis-tcp PING and cluster connected",
        REDIS_READY_TIMEOUT,
    )
    deadline = time.time() + REDIS_READY_TIMEOUT
    last = "PING not attempted yet"

    while time.time() < deadline:
        try:
            ping = redis_cli("PING")
        except RuntimeError as exc:
            last = str(exc)
            LOG.debug("Waiting for redis-tcp ready: %s", last)
            time.sleep(REDIS_READY_POLL)
            continue

        if ping.stdout.strip().upper() != "PONG":
            last = ping.stdout.strip() or "PING did not return PONG"
            LOG.debug("Waiting for redis-tcp ready: %s", last)
            time.sleep(REDIS_READY_POLL)
            continue

        if is_connected():
            LOG.info("Redis cluster node is connected")
            return

        last = "PING ok; cluster node not connected"
        # is_connected() already logged the reason at INFO
        time.sleep(REDIS_READY_POLL)

    raise RuntimeError(
        "Timed out after %ss waiting for redis-tcp to become ready/connected. "
        "Last status: %s" % (REDIS_READY_TIMEOUT, last)
    )


def main():
    setup_logging()
    try:
        action = parse_action()

        if action == "start":
            start_units()

            wait_until_connected()

            print("started")
            return 0

        if action == "stop":

            if not is_active():
                LOG.info("redis-tcp not active; skipping failover")
            elif not is_primary():
                LOG.info("redis-tcp is not primary; skipping failover")
            else:
                failover_replica()

            stop_units()
            print("stopped")
            return 0

        return 1
    except Exception as exc:
        LOG.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
