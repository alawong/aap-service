# AAP Node Lifecycle Services

Ansible role and playbooks that install system-level wrapper services for containerized AAP 2.6 nodes. Playbooks run as **root** (`become`). System unit files live in `/etc/systemd/system/`; scripts in `/usr/local/bin/`. Component wrapper service scripts run `systemctl --user` as `ansible_user` from inventory. Wrapper units wait for `user@<ansible_user uid>.service` at boot so the user manager is ready before `systemctl --user start`.

A single host may run more than one AAP role (for example gateway and controller on the same server). The role installs one **component wrapper service** per node type on that host, derived from all matching installer inventory groups.

## Services


| Component       | Component wrapper service         | What it does                                                                             |
| --------------- | --------------------------------- | ---------------------------------------------------------------------------------------- |
| Controller mesh | `aap-instance-controller.service` | Enable/disable control node in mesh via controller API (`receptor_type=control`)           |
| Hybrid mesh     | `aap-instance-hybrid.service`     | Enable/disable hybrid node in mesh via controller API (`receptor_type=hybrid`, default)  |
| Execution mesh  | `aap-instance-execution.service`  | Enable/disable execution node in mesh via controller API (`execution_nodes` hosts only)  |
| Gateway         | `aap-gateway.service`             | Start/stop local gateway Podman units                                                    |
| Controller      | `aap-controller.service`          | Start/stop local controller Podman units                                                 |
| Execution       | `aap-execution.service`           | Start/stop local receptor unit                                                           |
| EDA             | `aap-eda.service`                 | Start/stop local EDA Podman units                                                        |
| Hub             | `aap-hub.service`                 | Start/stop local hub Podman units                                                        |
| Redis           | `aap-redis.service`               | Start/stop centralized `redis-tcp` (`[redis]` hosts, or first gateway when `[redis]` is empty) |


Mesh instance services (`aap-instance-*`) call the controller API only. Before enable/disable they wait for `GET /api/controller/v2/ping/` (retries on connection errors and HTTP 502/503/504). Component wrapper services (`aap-gateway`, `aap-controller`, and so on) manage local Podman user units only.

## Requirements

- AAP installer inventory (`automationgateway`, `automationcontroller`, `automationhub`, `execution_nodes`, `automationeda`, `redis`; not `database`)
- `ansible_user` must have root permissions on each AAP node
- On controller and execution hosts: `aap_token` (API token with superuser write permissions) and `aap_hostname` / `gateway_main_url` for mesh scripts



## Limitations

- `aap_node_types` lists every node type on a host from inventory group membership. Colocated hosts install multiple component wrapper services (for example `aap-gateway` and `aap-controller` on one server). Hybrid controller hosts (`receptor_type=hybrid`, the installer default) also get `aap-execution`; mesh uses a single `aap-instance-hybrid`.
- `aap-instance-*` does not wait for running jobs to finish. On controller and execution hosts, stop the mesh instance service first, wait for jobs to finish, then stop `aap-controller` or `aap-execution` (both on hybrid).
- Uninstall removes wrapper units and scripts only; it does not stop Podman containers or change mesh state.
- On colocated hosts, stop/start each `aap-*` unit in Red Hat platform order (gateway → eda → execution → controller → hub → redis on stop; reverse on start).
- `receptor_type` is assumed stable for the life of a deployment. Changing it later (for example hybrid to control) may leave a stale `aap-instance-*` unit on disk until addressed manually or by a future role enhancement.



## Playbooks



### Install

```bash
ansible-playbook -i inventory install_aap_service.yml
ansible-playbook -i inventory install_aap_service.yml -l exec1.example.com
```


| Variable                                         | Default                                     | Required   | Description                                                             |
| ------------------------------------------------ | ------------------------------------------- | ---------- | ----------------------------------------------------------------------- |
| `aap_token`                                      | —                                           | Mesh hosts | API token; encrypted to `/etc/credstore.encrypted/aap_token` on install |
| `aap_hostname`                                   | `gateway_main_url`                          | Mesh hosts | Gateway URL for controller API (`https://` added if omitted)            |
| `ansible_user`                                   | inventory                                   | Yes        | User that owns AAP Podman user units                                    |
| `aap_validate_certs`                             | `true` (`false` in install playbook)        | No         | TLS verification for mesh API calls                                     |
| `aap_instance_hostname`                          | `routable_hostname` or `inventory_hostname` | No         | Hostname of this instance in the controller mesh                        |
| `aap_skip_units`                                 | `[]`                                        | No         | Skip container units (e.g. optional `redis-unix`)                       |
| `aap_extra_start_units` / `aap_extra_stop_units` | `[]`                                        | No         | Extra units after/before profile lists                                  |
| `aap_instance_api_ready_timeout_seconds`         | `120`                                       | No         | Wait for `GET /api/controller/v2/ping/` before mesh enable/disable      |
| `aap_instance_api_ready_poll_seconds`            | `15`                                        | No         | Poll interval while waiting for controller API                          |
| `aap_instance_ready_timeout_seconds`             | `300`                                       | No         | Wait for `node_state=ready` after mesh enable                           |
| `aap_instance_ready_poll_seconds`                | `15`                                        | No         | Poll interval while waiting for ready                                   |
| `aap_redis_failover_timeout_seconds`             | `60`                                        | No         | Wait for primary demotion after `CLUSTER FAILOVER`                      |
| `aap_redis_failover_poll_seconds`                | `3`                                         | No         | Poll interval during Redis failover wait                                |
| `aap_redis_ready_timeout_seconds`                | `120`                                       | No         | Wait for Redis PING / cluster connected after start                     |
| `aap_redis_ready_poll_seconds`                   | `3`                                         | No         | Poll interval while waiting for Redis ready                             |




### Uninstall

```bash
ansible-playbook -i inventory uninstall_aap_service.yml
ansible-playbook -i inventory uninstall_aap_service.yml -l exec1.example.com
```

Removes wrapper units and scripts without running `ExecStop`. On Automation Mesh hosts, it also removes `/etc/credstore.encrypted/aap_token` which contains the encrypted API token.

## Maintenance

Follow [Red Hat KCS 7124426](https://access.redhat.com/solutions/7124426) for platform-wide stop/start order. Operate units with `systemctl` (wrappers are enabled at install and come back on reboot).

| Step | Target                   | Wrapper / notes                                                                       |
| ---- | ------------------------ | ------------------------------------------------------------------------------------- |
| 1    | `automationgateway`      | `aap-gateway` — `redis-unix` last when present (skipped on first gateway in standalone) |
| 2    | `automationeda`          | `aap-eda` — `redis-unix` last when present                                            |
| 3    | `execution_nodes`        | `aap-instance-execution` (drain), wait for jobs, then `aap-execution`                 |
| 4    | `automationcontroller`   | `aap-instance-hybrid` or `aap-instance-controller` (drain), wait for jobs, then `aap-controller` (and `aap-execution` on hybrid) |
| 5    | `automationhub`          | `aap-hub`                                                                             |
| 6    | `redis`                  | `aap-redis` — `redis-tcp` only; rolling OS patch one host at a time (see below)       |
| 7    | Controller with local DB | Manual only: `systemctl --user stop postgresql.service` (not managed by any `aap-*` wrapper) |

Restart in reverse order (step 7 → 1): component wrappers first, then `aap-instance-*` on mesh hosts.

**Rolling patch (execution node)**

```bash
sudo systemctl stop aap-instance-execution.service
# wait for jobs to finish
sudo systemctl stop aap-execution.service

# patch / reboot
dnf upgrade
# reboot — enabled units start automatically (instance after local wrappers + API ping)

# if not rebooting:
sudo systemctl start aap-execution.service
sudo systemctl start aap-instance-execution.service
```

Controller / hybrid hosts are the same pattern with `aap-instance-hybrid` or `aap-instance-controller`, then `aap-controller` (and `aap-execution` on hybrid).



### Risks


| Node / mesh                       | Playbook `stopped` alone? | Risk                                                                |
| --------------------------------- | ------------------------- | ------------------------------------------------------------------- |
| Instance (controller / execution / hybrid) | Yes              | Low - drains mesh; does not stop container services                 |
| Gateway                           | Yes                       | High - UI/API down; will break aap-instance-* service scripts       |
| Controller / execution (local)    | Manual step required      | High — breaks job execution; drain jobs first                       |
| Hub                               | Yes                       | Moderate - collection sync/publish and EE sync/publishing will fail |
| EDA                               | Yes                       | Low for controller jobs, High for active EDA rulebook activations   |
| Redis (`aap-redis`)               | Yes                       | High - gateway and EDA lose cache/queues                            |




## Validation

Check component wrapper service units with `-b` (root). Check containers as `ansible_user` (no `-b`).

```bash
# Example: gateway group or single host
ansible -i inventory automationgateway -b -a "systemctl status aap-gateway.service"
ansible -i inventory automationgateway -a "podman ps -a"
ansible -i inventory automationgateway -b -l gateway1.example.com -a "systemctl status aap-gateway.service"
```


| Group                  | Component wrapper service(s) to check                       |
| ---------------------- | ----------------------------------------------------------- |
| `automationgateway`    | `aap-gateway.service`                                       |
| `automationcontroller` | `aap-controller.service`, `aap-instance-hybrid.service` (or `aap-instance-controller` when `receptor_type=control`); hybrid hosts also have `aap-execution.service` |
| `execution_nodes`      | `aap-execution.service`, `aap-instance-execution.service`   |
| `automationhub`        | `aap-hub.service`                                           |
| `automationeda`        | `aap-eda.service`                                           |
| `redis`                | `aap-redis.service`                                         |


`systemctl status` exits non-zero when a unit is inactive; Ansible may report that as failed even when the output is useful.

## Configuration



### Inventory groups and Redis

`aap_node_types` is derived from all matching installer groups on the host. One component wrapper service is installed per type. Hosts in multiple groups get multiple entries (no duplicates).

| Inventory group        | Node type | Component wrapper service(s)                |
| ---------------------- | -------------- | ------------------------------------------- |
| `automationcontroller` | `controller`   | `aap-controller`, `aap-instance-hybrid` (default) or `aap-instance-controller` (`receptor_type=control`) |
| `automationcontroller` | `execution`    | `aap-execution` (hybrid hosts only; `receptor` managed by `aap-controller`) |
| `automationgateway`    | `gateway`      | `aap-gateway`                               |
| `automationhub`        | `hub`          | `aap-hub`                                   |
| `execution_nodes`      | `execution`    | `aap-execution`, `aap-instance-execution`   |
| `automationeda`        | `eda`          | `aap-eda`                                   |
| `redis`                | `redis`        | `aap-redis`                                 |

**Redis units**

| Unit        | Managed by                         | Notes |
| ----------- | ---------------------------------- | ----- |
| `redis-tcp` | `aap-redis` only                   | Centralized Redis; hosts in `[redis]` |
| `redis-unix` | `aap-gateway`, `aap-controller`, `aap-eda`, `aap-hub` | Local Redis; optional when unit file is absent |

- Standalone (empty or missing `[redis]` group): first host in `automationgateway` installs `aap-redis` automatically and skips `redis-unix` in `aap-gateway`.
- Controller: `redis-unix` via `aap-controller`. If the host is also in `[redis]`, `aap-redis` manages `redis-tcp` separately.
- Execution nodes and database hosts are not Redis hosts.

**`aap-redis` start/stop behaviour** (assumes `redis_mode=cluster`)

| Action | Replica | Primary |
| ------ | ------- | ------- |
| `stop` | Stop `redis-tcp` | Preflight: require a cluster-`connected` replica that answers `PING`; then `CLUSTER FAILOVER` to each such replica until demoted, then stop |
| `start` | Start `redis-tcp`, wait for `PING` and `CLUSTER NODES` `myself` with link `connected` and no `fail` flag | Same |

Failover/ready waits use role defaults: `aap_redis_failover_timeout_seconds` (60), `aap_redis_failover_poll_seconds` (3), `aap_redis_ready_timeout_seconds` (120), `aap_redis_ready_poll_seconds` (3). Before failover, `aap-redis` requires at least one replica that is `connected` in `CLUSTER REPLICAS` and answers TLS `PING`. If `CLUSTER FAILOVER` or the demotion wait fails for one replica, it tries the next preflight-passed replica. If none are usable or all attempts fail, stop fails and `redis-tcp` is left running. Transient `ROLE` failures during the wait are retried until the failover timeout. `CLUSTER NODES` addresses look like `ip:6379@16379`; failover targets the Redis client port (`6379`), not the cluster bus port (`16379`). `podman exec` / `redis-cli` run as `ansible_user` even though the wrapper unit is root. `redis-cli` always uses TLS with the container-mounted `server.crt` / `server.key`, matching AAP’s TLS-only Redis listener. Standalone Redis is out of scope for `aap-redis`.

**Rolling Redis OS patch** (AAP may stay up; one host at a time)

1. Stop / patch / start each **replica** first (`systemctl stop aap-redis` on that host only).
2. Confirm the replica is back (`active`, cluster connected, `ROLE` slave) before the next host.
3. Then stop / patch / start each **primary** the same way. Preflight requires its replica to be connected and reachable; otherwise stop refuses and leaves `redis-tcp` running.
4. Do not stop the whole `[redis]` group at once for rolling patch — work one host at a time.

```bash
ansible -i inventory <redis-host> -b -a "systemctl stop aap-redis"
# patch / reboot as required
ansible -i inventory <redis-host> -b -a "systemctl start aap-redis"
ansible -i inventory <redis-host> -b -a "systemctl status aap-redis --no-pager"
```

After failover, which node is primary for a shard may change; restoring a preferred topology is a separate ops step if needed.

### Colocated hosts

Installer inventory can place multiple AAP roles on one server (for example `automationgateway` and `automationcontroller` on the same host). The role:

- Builds `aap_node_types` from every matching group on that host.
- Installs one component wrapper service (`aap-<node_type>`) per type, plus at most one mesh instance service (`aap-instance-*`) when applicable.
- On hybrid controller hosts, installs `aap-controller` and `aap-execution` together; `aap-execution` does not manage `receptor` because `aap-controller` already does.
- Rejects inventory where a host is in both `automationcontroller` and `execution_nodes` (each host should have one mesh role).

`receptor_type` on `[automationcontroller]` hosts (`hybrid` or `control`) selects the mesh instance service name and whether `execution` is included in `aap_node_types`. It is expected to remain fixed after install.

Set `aap_token` in `install_aap_service.yml` (vault or `-e`). `aap_validate_certs: false` is set in that playbook when the gateway certificate does not match inventory hostnames.

All defaults: `roles/aap_service/defaults/main.yml`.

### API Token Usage

1. Install - `systemd-creds encrypt` to `/etc/credstore.encrypted/aap_token`
2. `aap-instance-*.service` - encrypted token file is loaded into the systemd binary using `LoadCredentialEncrypted` with the `PrivateMounts=yes` option
3. Manual mesh start/stop - Running `systemctl start|stop aap-instance-*.service` will decrypt the API token using systemd-creds and load it into the systemd binary on start/stop. API token is never stored in plaintext.

Rotate: update the `aap_token` variable within `install_aap_service.yml` and re-run the playbook.

## Repository Layout

```
install_aap_service.yml
uninstall_aap_service.yml
roles/
  aap_service/
docs/
  systemd/              # reference units (deployed from role templates)
  scripts/aap-redis.py  # example render of aap-redis (review only)
  architecture.md
  operations-runbook.md
```



## References

- [Red Hat KCS 7124426 — containerized AAP stop/start order](https://access.redhat.com/solutions/7124426)
- [systemd credentials](https://systemd.io/CREDENTIALS/)
- [AAP 2.6 containerized installation](https://docs.redhat.com/en/documentation/red_hat_ansible_automation_platform/2.6/html/containerized_installation)
- [Architecture](docs/architecture.md)
- [Operations runbook](docs/operations-runbook.md)

