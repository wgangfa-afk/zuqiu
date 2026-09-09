# Football Quant AI V6.0

这是 Football Quant AI 的主仓库，正式采用 **A/B 双分区架构**：

- `analysis_engine/`：**A — Analysis Engine**。负责足球分析、盘口定价、多市场路由、EV、评级、临场判断、资金池与赛后复盘。
- `data_platform/`：**B — Data & Development Platform**。由 Codex 工程化实现数据采集、数据库、盘口历史、结算、回测、自动化与相关基础设施。
- `codex_guide/`：属于 **B 分区内部的开发指导与质量控制目录**，用于 Codex 开发任务、编码规范、验收标准、代码与足球业务逻辑审查；它不是独立分区。
- `docs/`：A/B 共用的 V6.0 分析规范、资金池、复盘、数据质量等长期规范。

## A/B 职责边界

### A — Analysis Engine

A 是决策层，负责：
- 赛前与临场比赛分析
- 理论盘口与市场定价
- Market Router / Cross-Market EV
- 1X2、亚洲让球、大小球、BTTS、球队进球
- Corner Engine：总角球、亚洲角球、三项角球、让角、球队角球
- Card Engine：总牌、球队牌、让牌及裁判因素
- Match State / Market Refusal / Favorite Trap
- `S > A+ > A > A- > B+ > B > C > PASS` 评级
- ¥10,000 月度模拟资金池与仓位决策
- Execution / Analysis / Counterfactual 全决策复盘

### B — Data & Development Platform

B 是工程与研究基础设施层，负责：
- 数据采集与多源校验
- 盘口、水位、欧赔与历史快照数据库
- 数据质量等级与时间戳
- 结算引擎与资金账本
- CLV、ROI、回测与统计
- 自动报告和复盘基础设施
- 后续机器学习/研究平台
- Codex 开发、测试、PR 与验收

**原则：B 为 A 提供可信数据与计算能力，但不得擅自改变 A 的足球分析业务规则。A 的规则变更应先更新规范，再由 B 工程化实现。**

## 核心原则

1. 目标不是“预测谁会赢”，而是在“比赛 × 市场”空间寻找错误定价和长期正 EV。
2. 主胜价格差不等于整场 PASS。Market Router 必须继续检查亚洲让球、大小球、球队进球、BTTS、角球、让角、球队角球、罚牌、让牌等。
3. 严禁编造盘口、水位、伤停、首发、角球或罚牌数据。无法核验时降级或 PASS。
4. 角球与罚牌独立建模；高进球不等于大角，高压制也不必然大牌。
5. 使用 `S > A+ > A > A- > B+ > B > C > PASS` 评级，并由 EV、数据质量、盘口一致性、模型置信度和风险共同决定。
6. 月度模拟资金池为 ¥10,000 = 100U，1U = ¥100；不为回本而加仓。
7. Execution Book、Analysis Book、Counterfactual Book 三账分离，赛后禁止把未执行方向算进正式收益。
8. 默认单场，不默认串关，不为凑推荐数量强推。

## 当前版本

- A / Analysis Engine: V6.0
- A / Bankroll Engine: V1.0
- A / Review Engine: Counterfactual Review V1.0
- B / Data & Development Platform: Alpha Foundation 开发阶段
- B / Codex Guide: V1.0

开发前请先阅读 `docs/` 与 `codex_guide/`。`codex_guide/` 从现在起统一视为 B 分区的内部开发规范，不再使用 C 分区称谓。

## Alpha Foundation（FQ-V6-001）

本仓库的 Alpha Foundation 位于 `data_platform/`，只提供 B 分区的 SQLite、结算、三账隔离与模拟账本能力；不采集真实盘口，也不生成预测概率。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m data_platform health
pytest
```

默认数据库是当前目录的 `football_quant.sqlite3`。也可通过 `.env` 设定 `DATABASE_URL=sqlite:///path/to/file.sqlite3`。所有内部时间字段使用 UTC；`TIMEZONE` 仅用于展示层的默认时区。

## Recoverability（FQ-V6-002）

`data_platform.recovery` 提供 SQLite 一致性备份、manifest SHA-256 校验、向全新路径恢复、启动完整性检查与资金账本重建。备份必须放在 Git 仓库外：

```python
from pathlib import Path
from data_platform.database import Database
from data_platform.recovery import create_backup, restore_backup, startup_integrity_check

db = Database("football_quant.sqlite3")
db.initialize()
assert startup_integrity_check(db).ok
manifest = create_backup(db, Path("../backup/manual"))
restored = restore_backup(manifest, Path("../recovery-test.sqlite3"))
```

也可直接使用命令行完成真实备份与恢复演练（恢复目标必须是尚不存在的新文件）：

```powershell
python -m data_platform backup --destination ..\backup\manual
python -m data_platform restore --manifest ..\backup\manual\<backup-id>.manifest.json --destination ..\recovery-test.sqlite3
python -m data_platform health
```

manifest 会保存全部 P0 表的逐表摘要及正式 `stake/ROI/PnL` 基线。恢复过程先在临时数据库完成 checksum、row count、逐表 digest、账本重建、三账边界和 ROI/PnL 校验，通过后才原子发布到新路径；失败时不会覆盖既有目标。

任何完整性失败都会使当前 `Database` 进入 `RECOVERY_REQUIRED`，阻止正式 Execution、锁单、结算和盘口快照写入；必须恢复到新数据库并重新通过检查后才可恢复运行。
