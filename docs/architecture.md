# Architecture

## Services

```text
     aap-instance-controller.service     aap-instance-execution.service
         (/etc/systemd/system)              (/etc/systemd/system)
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

**aap-instance-*** services never touch local container units. Component wrappers never call the controller API.

Lifecycle **wrapper** units are system services in `/etc/systemd/system/`. AAP **container** units remain user services under `~/.config/systemd/user/` (installed by the AAP installer).

Playbooks and all wrapper units run as **root** (`become`). Component scripts embed `ansible_user` from inventory and delegate `systemctl --user` to that user's Podman units.

## API credentials

`aap-instance-*` services use system-scoped **LoadCredentialEncrypted** (`/etc/credstore.encrypted/aap_token`) with `PrivateMounts=yes`. Systemd decrypts at activation and passes the token via `$CREDENTIALS_DIRECTORY/aap_token`. The install playbook encrypts with `systemd-creds encrypt` (not `--user`).

## Stop order

When `aap_state=stopped` on controller or execution hosts (`automationcontroller` / `execution_nodes` groups):

1. `aap-instance-controller` / `aap-instance-execution` - disable in controller (playbook)
2. `aap-controller` / `aap-execution` - stop local units (manual, after jobs complete)

When `aap_state=stopped` on gateway, hub, EDA, or dedicated Redis hosts, the playbook stops the component service only.

## Start order

When `aap_state=started` on controller or execution hosts:

1. `aap-{{ aap_node_type }}` - start local units
2. `aap-instance-controller` / `aap-instance-execution` - enable in controller and wait until `node_state` is `ready`

Gateway, hub, EDA, and dedicated Redis hosts only run the component service task.

## Scripts

| Script | Usage |
|--------|-------|
| `/usr/local/bin/aap-instance-controller` | `start` enable · `stop` disable |
| `/usr/local/bin/aap-instance-execution` | `start` enable · `stop` disable |
| `/usr/local/bin/aap-gateway` | `start` · `stop` |
| `/usr/local/bin/aap-controller` | `start` · `stop` |
| `/usr/local/bin/aap-execution` | `start` · `stop` |
| `/usr/local/bin/aap-eda` | `start` · `stop` |
| `/usr/local/bin/aap-hub` | `start` · `stop` |
| `/usr/local/bin/aap-redis` | `start` · `stop` |

System unit example (`/etc/systemd/system/aap-execution.service`):

```ini
ExecStart=/usr/local/bin/aap-execution start
ExecStop=/usr/local/bin/aap-execution stop
WantedBy=multi-user.target
```

The script runs `systemctl --user` as `ansible_user` from inventory (e.g. `ec2-user`).

## Limitations

Install deploys one component wrapper per host (`aap_node_type` precedence: controller - gateway - hub - execution - eda - redis). Dedicated `[redis]` hosts install `aap-redis`. Colocated Redis (`redis-unix`, `redis-tcp`) starts first and stops last on any component host where those unit files exist. Instance mesh services (`aap-instance-*`) install only when `aap_node_type` is `controller` or `execution`. Mesh disable does not wait for long-running jobs to finish. See [Limitations](../README.md#limitations) in the README.

## Reference systemd units

Static reference copies are in `docs/systemd/`. The install role deploys from `roles/aap_service/templates/aap-instance.service.j2` and `aap-component.service.j2`.

## Node profiles

Unit lists for component services are in `aap_services` in role defaults. Stop order uses `aap_stop_services` when defined, otherwise `reverse(start)`. Centralized Redis (`redis-unix`, `redis-tcp`) starts first and stops last for gateway, EDA, and dedicated Redis hosts. **aap-instance-*** services are installed only when `aap_node_type` is in `aap_mesh_node_types` (`controller`, `execution`).
