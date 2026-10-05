# Architecture

## Services

```text
     aap-instance-hybrid.service       aap-instance-controller.service
     aap-instance-execution.service         (/etc/systemd/system)
         (/etc/systemd/system)              (mesh hosts only)
              (automationcontroller)              (execution_nodes)
                            │
                            ▼
              PATCH /api/controller/v2/instances/
              enabled: false | enabled: true
         LoadCredentialEncrypted - /etc/credstore.encrypted/aap_token


     aap-gateway | aap-controller | aap-execution | aap-eda | aap-hub | aap-redis
              (system units, run as root)
                            │
                            ▼
              systemctl --user stop/start as ansible_user (AAP container units)
              receptor, controller-*, gateway, eda-*, hub-*, etc.
```

**aap-instance-*** mesh instance services never touch local container units. Component wrapper services never call the controller API.

Lifecycle **wrapper** units are system services in `/etc/systemd/system/`. AAP **container** units remain user services under `~/.config/systemd/user/` (installed by the AAP installer).

Playbooks and all wrapper units run as **root** (`become`). Component wrapper service scripts embed `ansible_user` from inventory and delegate `systemctl --user` to that user's Podman units.

## Colocated hosts

A single server may belong to more than one installer inventory group. The role derives `aap_node_types` from all groups on that host and installs one component wrapper service per type. Examples:

| Host membership | Component wrapper services | Mesh instance service |
| --------------- | ------------- | ------------ |
| `automationcontroller` only (`receptor_type=hybrid`) | `aap-controller`, `aap-execution` | `aap-instance-hybrid` |
| `automationcontroller` only (`receptor_type=control`) | `aap-controller` | `aap-instance-controller` |
| `execution_nodes` | `aap-execution` | `aap-instance-execution` |
| `automationgateway` + `automationcontroller` | `aap-gateway`, `aap-controller`, … | per controller / execution rules above |

`manage_aap_service.yml` applies Red Hat platform stop/start order (`aap_manage_order`) across every component wrapper service on the host in one run. Mesh drain/start runs once before and after that loop when `aap_mesh_instance_type` is set.

Inventory validation fails if a host is in both `automationcontroller` and `execution_nodes`.

## API credentials

`aap-instance-*` services use system-scoped **LoadCredentialEncrypted** (`/etc/credstore.encrypted/aap_token`) with `PrivateMounts=yes`. Systemd decrypts at activation and passes the token via `$CREDENTIALS_DIRECTORY/aap_token`. The install playbook encrypts with `systemd-creds encrypt` (not `--user`).

## Stop order

When `aap_state=stopped` on mesh hosts (`automationcontroller` / `execution_nodes`):

1. `aap-instance-hybrid`, `aap-instance-controller`, or `aap-instance-execution` — disable in controller (playbook)
2. `aap-controller` / `aap-execution` — stop local units (manual, after jobs complete; both on hybrid)

When `aap_state=stopped` on gateway, hub, EDA, or dedicated Redis hosts, the playbook stops the component wrapper service only.

On colocated hosts, component wrapper services stop in platform order (gateway → eda → execution → controller → hub → redis).

## Start order

When `aap_state=started` on mesh hosts:

1. `aap-<node_type>` — start local units (reverse platform order on colocated hosts)
2. `aap-instance-*` — enable in controller and wait until `node_state` is `ready`

Gateway, hub, EDA, and dedicated Redis hosts only run the component wrapper service task.

## Scripts

| Script | Usage |
|--------|-------|
| `/usr/local/bin/aap-instance-hybrid` | `start` enable · `stop` disable |
| `/usr/local/bin/aap-instance-controller` | `start` enable · `stop` disable |
| `/usr/local/bin/aap-instance-execution` | `start` enable · `stop` disable |
| `/usr/local/bin/aap-gateway` | `start` · `stop` |
| `/usr/local/bin/aap-controller` | `start` · `stop` |
| `/usr/local/bin/aap-execution` | `start` · `stop` |
| `/usr/local/bin/aap-eda` | `start` · `stop` |
| `/usr/local/bin/aap-hub` | `start` · `stop` |
| `/usr/local/bin/aap-redis` | `start` (wait until PING + cluster connected) · `stop` (primary: preflight + `CLUSTER FAILOVER`, then stop `redis-tcp`) |

System unit example (`/etc/systemd/system/aap-execution.service`):

```ini
ExecStart=/usr/local/bin/aap-execution start
ExecStop=/usr/local/bin/aap-execution stop
WantedBy=multi-user.target
```

The script runs `systemctl --user` as `ansible_user` from inventory (e.g. `ec2-user`).

## Limitations

Install deploys one component wrapper service per entry in `aap_node_types` (from all matching inventory groups on the host). Hybrid controller hosts (`receptor_type=hybrid`, the installer default) get both `controller` and `execution` in `aap_node_types` but a single mesh instance service (`aap-instance-hybrid`). Control-only controller hosts get `aap-instance-controller`. When `[redis]` is empty, the first `automationgateway` host also gets `aap-redis`. `aap-redis` manages `redis-tcp` only. Component wrapper services manage `redis-unix` where listed (optional when absent). The first `automationgateway` host skips `redis-unix` for standalone topologies. On hybrid hosts, `aap-execution` skips `receptor` because `aap-controller` already manages it. Mesh disable does not wait for long-running jobs to finish. See [Limitations](../README.md#limitations) in the README.

`receptor_type` is treated as stable after install. Changing it without reinstalling may leave an obsolete `aap-instance-*` script or unit on the host (not yet handled automatically).

## Reference systemd units

Static reference copies are in `docs/systemd/`. The install role deploys from `roles/aap_service/templates/aap-instance.service.j2` and `aap-node.service.j2`.

## Node profiles

Unit lists for component wrapper services are in `aap_services` in role defaults. Stop order uses `aap_stop_services` when defined, otherwise `reverse(start)`. `postgresql` is not managed by any wrapper — start and stop it manually when using a local DB. `redis-tcp` is only in the `redis` profile; on primary stop, `aap-redis` failovers only when a cluster-`connected` replica answers TLS `PING`, otherwise stop fails and leaves `redis-tcp` running. `redis-unix` is optional on gateway, controller, eda, and hub. **aap-instance-*** services install once per host as `aap_mesh_instance_type` (`hybrid`, `controller`, or `execution`), derived from inventory group and `receptor_type`. See [README — aap-redis](../README.md) for rolling OS patch guidance (one host at a time).
