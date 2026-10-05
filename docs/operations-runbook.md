# Operations runbook

Full-stack stop/start order for containerized deployments follows Red Hat [KCS 7124426](https://access.redhat.com/solutions/7124426). See [README - Maintenance](../README.md#maintenance) for playbook workflows.

When multiple AAP roles share one server, a single `manage_aap_service.yml` run on that host stops or starts every component wrapper service in platform order. Mesh drain/start runs once when the host has an `aap-instance-*` mesh instance service.

## Install

```bash
ansible-playbook -i inventory install_aap_service.yml -l exec1.example.com
```

Runs as root via Ansible `become`. Requires systemd user lingering for the AAP install user (enabled by AAP install).

## Drain only (keep receptor running)

```bash
ansible-playbook -i inventory manage_aap_service.yml \
  -e aap_state=stopped \
  -l exec1.example.com
```

On a single node:

```bash
sudo systemctl stop aap-instance-execution.service
```

## Stop local services only

After drain and once jobs have finished:

```bash
sudo systemctl stop aap-execution.service   # or aap-controller
```

Gateway, hub, or EDA via Ansible:

```bash
ansible-playbook -i inventory manage_aap_service.yml \
  -e aap_state=stopped \
  -l gateway1.example.com
```

Or on the node:

```bash
sudo systemctl stop aap-gateway.service   # or aap-eda or aap-hub
```

## Full maintenance stop (execution / controller)

```bash
ansible-playbook -i inventory manage_aap_service.yml \
  -e aap_state=stopped \
  -l exec1.example.com

sudo systemctl stop aap-execution.service
```

## Return to service

```bash
ansible-playbook -i inventory manage_aap_service.yml \
  -e aap_state=started \
  -l exec1.example.com
```

## Rolling Redis OS patch

Keep AAP up if required. Work **one** `[redis]` host at a time: replicas first, then primaries. Bring each host back before the next.

```bash
ansible -i inventory <redis-host> -b -a "systemctl stop aap-redis"
# patch / reboot
ansible -i inventory <redis-host> -b -a "systemctl start aap-redis"
```

On primary stop, `aap-redis` failovers only if a connected replica answers `PING`; otherwise stop fails and `redis-tcp` stays up. Do not use `-l redis` for rolling work (that can stop the whole group). Details: [README — aap-redis](../README.md).

Local DB (`postgresql`) is never started/stopped by wrappers — do that manually when needed.

## Validation

See [README - Validation](../README.md#validation) for `ansible -i inventory <group> -b -a "systemctl status ..."` and `podman ps -a` commands per component wrapper service. Colocated hosts may have several `aap-*.service` units on one server.
