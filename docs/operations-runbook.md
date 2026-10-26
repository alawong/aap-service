# Operations runbook

Full-stack stop/start order for containerized deployments follows Red Hat [KCS 7124426](https://access.redhat.com/solutions/7124426). See [README - Maintenance](../README.md#maintenance).

On colocated hosts, stop or start each `aap-*` wrapper in platform order. Mesh drain/start is a separate `aap-instance-*` unit.

## Install

```bash
ansible-playbook -i inventory install_aap_service.yml -l exec1.example.com
```

Runs as root via Ansible `become`. Requires systemd user lingering for the AAP install user (enabled by AAP install).

## Drain only (keep receptor running)

```bash
sudo systemctl stop aap-instance-execution.service
# or aap-instance-hybrid / aap-instance-controller
```

## Stop local services only

After drain and once jobs have finished:

```bash
sudo systemctl stop aap-execution.service   # or aap-controller
```

Gateway, hub, or EDA:

```bash
sudo systemctl stop aap-gateway.service   # or aap-eda or aap-hub
```

## Full maintenance stop (execution / controller)

```bash
sudo systemctl stop aap-instance-execution.service
# wait for jobs to finish
sudo systemctl stop aap-execution.service
# patch / reboot — enabled units return on boot
```

## Return to service (no reboot)

```bash
sudo systemctl start aap-execution.service
sudo systemctl start aap-instance-execution.service
```

## Rolling Redis OS patch

Keep AAP up if required. Work **one** `[redis]` host at a time: replicas first, then primaries. Bring each host back before the next.

```bash
ansible -i inventory <redis-host> -b -a "systemctl stop aap-redis"
# patch / reboot
ansible -i inventory <redis-host> -b -a "systemctl start aap-redis"
```

On primary stop, `aap-redis` failovers only if a connected replica answers `PING`; otherwise stop fails and `redis-tcp` stays up. Do not stop the whole `[redis]` group at once for rolling work. Details: [README — aap-redis](../README.md).

Local DB (`postgresql`) is never started/stopped by wrappers — do that manually when needed.

## Validation

See [README - Validation](../README.md#validation) for `ansible -i inventory <group> -b -a "systemctl status ..."` and `podman ps -a` commands per component wrapper service. Colocated hosts may have several `aap-*.service` units on one server.
