# Operations runbook

Full-stack stop/start order for containerized deployments follows Red Hat [KCS 7124426](https://access.redhat.com/solutions/7124426). See [README - Usage](../README.md#usage) for playbook workflows.

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

## Validation

See [README - Validation](../README.md#validation) for `ansible -i inventory <group> -b -a "systemctl status ..."` and `podman ps -a` commands per component.

## Skip external database on controller

```yaml
aap_skip_units:
  - postgresql
```
