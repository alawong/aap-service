# AAP Node Lifecycle Services

Ansible role and playbooks that install system-level wrapper services for containerized AAP 2.6 nodes. Playbooks run as **root** (`become`). System unit files live in `/etc/systemd/system/`; scripts in `/usr/local/bin/`. Component scripts run `systemctl --user` as `ansible_user` from inventory.

## Services


| Component       | Wrapper unit                      | What it does                                                                             |
| --------------- | --------------------------------- | ---------------------------------------------------------------------------------------- |
| Controller mesh | `aap-instance-controller.service` | Enable/disable controller in mesh via controller API (`automationcontroller` hosts only) |
| Execution mesh  | `aap-instance-execution.service`  | Enable/disable execution node in mesh via controller API (`execution_nodes` hosts only)  |
| Gateway         | `aap-gateway.service`             | Start/stop local gateway Podman units                                                    |
| Controller      | `aap-controller.service`          | Start/stop local controller Podman units                                                 |
| Execution       | `aap-execution.service`           | Start/stop local receptor unit                                                           |
| EDA             | `aap-eda.service`                 | Start/stop local EDA Podman units                                                        |
| Hub             | `aap-hub.service`                 | Start/stop local hub Podman units                                                        |
| Redis           | `aap-redis.service`               | Start/stop centralized Redis on dedicated `[redis]` hosts                                |


Automation Mesh wrappers (`aap-instance-*`) call the controller API only. Component wrappers (`aap-<component>`) manage local Podman user units only.

## Requirements

- AAP installer inventory (`automationgateway`, `automationcontroller`, `automationhub`, `execution_nodes`, `automationeda`, `redis`; not `database`)
- `ansible_user` must have root permissions on each AAP node
- On controller and execution hosts: `aap_token` (API token with superuser write permissions) and `aap_hostname` / `gateway_main_url` for mesh scripts



## Limitations

- One component wrapper per host. `aap_node_type` is derived from inventory groups (precedence: controller, gateway, hub, execution, eda, redis).
- `aap-instance-*` does not wait for running jobs to finish. On controller and execution hosts, drain with the playbook first, then stop `aap-controller` or `aap-execution` manually after jobs complete.
- Uninstall removes wrapper units and scripts only; it does not stop Podman containers or change mesh state.



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
| `aap_node_type`                                  | from inventory groups                       | No         | Override component type if needed                                       |
| `aap_skip_units`                                 | `[]`                                        | No         | Skip container units (e.g. external `postgresql`)                       |
| `aap_extra_start_units` / `aap_extra_stop_units` | `[]`                                        | No         | Extra units after/before profile lists                                  |
| `aap_instance_ready_timeout_seconds`             | `600`                                       | No         | Wait for `node_state=ready` after mesh enable                           |
| `aap_instance_ready_poll_seconds`                | `15`                                        | No         | Poll interval while waiting for ready                                   |




### Manage

```bash
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=stopped -l automationgateway
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=started -l automationgateway
```


| Variable    | Required | Description            |
| ----------- | -------- | ---------------------- |
| `aap_state` | Yes      | `started` or `stopped` |


On `automationcontroller` and `execution_nodes`, `aap_state=stopped` runs mesh drain (`aap-instance-*`) only. Stop `aap-controller` or `aap-execution` manually after jobs finish. All other groups stop or start the component wrapper directly.

### Uninstall

```bash
ansible-playbook -i inventory uninstall_aap_service.yml
ansible-playbook -i inventory uninstall_aap_service.yml -l exec1.example.com
```

Removes wrapper units and scripts without running `ExecStop`. On Automation Mesh hosts, it also removes `/etc/credstore.encrypted/aap_token` which contains the encrypted API token.

## Maintenance

Follow [Red Hat KCS 7124426](https://access.redhat.com/solutions/7124426) for platform-wide order. It is strongly recommended to run the `manage_aap_service.yml` once per component, in the following order.


| Step | Target                   | Wrapper / notes                                                                       |
| ---- | ------------------------ | ------------------------------------------------------------------------------------- |
| 1    | `automationgateway`      | `aap-gateway` — colocated `redis-unix` / `redis-tcp` stop last when present           |
| 2    | `automationeda`          | `aap-eda` — colocated Redis stops last when present                                   |
| 3    | `execution_nodes`        | `aap-instance-execution` (drain), then `sudo systemctl stop aap-execution.service`    |
| 4    | `automationcontroller`   | `aap-instance-controller` (drain), then `sudo systemctl stop aap-controller.service`  |
| 5    | `automationhub`          | `aap-hub`                                                                             |
| 6    | `redis`                  | `aap-redis` — dedicated Redis hosts only                                              |
| 7    | Controller with local DB | `sudo systemctl --user stop postgresql.service` — skip if external (`aap_skip_units`) |


Restart in reverse order (step 7 → 1). On controller and execution hosts, a single `aap_state=started` playbook run starts `aap-<component>` first, then `aap-instance-*` (mesh re-enable).

**Full stack**

```bash
# Stop AAP services (1 to 7)
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=stopped -l automationgateway
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=stopped -l automationeda
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=stopped -l execution_nodes

# wait for automation jobs to complete running
ansible -i inventory execution_nodes -b -a "systemctl stop aap-execution.service"
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=stopped -l automationcontroller

# wait for controller jobs to complete running
ansible -i inventory automationcontroller -b -a "systemctl stop aap-controller.service"

ansible-playbook -i inventory manage_aap_service.yml -e aap_state=stopped -l automationhub
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=stopped -l redis
# sudo systemctl --user stop postgresql.service  # if local DB

# Perform maintenance
ansible-playbook -i inventory maintain_aap.yml

# Start AAP services up again (7 - 1)
# sudo systemctl --user start postgresql.service  # if local DB
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=started -l redis
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=started -l automationhub
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=started -l automationcontroller
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=started -l execution_nodes
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=started -l automationeda
ansible-playbook -i inventory manage_aap_service.yml -e aap_state=started -l automationgateway
```

**On the node (execution example)**

```bash
sudo systemctl stop aap-instance-execution.service
# wait for jobs to finish
sudo systemctl stop aap-execution.service
sudo systemctl start aap-execution.service
sudo systemctl start aap-instance-execution.service
```



### Risks


| Component                         | Playbook `stopped` alone? | Risk                                        |
| --------------------------------- | ------------------------- | ------------------------------------------- |
| Instance (controller / execution) | Yes                       | Low — drains mesh; does not stop containers |
| Gateway                           | Yes                       | High — UI/API down; breaks mesh scripts     |
| Controller / execution (local)    | Manual step required      | High — stops job execution; drain first     |
| Hub                               | Yes                       | Moderate — collection sync/publish fails    |
| EDA                               | Yes                       | Low for controller jobs — pauses EDA only   |
| Redis (`aap-redis`)               | Yes                       | High — gateway and EDA lose cache/queues    |




## Validation

Check wrapper units with `-b` (root). Check containers as `ansible_user` (no `-b`).

```bash
# Example: gateway group or single host
ansible -i inventory automationgateway -b -a "systemctl status aap-gateway.service"
ansible -i inventory automationgateway -a "podman ps -a"
ansible -i inventory automationgateway -b -l gateway1.example.com -a "systemctl status aap-gateway.service"
```


| Group                  | Wrapper unit(s) to check                                    |
| ---------------------- | ----------------------------------------------------------- |
| `automationgateway`    | `aap-gateway.service`                                       |
| `automationcontroller` | `aap-controller.service`, `aap-instance-controller.service` |
| `execution_nodes`      | `aap-execution.service`, `aap-instance-execution.service`   |
| `automationhub`        | `aap-hub.service`                                           |
| `automationeda`        | `aap-eda.service`                                           |
| `redis`                | `aap-redis.service`                                         |


`systemctl status` exits non-zero when a unit is inactive; Ansible may report that as failed even when the output is useful.

## Configuration



### Inventory groups


| Inventory group        | `aap_node_type` | Wrapper                                     |
| ---------------------- | --------------- | ------------------------------------------- |
| `automationcontroller` | `controller`    | `aap-controller`, `aap-instance-controller` |
| `automationgateway`    | `gateway`       | `aap-gateway`                               |
| `automationhub`        | `hub`           | `aap-hub`                                   |
| `execution_nodes`      | `execution`     | `aap-execution`, `aap-instance-execution`   |
| `automationeda`        | `eda`           | `aap-eda`                                   |
| `redis`                | `redis`         | `aap-redis`                                 |


Colocated centralized Redis (`redis-unix`, `redis-tcp`) is managed by `aap-gateway` or `aap-eda` when those unit files exist on the host (optional units — skipped when absent). Dedicated Redis VMs (defined using the `[redis]` group) use the dedicated `aap-redis` service. Local redis units (`redis-unix` ) are  managed by the standard `aap-*` service.

Set `aap_token` in `install_aap_service.yml` (vault or `-e`). `aap_validate_certs: false` is set in that playbook when the gateway certificate does not match inventory hostnames.

Skip external database on the controller:

```yaml
aap_skip_units:
  - postgresql
```

All defaults: `roles/aap_service/defaults/main.yml`.

### API Token Usage

1. Install - `systemd-creds encrypt` to `/etc/credstore.encrypted/aap_token`
2. `aap-instance-*.service` - encrypted token file is loaded into the systemd binary using `LoadCredentialEncrypted` with the `PrivateMounts=yes` option
3. Manual mesh start/stop - Running `systemctl start|stop aap-instance-*.service` will decrypt the API token using systemd-creds and load it into the systemd binary on start/stop. API token is never stored in plaintext.

Rotate: update the `aap_token` variable within `install_aap_service.yml` and re-run the playbook.

## Repository Layout

```
install_aap_service.yml
manage_aap_service.yml
uninstall_aap_service.yml
roles/
  aap_service/
docs/
  systemd/              # reference units (deployed from role templates)
  architecture.md
  operations-runbook.md
```



## References

- [Red Hat KCS 7124426 — containerized AAP stop/start order](https://access.redhat.com/solutions/7124426)
- [systemd credentials](https://systemd.io/CREDENTIALS/)
- [AAP 2.6 containerized installation](https://docs.redhat.com/en/documentation/red_hat_ansible_automation_platform/2.6/html/containerized_installation)
- [Architecture](docs/architecture.md)
- [Operations runbook](docs/operations-runbook.md)

