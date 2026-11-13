"""把集中度不确定性分析结果渲染为规划会可直接阅读的中文说明。"""


def _fmt(value, digits=6):
    if value is None:
        return '（未定义）'
    return ('%%.%df' % digits) % value


def _pct(value, digits=2):
    if value is None:
        return '（未定义）'
    return ('%%.%df%%%%' % digits) % (value * 100)


def _choices_text(choices):
    return '，'.join('%s=%s' % (group, option) for group, option in sorted(choices.items()))


def render_explanation(result):
    lines = []
    lines.append('# 经费集中度不确定性说明（供规划会）')
    lines.append('')
    lines.append('## 一句话结论')
    lines.append('')
    years = result['years']
    if not years:
        lines.append('数据中没有经费年份，无法计算集中度。')
    for year in years:
        entry = result['range'][year]
        dist = result['weighted_distribution'][year]
        if entry['hhi'] is None:
            lines.append('- %s 年：所有情景下总额为零或 HHI 未定义，集中度无法给出。' % year)
            continue
        low = entry['hhi']['min']['value']
        high = entry['hhi']['max']['value']
        if low == high:
            lines.append('- %s 年：全部可行情景的 HHI 一致为 %s，待审归属不影响该年集中度。'
                         % (year, _fmt(low)))
        else:
            lines.append(
                '- %s 年：HHI 在可行情景间为 %s ~ %s（按上游相对权重的加权均值 %s），'
                '归属未确认前不应把单一确定数字当成事实。'
                % (year, _fmt(low), _fmt(high), _fmt(dist['mean'])))
    lines.append('')
    lines.append('## 口径与已通过的检查')
    lines.append('')
    lines.append('- 固定归属保持不变；每个待审组整体选择一个完整方案；跨组互斥方案不同时出现。')
    lines.append('- 每一合法情景中每笔金额恰好归给一家机构，逐年总额与原始明细一致（最大偏差 %g 万元）。'
                 % result['checks']['amount_conservation']['max_abs_deviation'])
    lines.append('- parent_hint 仅作为线索保留，未触发任何机构合并。')
    lines.append('- 跨组方案落到同一机构时，HHI 在合并后的完整世界上计算，不是逐组算完再相加。')
    lines.append('- %s。' % result['scenario_space']['weight_normalization'])
    lines.append('')
    lines.append('## 情景空间')
    lines.append('')
    space = result['scenario_space']
    if space['mode'] == 'exact':
        lines.append('- 组合空间 %d 个，互斥排除 %d 个，精确枚举全部 %d 个可行情景。'
                     % (space['product_space'], space['excluded_by_incompatibility'], space['feasible']))
    else:
        lines.append('- 组合空间 %d 个，超过枚举上限，采用有种子的受约束抽样：种子 %d，抽取 %d 次，'
                     '因互斥拒绝 %d 次，覆盖 %d 个不同可行情景（上限 %d）。'
                     % (space['product_space'], space['seed'], space['draws'],
                        space['rejected_incompatible'], space['unique_feasible_found'], space['sample_limit']))
        lines.append('- 可行空间未完全探索，分布为样本内归一；未覆盖情景可能使范围进一步扩大。')
    lines.append('- 抽样（如有）以组级方案组合为单位整体抽取并校验互斥，没有逐条记录独立抽样后拼接。')
    lines.append('')
    lines.append('## 情景明细')
    lines.append('')
    for scenario in result['scenarios']:
        lines.append('### %s：%s' % (scenario['id'], _choices_text(scenario['choices'])))
        lines.append('')
        lines.append('- 相对权重 %g，归一后 %s。' % (scenario['weight'], _pct(scenario['normalized_weight'])))
        for year in years:
            metrics = scenario['years'][year]
            if metrics['hhi'] is None:
                lines.append('- %s 年：总额 %g 万元，HHI 未定义（总额为零）。' % (year, metrics['total']))
                continue
            top3 = '，'.join('%s %s' % (item['institution'], _pct(item['share'])) for item in metrics['top3'])
            combined = sum(item['share'] for item in metrics['top3'])
            lines.append('- %s 年：HHI %s；头部三家合计 %s（%s）。'
                         % (year, _fmt(metrics['hhi']), _pct(combined), top3))
        lines.append('')
    lines.append('## 按给定权重的情景分布')
    lines.append('')
    lines.append('- %s。' % result['weighted_distribution_note'])
    for year in years:
        dist = result['weighted_distribution'][year]
        lines.append('- %s 年：加权均值 %s，p10 %s，p50 %s，p90 %s。'
                     % (year, _fmt(dist['mean']), _fmt(dist['p10']), _fmt(dist['p50']), _fmt(dist['p90'])))
    lines.append('')
    lines.append('## 哪些待审组最影响结论')
    lines.append('')
    for year in years:
        ranking = result['group_influence'][year]
        if not ranking:
            continue
        lines.append('- %s 年：' % year)
        for item in ranking:
            options_text = '，'.join(
                '%s→条件均值 %s（条件权重 %s）'
                % (option['option'], _fmt(option['conditional_mean_hhi']), _pct(option['conditional_weight']))
                for option in item['options'])
            lines.append('  - %s：条件均值极差 %s；%s。' % (item['group'], _fmt(item['hhi_spread']), options_text))
    lines.append('')
    lines.append('固定某组方案后可用 `--fix 组=方案` 重新计算，输出中的 fixes 字段会记录所固定的选择。')
    lines.append('')
    if 'bootstrap' in result:
        boot = result['bootstrap']
        lines.append('## 资助记录抽样误差（与归属情景不确定性分列）')
        lines.append('')
        lines.append('- %s。' % boot['resampling_unit'])
        lines.append('- 复制次数 %d，种子 %d；%s。' % (boot['replicates'], boot['seed'], boot['interpretation']))
        for year in years:
            band = boot['weighted_mean_hhi'][year]
            lines.append('- %s 年加权均值 HHI 的抽样区间：p2.5 %s，p50 %s，p97.5 %s（有效复制 %d 次）。'
                         % (year, _fmt(band['p2.5']), _fmt(band['p50']), _fmt(band['p97.5']), band['n']))
        lines.append('')
    lines.append('## 使用注意')
    lines.append('')
    lines.append('- 权重是上游相对可信权重，不是校准概率；加权分布只用于展示敏感性，不能当成发生概率。')
    lines.append('- 归属确认前，会上应展示范围与最敏感待审组，而不是单一确定数字。')
    lines.append('- 本分析不写回上游身份数据，不修改任何机构归属。')
    lines.append('')
    return '\n'.join(lines)
