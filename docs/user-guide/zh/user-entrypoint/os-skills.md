# OS 技能库

OS Skills 是面向 AI Agent 的系统管理与 DevOps 技能库。它提供预构建的技能，使 Agent 能够执行常见的系统管理和自动化任务。

---

## 概述

OS Skills 覆盖三大领域：

- **系统管理** — 用户管理、服务控制、包管理、文件系统操作
- **云集成** — 云资源查询、实例管理、网络配置
- **DevOps 自动化** — CI/CD 流水线管理、容器操作、部署工作流

---

## 安装

```bash
anolisa install os-skills
```

---

## 快速开始

安装后，OS Skills 可供任何 ANOLISA 兼容的 Agent 运行时使用。Agent 可通过自然语言调用技能：

```
> "检查所有已挂载文件系统的磁盘使用情况"
> "重启 nginx 服务"
> "显示运行中的容器及其资源使用"
```

---

## 技能分类

### 系统管理

| 技能 | 说明 |
|------|------|
| `disk-usage` | 检查文件系统磁盘使用 |
| `service-ctl` | 启动/停止/重启系统服务 |
| `process-mgmt` | 列出和管理进程 |
| `user-mgmt` | 用户和组管理 |
| `package-ops` | 包安装/移除/查询 |

### DevOps 自动化

| 技能 | 说明 |
|------|------|
| `container-ops` | Docker/Podman 容器管理 |
| `log-analysis` | 搜索和分析系统日志 |
| `network-diag` | 网络诊断（ping、traceroute、端口检查） |
| `cron-mgmt` | Cron 任务管理 |

---

## 与 Agent 运行时集成

OS Skills 与 cosh 及其他 ANOLISA 兼容运行时自动集成。技能在启动时被发现并加入 Agent 的工具清单。

```bash
# 验证技能已加载
anolisa status os-skills
```

---

## 配置

配置文件：`~/.config/os-skills/config.toml`

```toml
[skills]
# 启用的技能类别
enabled = ["system", "devops"]

[safety]
# 对破坏性操作要求确认
confirm_destructive = true
```

---

## 工作簿命名范围与打印范围

XLSX 行移动脚本现在更新 `xl/workbook.xml` 定义名称中的直接引用，包括打印区域和重复打印的标题行：

```bash
python3 SKILL_DIR/scripts/xlsx_unpack.py input.xlsx /tmp/xlsx_work/
python3 SKILL_DIR/scripts/xlsx_shift_rows.py /tmp/xlsx_work/ insert 5 2
python3 SKILL_DIR/scripts/xlsx_pack.py /tmp/xlsx_work/ output.xlsx
python3 SKILL_DIR/scripts/formula_check.py output.xlsx
```

与原有行移动行为一致，操作作用于解包工作簿内所有工作表。上述插入将 `Sheet1!$A$3:$C$7` 改为 `Sheet1!$A$3:$C$9`，打印标题行 `$1:$6` 改为 `$1:$8`。绝对引用标记、带引号的工作表名称、本地或隐藏名称属性及逗号联合范围都会保留。整列范围不变。删除遵循现有端点移动策略，移动后的行号至少为 1。

仅支持完整的直接单元格、矩形区域、整行或整列联合引用。复杂公式或常量、结构化引用、外部工作簿、三维工作表引用及无效或超出网格的名称保持原样，需人工检查；若联合引用中任一部分不支持，会保留整个定义。重新打包后先检查结果再使用。脚本不会计算公式、移除被删除的行元素，也不提供单工作表行移动。

---

## 参见

- [Copilot Shell](copilot-shell/QUICKSTART.md)
- [anolisa CLI](anolisa-cli.md)
