# AAP Node Lifecycle Services

Repository that contains roles that install and manage per-component system services for containerized AAP 2.6 nodes. Playbooks and wrapper services run as **root** (`become`); service files live in `/etc/systemd/system/`, binaries in `/usr/local/bin/`. Component scripts delegate `systemctl --user` to `ansible_user` from inventory for user-scoped Podman container services.


| Component                 | Service                              | Purpose                                                                                             |
| ------------------------- | ------------------------------------ | --------------------------------------------------------------------------------------------------- |
| **instance (controller)** | `aap-instance-controller.service`    | Disable/enable controller in mesh (API), installed on hosts within the `automationcontroller` group |
| **instance (execution)**  | `aap-instance-execution.service` | Disable/enable execution node in mesh (API), installed on hosts within the `execution_nodes` group  |
| **gateway**               | `aap-gateway.service`                | Stop/start local gateway services                                                                   |
| **controller**            | `aap-controller.service`             | Stop/start local controller services                                                                |
| **execution**             | `aap-execution.service`              | Stop/start local receptor service                                                                   |
| **eda**                   | `aap-eda.service`                    | Stop/start local EDA services                                                                       |
| **hub**                   | `aap-hub.service`                    | Stop/start local hub services                                                                       |


`aap-instance-controller` is installed on `automationcontroller` hosts; `aap-instance-execution` on `execution_nodes`.

## Usage

The installation requires the AAP installer inventory, sudo permissions on the API nodes, and an AAP API token with superuser write permissions in order to disable and enable instances. 

Most variables are derived from the AAP installer inventory. See [Install](#install) variables for futher information.

On controller and execution hosts, using the `manage_aap_service.yml` playbook with `aap_state=stopped` will only disable the instance ****via* `aap-instance-`. Stopping the `aap-<controller/execution` services must be a separate manual step after all jobs have completed running.

Follow the [Red Hat stop order](#red-hat-recommended-order-containerized) for maintenance. It is recommended to use one playbook run per component (using the inventory host group), or `-l` for a single host. See [Details](#details) for risks, service lists, and limitations. Use [Validation](#validation) to check wrapper services and containers after install or maintenance.

### Limitations

Each host runs a single AAP component wrapper (`aap-<component>`). `aap_node_type` is derived from inventory groups with precedence: controller, gateway, hub, execution, eda, redis. Dedicated Redis hosts (`[redis]` only) install `aap-redis`. Automation Mesh lifecycle services (`aap-instance-*`) apply only when `aap_node_type` is `controller` or `execution`.

The `aap-instance-*` roles do not wait for running jobs to finish before the service returns an `inactive` status. Stopping the `aap-controller` or `aap-execution` services after all jobs have completed running must be done manually.

### Install

```bash
ansible-playbook -i inventory install_aap_service.yml
ansible-playbook -i inventory install_aap_service.yml -l exec1.example.com
```


| Variable                             | Default                                             | Required                                            | Type            | Description                                                                                                                                                                                   |
| ------------------------------------ | --------------------------------------------------- | --------------------------------------------------- | --------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `aap_token`                          | -                                                   | Yes on `automationcontroller` and `execution_nodes` | string (secret) | Controller API token with superuser write permissions. Encrypted value is stored in `/etc/credstore.encrypted/aap_token` on install. Set in `install_aap_service.yml` `vars`, vault, or `-e`. |
| `aap_hostname`                       | `aap_hostname` or `gateway_main_url` from inventory | Yes on `automationcontroller` and `execution_nodes` | string (URL)    | Gateway URL for controller API calls. `https://` is added automatically if omitted. Omit to use `gateway_main_url`.                                                                            |
| `ansible_user`                       | Derived from inventory                              | Yes                                                 | string          | Inventory - user that owns AAP Podman container services.                                                                                                                                     |
| `aap_validate_certs`                 | `true` (role); `false` in `install_aap_service.yml` | No                                                  | boolean         | Verify TLS when calling the controller API from instance scripts.                                                                                                                             |
| `aap_instance_hostname`              | `routable_hostname`, else `inventory_hostname`      | No                                                  | string          | Hostname of this instance in the controller mesh.                                                                                                                                             |
| `aap_node_type`                      | Derived from inventory groups                       | No                                                  | string          | Component wrapper: `gateway`, `controller`, `execution`, `eda`, `hub`, or `redis`. Mesh lifecycle (`aap-instance-*`) applies only to `controller` and `execution`.                            |
| `aap_skip_units`                     | `[]`                                                | No                                                  | list            | Container service names to skip during start/stop (e.g. `postgresql` when external).                                                                                                          |
| `aap_extra_start_units`              | `[]`                                                | No                                                  | list            | Extra container services to start after the profile list.                                                                                                                                     |
| `aap_extra_stop_units`               | `[]`                                                | No                                                  | list            | Extra container services to stop.                                                                                                                                                             |
| `aap_instance_ready_timeout_seconds` | `600`                                               | No                                                  | integer         | Seconds to wait for `node_state=ready` after mesh enable.                                                                                                                                     |
| `aap_instance_ready_poll_seconds`    | `15`                                                | No                                                  | integer         | Poll interval when waiting for `node_state=ready`.                                                                                                                                            |
| `--limit` (`-l`)                     | All playbook hosts                                  | No (recommended)                                    | string          | Host pattern or inventory group to target.                                                                                                                                                    |


Requires `become` on targets. See [Inventory and configuration](#inventory-and-configuration) for group mapping and token storage. After install, use [Validation](#validation).

### Manage

```bash
# Step 1: stop the aap service on a controller node
ansible-playbook -i inventory manage_aap_service.yml \
  -e aap_state=stopped \
  -l controller.example.com

# Step 2: perform necessary maintenance

# Step 3: start the aap service again
ansible-playbook -i inventory manage_aap_service.yml \
  -e aap_state=started \
  -l controller.example.com
```


| Variable         | Default            | Required         | Type   | Description                                                             |
| ---------------- | ------------------ | ---------------- | ------ | ----------------------------------------------------------------------- |
| `aap_state`      | -                  | Yes              | string | `started` or `stopped`. Asserted in `manage_aap_service.yml` pre-tasks. |
| `--limit` (`-l`) | All playbook hosts | No (recommended) | string | Host pattern or inventory group to target.                              |


On `automationcontroller` and `execution_nodes`, `stopped` runs mesh drain (`aap-instance-*`) only; stop `aap-controller` / `aap-execution` manually after jobs finish. Other groups stop the component wrapper service directly.

### Uninstall

```bash
ansible-playbook -i inventory uninstall_aap_service.yml
ansible-playbook -i inventory uninstall_aap_service.yml -l exec1.example.com
```

Removes `aap-<component>` and `aap-instance-*` wrapper units and scripts without stopping them (Podman containers and mesh state are left as-is). On mesh hosts, also removes `/etc/credstore.encrypted/aap_token`. Does not remove AAP Podman container unit files or containers. Use `-l` to target a single host or group.

### Validation

Check wrapper services (system units - use `-b`) and containers (Podman - run as `ansible_user`, no `-b`). Replace `gateway1.example.com` with your host or omit `-l` to target the whole group.

**Automation Gateway**

```bash
ansible -i inventory automationgateway -b -a "systemctl status aap-gateway.service"
ansible -i inventory automationgateway -a "podman ps -a"
ansible -i inventory automationgateway -b -l gateway1.example.com -a "systemctl status aap-gateway.service"
ansible -i inventory automationgateway -l gateway1.example.com -a "podman ps -a"
```

**Automation Controller**

```bash
ansible -i inventory automationcontroller -b -a "systemctl status aap-controller.service"
ansible -i inventory automationcontroller -b -a "systemctl status aap-instance-controller.service"
ansible -i inventory automationcontroller -a "podman ps -a"
ansible -i inventory automationcontroller -b -l controller1.example.com -a "systemctl status aap-controller.service"
ansible -i inventory automationcontroller -b -l controller1.example.com -a "systemctl status aap-instance-controller.service"
ansible -i inventory automationcontroller -l controller1.example.com -a "podman ps -a"
```

**Execution node**

```bash
ansible -i inventory execution_nodes -b -a "systemctl status aap-execution.service"
ansible -i inventory execution_nodes -b -a "systemctl status aap-instance-execution.service"
ansible -i inventory execution_nodes -a "podman ps -a"
ansible -i inventory execution_nodes -b -l exec1.example.com -a "systemctl status aap-execution.service"
ansible -i inventory execution_nodes -b -l exec1.example.com -a "systemctl status aap-instance-execution.service"
ansible -i inventory execution_nodes -l exec1.example.com -a "podman ps -a"
```

**Automation Hub**

```bash
ansible -i inventory automationhub -b -a "systemctl status aap-hub.service"
ansible -i inventory automationhub -a "podman ps -a"
ansible -i inventory automationhub -b -l hub1.example.com -a "systemctl status aap-hub.service"
ansible -i inventory automationhub -l hub1.example.com -a "podman ps -a"
```

**EDA**

```bash
ansible -i inventory automationeda -b -a "systemctl status aap-eda.service"
ansible -i inventory automationeda -a "podman ps -a"
ansible -i inventory automationeda -b -l eda1.example.com -a "systemctl status aap-eda.service"
ansible -i inventory automationeda -l eda1.example.com -a "podman ps -a"
```

**Centralized Redis** (`[redis]` hosts)

```bash
ansible -i inventory redis -b -a "systemctl status aap-redis.service"
ansible -i inventory redis -a "podman ps -a"
ansible -i inventory redis -b -l redis1.example.com -a "systemctl status aap-redis.service"
ansible -i inventory redis -l redis1.example.com -a "podman ps -a"
```

`systemctl status` exits non-zero when a unit is not active; Ansible may report that as a failed task even when the output is useful.

### Full-stack maintenance

Stop in order (1 - 7); start in reverse (7 - 1). Mesh drain before execution/controller local stops. Dedicated `[redis]` hosts use step 6; colocated Redis stops last within `aap-gateway` / `aap-eda` when `redis-unix` / `redis-tcp` units are present on the host.

```bash
# Stop
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=stopped -l automationgateway
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=stopped -l automationeda
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=stopped -l execution_nodes
# wait for jobs; then on each execution node: sudo systemctl stop aap-execution.service
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=stopped -l automationcontroller
# wait for jobs; then on each controller node: sudo systemctl stop aap-controller.service
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=stopped -l automationhub
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=stopped -l redis
# local PostgreSQL: sudo systemctl --user stop postgresql.service

# Start
# local PostgreSQL: sudo systemctl --user start postgresql.service
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=started -l redis
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=started -l automationhub
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=started -l automationcontroller
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=started -l execution_nodes
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=started -l automationeda
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=started -l automationgateway
```

Verify gateway health and component registration before production use.

### Single component or node

Use one section when maintaining a single component. For multiple components in one window, run stop sections in order (1 - 7) and start in reverse (7 - 1).

#### Stop

**1. Automation Gateway**

```bash
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=stopped -l automationgateway
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=stopped -l gateway1.example.com
```

**2. EDA Server**

```bash
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=stopped -l automationeda
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=stopped -l eda1.example.com
```

**3. Execution node**

```bash
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=stopped -l execution_nodes
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=stopped -l exec1.example.com
# confirm drain in the controller UI (Instances) or wait for jobs to finish
sudo systemctl stop aap-execution.service
```

**4. Automation Controller**

```bash
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=stopped -l automationcontroller
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=stopped -l controller1.example.com
sudo systemctl stop aap-controller.service
```

**5. Automation Hub**

```bash
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=stopped -l automationhub
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=stopped -l hub1.example.com
```

**6. Centralized Redis** (`[redis]` hosts only; colocated Redis stops with gateway/EDA)

```bash
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=stopped -l redis
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=stopped -l redis1.example.com
```

**7. Database (local PostgreSQL)**

```bash
sudo systemctl --user stop postgresql.service
```

#### Start

On controller/execution hosts, start local container services before the playbook `started` run (mesh re-enable waits for `node_state=ready`).

**7. Database** - `sudo systemctl --user start postgresql.service`

**6. Centralized Redis**

```bash
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=started -l redis
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=started -l redis1.example.com
```

**5. Hub**

```bash
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=started -l automationhub
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=started -l hub1.example.com
```

**4. Controller**

```bash
sudo systemctl start aap-controller.service
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=started -l automationcontroller
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=started -l controller1.example.com
```

**3. Execution node**

```bash
sudo systemctl start aap-execution.service
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=started -l execution_nodes
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=started -l exec1.example.com
```

**2. EDA**

```bash
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=started -l automationeda
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=started -l eda1.example.com
```

**1. Gateway**

```bash
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=started -l automationgateway
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=started -l gateway1.example.com
```

### On the node (without Ansible)

```bash
sudo systemctl stop aap-instance-execution.service
# wait for jobs to finish
sudo systemctl stop aap-execution.service
sudo systemctl start aap-execution.service
sudo systemctl start aap-instance-execution.service
```

Binaries live under `/usr/local/bin/aap-*`.

## Details

### Maintenance overview


| Layer     | Service                                                                | Effect                                                                                        |
| --------- | ---------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| **Mesh**  | `aap-instance-`*                                                       | Controller API (`enabled: false`). Does not stop containers. Stops new jobs to that instance. |
| **Local** | `aap-gateway`, `aap-controller`, `aap-execution`, `aap-eda`, `aap-hub`, `aap-redis` | Stops Podman container services. Can kill running work immediately.                           |


### Red Hat recommended order (containerized)

Red Hat documents platform-wide order in [KCS 7124426](https://access.redhat.com/solutions/7124426) (AAP 2.5-2.7). This role wraps `systemctl --user` container services in `aap-<component>` wrapper services.

**Stop** (run on the appropriate nodes, in this order):


| Step | Node type             | Services (`systemctl --user stop ...`)                                                                                                                                                                                              |
| ---- | --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1    | Automation Gateway    | `automation-gateway`, `automation-gateway-proxy` - `redis-unix`, `redis-tcp` last when colocated on the host                                                                                                                                  |
| 2    | EDA Server            | `automation-eda-api`, `automation-eda-daphne`, `automation-eda-web`, `automation-eda-worker-*`, `automation-eda-activation-worker-*`, `automation-eda-scheduler` - `redis-unix`, `redis-tcp` last when colocated on the host                                   |
| 3    | Execution Node        | `receptor` - mesh drain first (`aap-instance-execution`)                                                                                                                                                                      |
| 4    | Automation Controller | `automation-controller-task`, `automation-controller-web`, `receptor` - mesh drain first - controller-local `redis` and `postgresql` last in `aap-controller`                                                                     |
| 5    | Automation Hub        | `automation-hub-api`, `automation-hub-content`, `automation-hub-web`, `automation-hub-worker-1`, `automation-hub-worker-2`                                                                                                        |
| 6    | Centralized Redis     | `redis-unix`, `redis-tcp` on dedicated `[redis]` hosts - after gateway and EDA; skipped on component hosts when unit files are absent                                                                                                  |
| 7    | Database              | `postgresql` - omit when external (`aap_skip_units`)                                                                                                                                                                              |


**Start:** reverse order (`start` instead of `stop`). Centralized `redis` starts first on gateway, EDA, and dedicated Redis hosts when the unit is present. Controller-local `redis` starts before controller app services. EDA worker services are optional when not installed.

### Component risks and considerations


| Component                 | Stopped by playbook `stopped`? | Risk if stopped without planning                              |
| ------------------------- | ------------------------------ | ------------------------------------------------------------- |
| **Instance (controller)** | Yes, on `automationcontroller` | Low for jobs on other nodes. Safe drain step.                 |
| **Instance (execution)**  | Yes, on `execution_nodes`      | Low for new work; running jobs continue until receptor stops. |
| **Gateway**               | Yes, on `automationgateway`    | **High** - UI/API unavailable; breaks mesh scripts.           |
| **Controller**            | No - manual `systemctl`        | **High** - kills job execution; drain first.                  |
| **Execution**             | No - manual `systemctl`        | **High** if jobs still run - drain first.                     |
| **Hub**                   | Yes, on `automationhub`        | **Moderate** - collection syncs/publishes fail.               |
| **EDA**                   | Yes, on `automationeda`        | **Low for controller mesh jobs** - pauses EDA only.           |
| **Redis (centralized)**   | Yes, on `[redis]` hosts        | **High** - gateway and EDA lose cache/queues when stopped.    |


Optional services (`postgresql`, `redis-unix`, `redis-tcp`, EDA workers) are skipped when the unit file is absent. Colocated Redis on gateway, EDA, or hub is started first and stopped last when those units exist on the host.

See [Limitations](#limitations) for mesh drain behavior.

### Inventory and configuration

Uses the AAP installer inventory. Playbooks target `automationgateway`, `automationcontroller`, `automationhub`, `execution_nodes`, `automationeda`, and `redis` (database hosts are not targeted). `ansible_user` is the AAP install user.

Set `aap_token` in `install_aap_service.yml` (vault or `-e`). `aap_validate_certs: false` is set in that playbook when the gateway cert does not match inventory hostnames.


| Inventory group        | Component    |
| ---------------------- | ------------ |
| `automationcontroller` | `controller` |
| `automationgateway`    | `gateway`    |
| `automationhub`        | `hub`        |
| `execution_nodes`      | `execution`  |
| `automationeda`        | `eda`        |
| `redis`                | `redis`      |


Colocated Redis (`redis-unix`, `redis-tcp`) is managed by the component wrapper on gateway, EDA, or hub when the installer placed those units on the host. Dedicated Redis VMs (`[redis]` only) get `aap-redis`. Controller-local Redis is always managed by `aap-controller`.


`aap_hostname` - gateway URL for controller API (`aap_hostname` or `gateway_main_url` from inventory; `https://` added if omitted). `aap_instance_hostname` - defaults to `routable_hostname` or `inventory_hostname`.

On enable, `aap-instance-*` waits for `node_state=ready` (default 600s timeout, 15s poll). Override `aap_instance_ready_timeout_seconds` and `aap_instance_ready_poll_seconds`.

Skip external database on controller:

```yaml
aap_skip_units:
  - postgresql
```

All role defaults: `roles/aap_service/defaults/main.yml`.

### API token storage

1. **Install** - `systemd-creds encrypt` into `/etc/credstore.encrypted/aap_token`.
2. **Service** - `aap-instance-*.service` uses `LoadCredentialEncrypted` and `PrivateMounts=yes`; token at `$CREDENTIALS_DIRECTORY/aap_token`.
3. **Manual start/stop** - use `systemctl start|stop aap-instance-*.service` so credentials are loaded via the unit.

Rotate: update `aap_token` and re-run `install_aap_service.yml`.

### Repository layout

```
install_aap_service.yml
manage_aap_service.yml
uninstall_aap_service.yml
roles/aap_service/
docs/
  systemd/              # reference service files (deployed from role templates)
  architecture.md
  operations-runbook.md
```

## References

- [Red Hat KCS 7124426 - Safely shut down and start containerized AAP](https://access.redhat.com/solutions/7124426)
- [systemd credentials](https://systemd.io/CREDENTIALS/)
- [Red Hat AAP 2.6 containerized installation](https://docs.redhat.com/en/documentation/red_hat_ansible_automation_platform/2.6/html/containerized_installation)
- [Architecture (](docs/architecture.md)`docs/architecture.md`[)](docs/architecture.md)
- [Operations runbook (](docs/operations-runbook.md)`docs/operations-runbook.md`[)](docs/operations-runbook.md)

