# 数据契约

科研协作分析整理多来源机构名称和项目经费，提供按来源的金额核对与登记码覆盖率。

主测量 `amount` 的单位为万元，主体字段是 `record`，核算维度是 `source`。`observation_id` 是文件内唯一观测编号，主体允许重复观测。数值只接受有限值；空单元格解析为 None，不能直接当成零。额外列不进入当前核算。

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `observation_id` | str | 必填 |
| `record` | str | 必填 |
| `source` | str | 必填 |
| `name` | str | 必填 |
| `city` | str | 必填 |
| `amount` | float | 必填 |
| `year` | int | 必填 |
| `registry` | str | 允许空值，空值不是零 |
| `parent_hint` | str | 允许空值，空值不是零 |

时间字段 day、week、tick、hour、minute、cycle、start_day、reported_day、known_at、visible_at、opened、observed 均以各字段名所述的相对时间单位表示整数；不同字段并不必然代表同一种时间。缺少的登记码与浓度等信息保持为空。示例只表达产品数据结构，不能代替实际调查资料。

## 业务字段语义

amount 为万元。registry 是机构登记码，可空；空值之间不是匹配证据。parent_hint 是上级组织线索，不是合并指令。year 为经费年份，source 为数据来源，record 是来源记录键。

## 候选归属交换格式

`data/linkage_options.json` 保存上游候选归属。fixed_assignments 为记录到机构的确定映射，groups 内每个方案完整覆盖该组记录，weight 为相对可信权重；incompatible_options 列出禁止同时选用的组与方案对。该文件只供分析使用，不表示机构登记码已经修改。基于该文件的集中度不确定性分析见 `docs/concentration.md`。
