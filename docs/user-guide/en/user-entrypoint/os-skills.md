# OS Skills

OS Skills is a system management and DevOps skill library for AI Agents. It provides pre-built skills that enable Agents to perform common system administration and automation tasks.

---

## Overview

OS Skills covers three main areas:

- **System Administration** — user management, service control, package operations, filesystem tasks
- **Cloud Integration** — cloud resource queries, instance management, network configuration
- **DevOps Automation** — CI/CD pipeline management, container operations, deployment workflows

---

## Installation

```bash
anolisa install os-skills
```

---

## Quick Start

Once installed, OS Skills are available to any ANOLISA-compatible Agent runtime. The Agent can invoke skills via natural language:

```
> "Check disk usage on all mounted filesystems"
> "Restart the nginx service"
> "Show running containers and their resource usage"
```

---

## Skill Categories

### System Administration

| Skill | Description |
|-------|-------------|
| `disk-usage` | Check filesystem disk usage |
| `service-ctl` | Start/stop/restart system services |
| `process-mgmt` | List and manage processes |
| `user-mgmt` | User and group management |
| `package-ops` | Package install/remove/query |

### DevOps Automation

| Skill | Description |
|-------|-------------|
| `container-ops` | Docker/Podman container management |
| `log-analysis` | Search and analyze system logs |
| `network-diag` | Network diagnostics (ping, traceroute, port check) |
| `cron-mgmt` | Cron job management |

---

## Usage with Agent Runtimes

OS Skills integrates with cosh and other ANOLISA-compatible runtimes automatically. Skills are discovered at startup and made available to the Agent's tool inventory.

```bash
# Verify skills are loaded
anolisa status os-skills
```

---

## Configuration

Configuration file: `~/.config/os-skills/config.toml`

```toml
[skills]
# Enabled skill categories
enabled = ["system", "devops"]

[safety]
# Require confirmation for destructive operations
confirm_destructive = true
```

---

## Workbook named and print ranges

The XLSX row-shift helper now updates direct references in `xl/workbook.xml` defined names, including print areas and repeated print-title rows:

```bash
python3 SKILL_DIR/scripts/xlsx_unpack.py input.xlsx /tmp/xlsx_work/
python3 SKILL_DIR/scripts/xlsx_shift_rows.py /tmp/xlsx_work/ insert 5 2
python3 SKILL_DIR/scripts/xlsx_pack.py /tmp/xlsx_work/ output.xlsx
python3 SKILL_DIR/scripts/formula_check.py output.xlsx
```

As with the existing row shift, the operation applies to every worksheet in the unpacked workbook. A defined range `Sheet1!$A$3:$C$7` becomes `Sheet1!$A$3:$C$9`; print-title rows `$1:$6` become `$1:$8` for this insertion. Absolute markers, quoted sheet names, local/hidden name attributes and comma unions are preserved. Whole-column ranges remain unchanged. Deletion follows the existing endpoint-shift policy, clamping shifted rows to row 1.

Only complete direct cell/range, whole-row or whole-column unions are supported. Complex formulas/constants, structured references, external workbooks, 3D sheet references and malformed/out-of-grid names remain unchanged for manual review; if one union component is unsupported, the entire definition is retained. Repack and inspect the result before using it. The helper does not calculate formulas, remove deleted row elements or provide sheet-specific shifting.

---

## See Also

- [Copilot Shell](copilot-shell/QUICKSTART.md)
- [anolisa CLI](anolisa-cli.md)
