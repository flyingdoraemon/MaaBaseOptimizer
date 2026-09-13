# 历史记录说明

本报告记录 2026-09-13 的实现；其中严格库存与心情审计的后续变更以 [2026-09-14 校对](login-morale-2026-09-14.md) 为准。

# 2026-09-13 排班与快进模拟校对

本次修改位于 `MaaBaseOptimizer`。相邻的 MAA 主仓库没有这个全局优化器和模拟模块，本次没有修改 MAA 主仓库。

## 可复现的数据来源

- 国服数据：[Kengxxiao/ArknightsGameData](https://github.com/Kengxxiao/ArknightsGameData/tree/0ef7f952dfd018392200157a5c79a6511ba69122/zh_CN/gamedata/excel)，2026-09-11 更新，客户端 2.7.71。429 名基建干员、755 条技能；文件 SHA-256 与提交号写入 `data/catalog.json` 的 `sources`。
- 价值公式：[一图流 BackEndV3，CustomItemServiceImpl.java](https://github.com/Arknights-yituliu/BackEndV3/blob/24b2cd7d3ae75b843104c6f37dc6aa6e9f51a084/src/main/java/com/lhs/service/material/impl/CustomItemServiceImpl.java#L296)。本次读取了实际源码，不只读取 README。
- 用户指定的[物品价值算法页面](https://ark.yituliu.cn/docs/item-value-algorithm)当前读取只返回前端入口，没有可提取的正文；公式核验以同项目上述固定提交的后端实现为准。
- [PRTS 发电站](https://prts.wiki/w/罗德岛基建/发电站)：一架无人机减少三分钟**基础耗时**。游戏数据中 `manufactReduceTimeUnit` / `tradingReduceTimeUnit` 同为 180 秒。

更新数据（完整下载、解析成功后才原子替换目录；失败保留旧数据）：

```bash
.venv/bin/python scripts/update_catalog.py
.venv/bin/python scripts/audit_skills.py
```

`--revision` 可固定游戏提交；`--maa-infrast` 可使用本地 MAA 模型。默认同时获取并记录当前 MAA dev-v2 的提交。

## 技能与产线

- 数据构建同时支持数值枚举和 `PHASE_*` / `TIER_*` 枚举。
- 结城理 E0 控制中枢制造 +2%，与同类效果取最高；E2 制造 +20%，基建内 S.E.E.S. 每人再 +5%，最多四人，包含自身。
- 埃癸斯发电基础 +15%，结城理在制造站时再 +5%。游戏该技能 `efficiency` 为零，因此必须显式处理。
- 岳羽由加莉、虎狼丸的技能与解锁数据同步更新，沿用办公室、宿舍等通用规则。
- S.E.E.S. 计数使用目录 `team_id`，自动统计已排定生产、中枢、会客室、办公室及锁定宿舍位；未指定的闲置宿舍/训练室人员不擅自算满四人。跨房间候选仍使用现有有限次迭代，未收敛会提示；尚非所有设施状态的联合最优证明。
- 制造产品目标修正：源石碎片技能不能获得仅对赤金/经验生效的加成；贸易站合成玉候选使用 MAA `SyntheticJade`，不能套用 `Money` 的排名分。
- 制造站生产的是源石碎片；贸易站消耗碎片换取合成玉，分别建模。
- API 接受 `gold_factories`、`exp_factories`、`shard_factories`，之和须等于布局制造站数。省略 `gold_factories` 时使用余数。`orundum_trades` 从零到贸易站总数独立选择。非法组合明确报错，不静默裁剪。
- 页面不再因为选了碎片制造而强制开启源石订单。全部三产品组合均可选择，赤金为制造站余数。

## 价值与无人机

基础常量：`V_LMD=36/10000`，`V_EXP=V_LMD×145/229`，`V_drone=V_EXP×50/3`，`V_gold=24×V_drone`。

旧代码把无人机的三分钟又乘上了房间生产倍率，导致高效率队伍下无人机收益被高估。已同时修正优化指标、固定/错峰曲线和快进模拟。60 架无人机加速 1000 EXP、24 架加速一根赤金，与干员速度无关；贸易订单品质、违约/投资造成的每基础工时收益差异仍影响贸易加速价值。

搓玉定价支持自定义价值（兼容默认 0.75 理智/合成玉）以及一图流的两种配方成本口径：

- 固源岩：`V_orundum=(2×V_rock+1600×V_LMD+40×V_drone)/10`。
- 装置：`V_orundum=(V_device+1000×V_LMD+40×V_drone)/10`。
- 中间品碎片：`V_shard=10×V_orundum−20×V_drone`，对应后续贸易加工后的净值。

完整方案按龙门币与经验产出、赤金/碎片库存净变化、合成玉产出记账，扣除碎片生产的龙门币和材料成本。单房候选与完整资源账本使用相同口径，避免消耗已有碎片获得“免费合成玉”，也避免对新制碎片与换得的合成玉重复计价。

材料价值依个人机会成本选择，页面高级设置或 API 可传：

```json
{"valuation":{"orundum_pricing":"rock","rock":1.2}}
```

此处 `1.2` 只是参数示例，不声称是当前一图流价格。留空材料价格时报告实物消耗并明确列为 `unpriced_materials`，不虚构市场价格；选择按配方定价则必须填对应材料价格。固定产线目标与理智价值目标继续分开，后者可能为了降低搓玉净成本而偏好较低产量，属于用户所选经济目标。

## 原模拟的问题与新模块

原 `simulate()` 用各班在岗比例乘总时长，制造站直接 `int(日均产速×天数)`，库存再按均值等分；前端甚至把 A/B 两个独立实验的分位数加权。该实现不是真正的共同时间线重放，不能检验跨班进度、满仓、收菜时机。

新 `maabase/simulator.py` 在虚拟时间中跳转，不调用 sleep、不等待真实天数：

1. 读取物理房间的 A/B `rotation` 时间线；产品进度在换班时保留，速度按新班次生效。
2. 每个产品/订单独立完成；订单开始时按种子抽样，品质随该班已工作时间变化，整点技能分段推进。
3. 三级站基础仓容与已实现的静态容量技能决定满仓暂停；收菜时先收制造产品，再交订单。无人机按实际上线节点逐架投入，减少基础工时，库存上限与余量保留。
4. `working_stock` 模式允许库存负数，显示所需周转补贴；`strict` 模式库存不足则订单留仓，满仓暂停。两者均有真实收取事件，终点不额外强制收菜。
5. 多次实验运行完整排班，从完整实验总收益计算均值、P05/P95。固定种子可复现，前端不再加权两个独立分位数。
6. 输出第一轮事件轨迹（最多 2000 个完成事件）、全部收取/无人机事件、期末未收产物及在制进度，页面可下载 JSON。只有事件明细截断，统计和账本不截断。

API 示例：

```python
from maabase.simulator import simulate
report = simulate({
    "rotation": optimized_result["rotation"],
    "days": 30, "trials": 1000, "seed": 20260913,
    "inventory_policy": "strict",
})
```

模拟仍是基于公开游戏数据的模型，不是游戏客户端执行日志。以下边界明确保留：品质暖机为线性近似；孑等动态队列速度使用候选均值；复杂动态仓容未全部逐状态还原；心情消耗/恢复由排班器审计，随机层不会自动修复不可持续班表；碎片配方材料与龙门币供应假定充足并报告消耗，不模拟其耗尽停产。旧版 `work_fraction` 输入缺少换班时刻，只按每天开头连续在岗兼容，完整重放应传 `rotation`。

## 验证

`tests/test_production_update.py` 覆盖 127 种合法产线组合、非法配置、新干员精英解锁/条件联动、目标产品隔离和一图流全账本守恒；`tests/test_simulator.py` 覆盖跨班保留进度、满仓暂停、严格库存、同节点制造/贸易结算、分段速度、无人机、随机种子和非整数收菜间隔。原有回归测试继续执行。

```bash
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/python scripts/audit_skills.py --compact
```

最终验证：原有与新增测试合计 61 项通过（完整套件 60 项通过后，补充大整数种子跨浏览器 JSON 保真测试，并重跑全部模拟与页面契约测试）；技能目录引用与映射审计通过。全目录仍明确标注铅踝“窗外雪啸”、PhonoR-0“咒文共鸣”为部分覆盖，未用虚构状态补齐。实际 Safari 页面已验证混合产线独立选择、30 天 × 100 次固定种子快进、收取记录和导出入口；本地 HTTP `/api/simulate` 返回离散事件结果。
