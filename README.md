# entity-uncertainty

科研协作分析整理多来源机构名称和项目经费，提供按来源的金额核对与登记码覆盖率。

## 使用

运行需要 Python 3.11 或更新版本，没有第三方运行依赖。数据在本地处理，不请求外部接口。

```bash
python3 -m analysis_app summary
python3 -m analysis_app summary --input data/observations.csv --output output/summary.json
python3 -m analysis_app concentration --output output/concentration.json --explain output/concentration_explanation.md
```

`concentration` 在候选归属情景上分析机构经费集中度（HHI 与头部三家份额）的不确定性，口径见 `docs/concentration.md`。

标准输出是完整 JSON，输出文件使用临时文件原子替换；失败退出码为 2，不覆盖既有结果。空数据集保留零计数与空分组，缺失数值不进入数值分母。数据指纹由按 observation_id 排序后的解析记录计算。

## 验证与容器

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q analysis_app
docker build -t entity-uncertainty .
docker run --rm entity-uncertainty
```

容器内也可执行 `python -m unittest discover -s tests -v`。镜像构建阶段取得 Python 镜像，产品启动、测试和演示均无需下载。小规模样例的完整单元测试和 summary 可以连续执行，不需要等待定时任务。

## 代码与数据

- `analysis_app/io.py`：有类型的 CSV 读取、完整性校验及内容指纹。
- `analysis_app/schema.py`：字段类型、主体与聚合维度。
- `analysis_app/domain.py`：当前业务核算函数。
- `analysis_app/summary.py`：确定性的分组与数值口径。
- `analysis_app/linkage.py`：候选归属交换文件的加载与校验。
- `analysis_app/concentration.py`：归属情景上的集中度不确定性分析。
- `analysis_app/explain.py`：分析结果的中文说明渲染。
- `analysis_app/cli.py`：本地命令及原子输出。
- `docs/data.md`：数据契约。
- `docs/concentration.md`：集中度不确定性口径。

演示数据全部为本地合成，不对应现实机构、设备或人员；不能用来推断真实业务效果。
