# 集中度不确定性分析

在候选归属情景上计算机构经费集中度（HHI 与头部三家份额），回答"归属还没审完时，集中度数字有多不确定"。本功能只做分析：不建设名称匹配，不维护机构主数据，不写回上游身份数据。

```bash
python3 -m analysis_app concentration
python3 -m analysis_app concentration --output output/concentration.json --explain output/concentration_explanation.md
python3 -m analysis_app concentration --fix group-b=shared          # 固定某组方案后重算，可重复
python3 -m analysis_app concentration --sample-limit 5000 --seed 7  # 大空间改为有种子抽样
python3 -m analysis_app concentration --bootstrap 1000              # 追加资助记录抽样误差
```

## 输入与约束

读取经费明细（`data/observations.csv`）与候选归属交换文件（`data/linkage_options.json`，格式见 data.md）。规则：

- 固定归属保持不变；每个待审组整体选择一个完整方案，不拆分方案内的记录。
- `incompatible_options` 列出的跨组方案对不能同时出现。
- 任何合法情景中每笔金额恰好归给一家机构，逐年总额与原始明细一致（结果 `checks.amount_conservation` 给出逐年核对）。
- `parent_hint` 只是线索，不触发任何合并。
- 跨组方案落到同一机构时，HHI 在合并后的完整世界上计算，不逐组算完再相加。

## 载入时校验（任一不满足即失败，退出码 2）

- 方案覆盖：组内各方案覆盖同一组记录；每条观测记录恰好被固定归属或一个待审组覆盖；不允许引用观测中不存在的记录。
- 重复归属：记录不能同时出现在固定归属与待审组、或两个待审组中；JSON 重复键同样拒绝。
- 负权重：weight 必须是非负有限数；每个待审组至少一个方案权重为正。
- 互斥引用：必须指向存在的组与方案，且两端不同组。
- 互斥后无可行组合、或可行情景权重之和为零时拒绝分析。

## 指标

按年计算：HHI = Σ（机构年经费份额）²；头部三家份额（并列按机构标识排序取前三）。某年总额为零时该年 HHI 记为 null 并说明，不当作零。

## 情景空间：枚举与抽样

组合空间不超过 `--sample-limit`（默认 10000）时精确枚举全部可行情景。超过时按组级方案组合做有种子的均匀抽样，整体校验互斥，不逐条记录（逐边）独立抽样后拼接世界。抽样模式在 `scenario_space` 披露：种子、抽取次数、互斥拒绝次数、覆盖的不同情景数、`coverage_complete=false` 及"可行空间未完全探索，分布为样本内归一"。

## 权重口径

情景权重 = 各组所选方案 weight 之积，在可行情景集合上归一（互斥排除后重新归一）。weight 是上游相对可信权重，不是校准概率；`weighted_distribution` 的均值与分位数只描述归属情景不确定性，不是抽样置信区间。

## 敏感性与固定重算

`group_influence` 按年给出每个待审组的条件均值极差（固定该组某一方案后，对其余组的合法组合按权重归一求条件均值，取各方案条件均值的最大差），按极差降序排列，用于定位最影响结论的待审组。`--fix 组=方案` 固定某组方案后重新计算全部结果，`fixes` 字段记录所固定的选择。

## 两类不确定性分列

归属情景不确定性（上节）与资助记录本身的抽样误差分开呈现。`--bootstrap N` 以 record（经费记录）为重采样单位，整记录及其全部观测行一起抽取，每次复制重新计算全部合法情景的 HHI；输出每个情景各自的抽样区间（条件于该情景）和加权均值 HHI 的抽样区间（条件于给定权重）。这些区间不与情景分位数混合，也不是无条件置信区间。

## 输出

标准输出为完整 JSON；`--output` 原子写入同一 JSON；`--explain` 生成供规划会阅读的中文说明。主要字段：`checks`（校验与金额守恒）、`scenario_space`（枚举/抽样披露与权重归一口径）、`scenarios`（每情景逐年 HHI 与头部三家）、`range`（逐年 HHI 与第一名份额范围）、`weighted_distribution`（按给定权重的分布）、`group_influence`（待审组敏感性排序）、`bootstrap`（可选，抽样误差）。
