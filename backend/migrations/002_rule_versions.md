# 002 规则版本与运行快照

分流规则改为按版本管理，验收成绩按规则版本分开计算。

- 新增 `rule_versions` 表：规则版本号唯一，（生效时刻， 签发序号）联合唯一约束 `uq_rule_moment_seq` 防止版本重叠；发布为单事务，中断时整体回滚，旧版本保持可查。
- `runs` 表新增 `rule_snapshot` JSON 列：提交验收时冻结当时已发布的全部规则版本，后台计算与中断重跑只读快照，不重复计分。既有库由应用启动时的 `ALTER TABLE runs ADD COLUMN IF NOT EXISTS rule_snapshot JSON` 补列，新库由 `create_all` 一并建出。
- `datasets.rows` 内的来信记录新增 `arrived_at` 字段（JSON 内字段，无需改表）：到件时间统一存带 `+00:00` 的 UTC ISO，导入时不带时区按北京时间（UTC+8）计。
- 历史运行没有规则快照，结果页回退显示当时的运行参数；历史批次缺少到件时间，不能用于新的验收运行。
