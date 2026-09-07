# Football Quant AI V6.0 — Recoverability & Disaster Recovery Spec

## 1. 目标

本规范属于 **B — Data & Development Platform**。目标不是“永不出错”，而是让系统在进程崩溃、机器损坏、数据库损坏、误操作、部分数据源失败、重复任务、版本升级失败时，能够：

1. 恢复到最后一个可信状态；
2. 不丢失已锁定 Execution；
3. 不重复记账、不重复结算；
4. 不把 Analysis / Counterfactual 混入正式收益；
5. 能证明恢复前后关键账本一致；
6. 能重放历史数据并复现当时结论。

## 2. 恢复优先级

### P0 — 必须恢复
- Execution Book
- Settlement
- Bankroll Ledger
- Fixture 基础身份与 kickoff
- MarketSnapshot 原始历史
- 审计记录与 schema/version 信息

### P1 — 应恢复
- Analysis Book
- Counterfactual Book
- ReviewRecord
- 计算缓存之外的中间产物

### P2 — 可重建
- 临时缓存
- 派生报表
- 可由原始数据重新计算的统计结果

## 3. 核心恢复原则

### 3.1 Source of Truth
SQLite 主库是当前 Alpha 阶段的事务源；备份、导出和恢复必须围绕同一套不可变业务约束进行。

### 3.2 Append-Only First
MarketSnapshot、Settlement、BankrollLedger、审计事件优先采用 append-only。对关键历史数据禁止原地覆盖。

### 3.3 Idempotency
所有可重复执行的写操作必须有幂等键，至少包括：
- market snapshot ingest key
- execution lock key
- settlement key
- bankroll ledger key
- backup manifest id

重复执行同一任务不得产生重复正式记录。

### 3.4 Recover Before Resume
程序重启后不得直接继续抓取/结算；必须先执行健康检查与恢复检查，通过后再恢复业务循环。

## 4. SQLite 备份策略

### 4.1 在线一致性备份
必须使用 SQLite 官方 backup API 或等价一致性机制，不允许在数据库写入期间直接复制裸 `.db` 文件作为唯一备份方案。

### 4.2 备份层级
Alpha 阶段至少提供：
- `backup/manual/`：人工触发快照
- `backup/daily/`：每日快照
- `backup/pre_migration/`：每次 schema migration 前快照

### 4.3 保留策略
建议默认：
- 最近 7 个 daily
- 最近 4 个 weekly（Phase 2 可实现）
- 所有 pre_migration 至少保留到该 migration 完成验证

不得把真实备份文件提交到 GitHub。

## 5. Backup Manifest

每个备份必须配套 manifest，至少记录：
- backup_id
- created_at_utc
- database_path
- schema_version
- git_commit_sha（如可用）
- db_size
- sha256
- row counts：fixtures / market_snapshots / executions / settlements / bankroll_ledger / analysis_decisions
- last_execution_locked_at
- last_settlement_at

恢复时先验证 manifest，再恢复数据库。

## 6. Schema Version & Migration

### 6.1 schema_version
数据库必须保存当前 schema 版本。

### 6.2 migration 原则
- migration 必须有唯一版本号
- migration 不允许静默失败
- 每次 migration 前自动生成 pre_migration backup
- migration 完成后运行 integrity check
- 验证失败必须回滚或从 pre_migration backup 恢复

### 6.3 禁止
- 在生产/正式账本数据库上手工 ALTER 而不记录版本
- 直接删除正式历史字段
- 修改已锁 Execution 的业务语义

## 7. Startup Recovery Check

应用启动时必须执行：
1. 数据库可打开
2. `PRAGMA integrity_check`
3. schema_version 可识别
4. foreign key check
5. Execution 生命周期合法
6. 一个 Execution 最多一个 Settlement
7. 每个 locked/settled Execution 的 stake ledger 唯一
8. 每个 settled Execution 的 pnl ledger 唯一
9. Analysis/Counterfactual 不得出现在正式 ledger
10. MarketSnapshot 不可变约束存在

任一 P0 检查失败：进入 `RECOVERY_REQUIRED`，禁止正式写入。

## 8. Execution 恢复规则

状态机只有：
`DRAFT -> LOCKED -> SETTLED`

恢复时：
- DRAFT 可丢弃或继续编辑，但不计正式资金
- LOCKED 必须完整保留，不允许因重启退回 DRAFT
- SETTLED 必须同时存在 Settlement 与匹配的 bankroll pnl

如果发现：
- LOCKED 有 stake 但重复 stake ledger：停止并报错
- SETTLED 无 Settlement：停止并报错
- Settlement 存在但 Execution 非 SETTLED：停止并报错

不得自动“猜测修复”正式账本。

## 9. Settlement 幂等

Settlement 必须由 `execution_id` 唯一约束。
重复结算同一 Execution：
- 若结果完全一致：返回已有结果，不重复记账
- 若结果不一致：拒绝写入并产生审计告警

禁止第二次结算覆盖第一次结算。

## 10. Bankroll 重建能力

正式 bankroll 余额必须可以仅从 Execution + Settlement + Ledger 重建。

提供 `rebuild_bankroll()` 或等价校验函数：
- 重新计算每个 Execution 的 stake/pnl
- 与 BankrollLedger 聚合结果比较
- 不一致则进入恢复模式

不得仅相信缓存余额。

### 10.1 净 PnL 账本语义

正式余额使用净 PnL 模型。`stake` ledger 是锁单时的 exposure/turnover 事实，不能当作已实现损失加入 bankroll balance；`pnl` ledger 与 Settlement 的 `pnl_u` 都必须等于由 immutable `stake_u`、`odds` 和 outcome 重算得到的净 PnL。余额等于初始资金加所有已结算净 PnL；ROI 分母为已结算 Execution 的 stake 周转额。

## 11. Export / Import

至少提供一种可审计导出格式（建议 JSONL 或 CSV + manifest），覆盖 P0 数据。

Import 必须：
- 先进入新数据库或临时数据库
- 验证 checksum / schema / 外键 / row counts
- 通过后才允许替换正式数据库

禁止直接把未知文件覆盖当前数据库。

## 12. Audit Log

对以下操作至少记录结构化审计事件：
- execution_created
- execution_locked
- settlement_created
- bankroll_entry_created
- backup_created
- restore_started
- restore_completed
- restore_failed
- migration_started
- migration_completed
- integrity_check_failed

审计日志不得包含 API Key、Cookie、Token。

## 13. Crash / Restart Scenarios

必须测试：
- 创建 DRAFT 后崩溃
- LOCK 成功、写 stake 后崩溃
- Settlement 写入前崩溃
- Settlement 写入后、pnl ledger 写入前崩溃
- 备份过程中崩溃
- migration 中途失败

事务边界必须保证不会留下半完成正式状态。

## 14. RPO / RTO（Alpha 目标）

- RPO：关键正式账本目标 0（依靠本地事务）；机器级损坏下取决于最近备份
- RTO：人工恢复目标 < 30 分钟

Phase 2 再考虑远程备份与更低机器级 RPO。

## 15. 验收标准

Recoverability 建设完成时必须证明：
1. 能生成一致性数据库备份和 manifest
2. 能从备份恢复到新数据库
3. 恢复后 P0 各表 row count 与 checksum 校验通过
4. locked/settled Execution 不丢失
5. bankroll 重建与原账本一致
6. 重复 settlement 不会重复记账
7. migration 前自动备份
8. integrity check 失败时阻止正式写入
9. 至少覆盖 6 类 crash/restart 测试
10. README 中有清晰的 backup / restore 命令

## 16. 范围边界

本阶段不要求：
- 云对象存储
- 跨区域容灾
- 高可用集群
- PostgreSQL 主从
- 实时热备

先把 **单机 SQLite 的可恢复性、幂等、审计、备份、恢复、校验** 做正确。

## 17. Checksum 威胁模型

SHA-256、行数和关键表 canonical digest 用于检测意外损坏、不完整发布和数据库/manifest 不一致。它们不是签名，不保证来源真实性，也不能抵御可同时重写备份数据库与 manifest 的攻击者。本阶段保留 manifest version 与签名/HMAC 扩展字段，但不实现密钥管理或签名验证。
