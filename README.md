# Football Quant AI V6.0

这是 Football Quant AI 的主仓库，采用三分支职责架构：

- `analysis_engine/`：A — Analysis Engine。负责足球分析、盘口定价、多市场路由、EV、评级、资金池与复盘规则。
- `data_platform/`：B — Data & Research Platform。由 Codex 工程化实现数据采集、数据库、盘口历史、回测与自动化。
- `codex_guide/`：C — Codex Dev Guide。用于开发任务、编码规范、验收标准与代码审查。
- `docs/`：V6.0 分析规范、资金池、复盘、数据质量等长期规范。

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

- Analysis Engine: V6.0
- Bankroll Engine: V1.0
- Review Engine: Counterfactual Review V1.0
- Data Platform: 待 Codex 开发
- Codex Guide: V1.0

请先阅读 `docs/` 与 `codex_guide/`，再开始代码开发。
