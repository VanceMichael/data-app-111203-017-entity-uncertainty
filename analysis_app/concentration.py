"""集中度不确定性分析：在候选归属情景上计算 HHI 与头部三家份额。

原则：
- 固定归属保持不变；每个待审组整体选择一个方案；互斥方案不同时出现。
- 不逐条记录独立抽样再拼接世界；抽样单位是"组级方案组合"整体。
- 跨组方案落到同一机构时，HHI 在合并后的完整世界上计算，不逐组算完再相加。
- weight 是上游相对可信权重，不是校准概率；情景分布的分位数不是置信区间。
- parent_hint 不参与任何合并。
"""
import itertools
import math
import random

from .io import fingerprint
from .linkage import linkage_fingerprint
from .schema import PRODUCT, UNIT

DEFAULT_SEED = 20261113
DEFAULT_BOOTSTRAP_SEED = 20261113
DEFAULT_SAMPLE_LIMIT = 10000
SCHEMA_VERSION = 1

WEIGHT_NOTE = '情景权重=各组所选方案 weight 之积，在可行情景集合上归一；weight 为上游相对可信权重，不是校准概率'
QUANTILE_NOTE = '情景分布分位数仅描述候选归属不确定性，不是抽样置信区间'
BOOTSTRAP_UNIT_NOTE = '重采样单位为 record（整记录及其全部观测行一起抽取），每次复制重新计算全部合法情景'


def _world_metrics(rows, years, world):
    """在合并后的完整归属世界上按年计算 HHI 与头部三家份额。年份键为字符串。"""
    per_year_inst = {year: {} for year in years}
    for row in rows:
        institution = world[row['record']]
        bucket = per_year_inst[str(row['year'])]
        bucket[institution] = bucket.get(institution, 0.0) + row['amount']
    metrics = {}
    for year in years:
        amounts = per_year_inst[year]
        total = math.fsum(amounts.values())
        if total == 0:
            metrics[year] = {'total': total, 'institutions': len(amounts), 'hhi': None, 'top3': []}
            continue
        ranking = sorted(amounts.items(), key=lambda item: (-item[1], item[0]))
        hhi = math.fsum((amount / total) ** 2 for amount in amounts.values())
        top3 = [{'institution': institution, 'amount': amount, 'share': amount / total}
                for institution, amount in ranking[:3]]
        metrics[year] = {'total': total, 'institutions': len(amounts), 'hhi': hhi, 'top3': top3}
    return metrics


def _check_coverage(records, spec):
    observed = {row['record'] for row in records}
    referenced = set(spec['fixed'])
    for group in spec['groups']:
        referenced |= set(group['options'][0]['assignments'])
    unknown = referenced - observed
    if unknown:
        raise ValueError('归属引用了观测中不存在的记录：' + ','.join(sorted(unknown)))
    uncovered = observed - referenced
    if uncovered:
        raise ValueError('方案覆盖不足：以下记录既无固定归属也不在任何待审组：' + ','.join(sorted(uncovered)))


def _apply_fixes(spec, fixes):
    groups = {group['id']: group for group in spec['groups']}
    for group_id, option_id in fixes:
        if group_id not in groups:
            raise ValueError('固定方案引用了不存在的待审组：' + group_id)
        matched = [option for option in groups[group_id]['options'] if option['id'] == option_id]
        if not matched:
            raise ValueError('固定方案引用了不存在的方案：%s/%s' % (group_id, option_id))
        groups[group_id] = {'id': group_id, 'options': matched}
    return [groups[group['id']] for group in spec['groups']]


def _is_feasible(choices, incompatible):
    chosen = set(choices)
    return all(not (first in chosen and second in chosen) for first, second in incompatible)


def _build_scenarios(groups, incompatible, sample_limit, seed):
    """返回 (情景列表, 空间披露)。每个情景是一整组组级方案选择，不逐边拼接。"""
    product_space = 1
    for group in groups:
        product_space *= len(group['options'])
    option_lists = [[(group['id'], option) for option in group['options']] for group in groups]

    def make_scenario(picked):
        choices = tuple((group_id, option['id']) for group_id, option in picked)
        weight = 1.0
        assignments = {}
        for _, option in picked:
            weight *= option['weight']
            assignments.update(option['assignments'])
        return {'choices': choices, 'weight': weight, 'assignments': assignments}

    if product_space <= sample_limit:
        scenarios = []
        excluded = 0
        for picked in itertools.product(*option_lists):
            choices = tuple((group_id, option['id']) for group_id, option in picked)
            if _is_feasible(choices, incompatible):
                scenarios.append(make_scenario(list(picked)))
            else:
                excluded += 1
        space = {'mode': 'exact', 'product_space': product_space,
                 'excluded_by_incompatibility': excluded, 'coverage_complete': True}
    else:
        rng = random.Random(seed)
        max_draws = sample_limit * 50
        draws = 0
        rejected = 0
        seen = {}
        while draws < max_draws and len(seen) < sample_limit:
            draws += 1
            picked = [rng.choice(options) for options in option_lists]
            choices = tuple((group_id, option['id']) for group_id, option in picked)
            if not _is_feasible(choices, incompatible):
                rejected += 1
                continue
            if choices not in seen:
                seen[choices] = make_scenario(picked)
        scenarios = [seen[key] for key in sorted(seen)]
        space = {'mode': 'sampled', 'product_space': product_space, 'seed': seed,
                 'draws': draws, 'rejected_incompatible': rejected,
                 'unique_feasible_found': len(scenarios), 'sample_limit': sample_limit,
                 'coverage_complete': False,
                 'sampling_note': '按组级方案组合均匀抽取并整体校验互斥，未逐边独立抽样；可行空间未完全探索，分布为样本内归一'}
    scenarios.sort(key=lambda scenario: scenario['choices'])
    if not scenarios:
        raise ValueError('互斥约束排除了全部组合，无可行情景')
    total_weight = math.fsum(scenario['weight'] for scenario in scenarios)
    if total_weight <= 0:
        raise ValueError('可行情景的权重之和为零，无法归一')
    for index, scenario in enumerate(scenarios, 1):
        scenario['id'] = 'S%d' % index
        scenario['normalized_weight'] = scenario['weight'] / total_weight
    return scenarios, space


def _weighted_quantile(weighted_values, quantile):
    items = sorted(weighted_values)
    cumulative = 0.0
    for value, weight in items:
        cumulative += weight
        if cumulative >= quantile - 1e-12:
            return value
    return items[-1][0]


def _percentile(sorted_values, fraction):
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * fraction
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return sorted_values[low]
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (rank - low)


def _scenario_rows(scenarios):
    rows = []
    for scenario in scenarios:
        row = {'id': scenario['id'],
               'choices': {group: option for group, option in scenario['choices']},
               'weight': scenario['weight'],
               'normalized_weight': scenario['normalized_weight'],
               'years': scenario['metrics']}
        rows.append(row)
    return rows


def _range_section(scenarios, years):
    section = {}
    for year in years:
        valid = [(scenario['metrics'][year]['hhi'], scenario['id']) for scenario in scenarios
                 if scenario['metrics'][year]['hhi'] is not None]
        top1 = [(scenario['metrics'][year]['top3'][0]['share'], scenario['id'])
                for scenario in scenarios if scenario['metrics'][year]['top3']]
        entry = {}
        if valid:
            low = min(valid)
            high = max(valid)
            entry['hhi'] = {
                'min': {'value': low[0], 'scenarios': sorted(sid for value, sid in valid if value == low[0])},
                'max': {'value': high[0], 'scenarios': sorted(sid for value, sid in valid if value == high[0])}}
        else:
            entry['hhi'] = None
        if top1:
            entry['top1_share'] = {'min': min(top1)[0], 'max': max(top1)[0]}
        else:
            entry['top1_share'] = None
        section[year] = entry
    return section


def _distribution_section(scenarios, years):
    section = {}
    for year in years:
        weighted = [(scenario['metrics'][year]['hhi'], scenario['normalized_weight'])
                    for scenario in scenarios if scenario['metrics'][year]['hhi'] is not None]
        if not weighted:
            section[year] = {'mean': None, 'p10': None, 'p50': None, 'p90': None}
            continue
        mean = math.fsum(value * weight for value, weight in weighted)
        section[year] = {'mean': mean,
                         'p10': _weighted_quantile(weighted, 0.10),
                         'p50': _weighted_quantile(weighted, 0.50),
                         'p90': _weighted_quantile(weighted, 0.90)}
    return section


def _influence_section(scenarios, groups, years):
    section = {}
    for year in years:
        ranking = []
        for group in groups:
            per_option = []
            means = []
            for option in group['options']:
                subset = [scenario for scenario in scenarios
                          if (group['id'], option['id']) in scenario['choices']]
                if not subset:
                    per_option.append({'option': option['id'], 'conditional_weight': 0.0,
                                       'conditional_mean_hhi': None})
                    continue
                weight_sum = math.fsum(scenario['normalized_weight'] for scenario in subset)
                valued = [scenario for scenario in subset if scenario['metrics'][year]['hhi'] is not None]
                if valued:
                    mean = math.fsum(scenario['metrics'][year]['hhi'] * scenario['normalized_weight']
                                     for scenario in valued) / math.fsum(
                                         scenario['normalized_weight'] for scenario in valued)
                else:
                    mean = None
                per_option.append({'option': option['id'], 'conditional_weight': weight_sum,
                                   'conditional_mean_hhi': mean})
                if mean is not None:
                    means.append(mean)
            spread = (max(means) - min(means)) if means else None
            ranking.append({'group': group['id'], 'hhi_spread': spread, 'options': per_option})
        ranking.sort(key=lambda item: (-(item['hhi_spread'] or 0.0), item['group']))
        section[year] = ranking
    return section


def _bootstrap(records, scenarios, years, replicates, seed):
    """资助记录抽样误差：整记录重采样，每次复制重算全部合法情景，与情景不确定性分列。"""
    record_years = {}
    for row in records:
        bucket = record_years.setdefault(row['record'], {year: 0.0 for year in years})
        bucket[str(row['year'])] += row['amount']
    record_ids = sorted(record_years)
    rng = random.Random(seed)
    samples = {scenario['id']: {year: [] for year in years} for scenario in scenarios}
    weighted_mean = {year: [] for year in years}
    for _ in range(replicates):
        drawn = [record_ids[rng.randrange(len(record_ids))] for _ in record_ids] if record_ids else []
        for scenario in scenarios:
            world = scenario['world']
            per_year_inst = {year: {} for year in years}
            for record in drawn:
                institution = world[record]
                for year in years:
                    amount = record_years[record][year]
                    if amount:
                        bucket = per_year_inst[year]
                        bucket[institution] = bucket.get(institution, 0.0) + amount
            for year in years:
                total = math.fsum(per_year_inst[year].values())
                if total == 0:
                    continue
                hhi = math.fsum((amount / total) ** 2 for amount in per_year_inst[year].values())
                samples[scenario['id']][year].append(hhi)
        for year in years:
            terms = []
            for scenario in scenarios:
                values = samples[scenario['id']][year]
                if len(values) > len(weighted_mean[year]):
                    terms.append((values[-1], scenario['normalized_weight']))
            if len(terms) == len(scenarios):
                weighted_mean[year].append(math.fsum(value * weight for value, weight in terms))

    def band(values):
        ordered = sorted(values)
        return {'n': len(ordered),
                'p2.5': _percentile(ordered, 0.025),
                'p50': _percentile(ordered, 0.50),
                'p97.5': _percentile(ordered, 0.975)}

    per_scenario = []
    for scenario in scenarios:
        per_scenario.append({'scenario': scenario['id'],
                             'years': {year: band(samples[scenario['id']][year]) for year in years}})
    return {'replicates': replicates, 'seed': seed, 'resampling_unit': BOOTSTRAP_UNIT_NOTE,
            'per_scenario': per_scenario,
            'weighted_mean_hhi': {year: band(weighted_mean[year]) for year in years},
            'interpretation': '资助记录抽样误差（条件于情景与给定权重），与归属情景不确定性分列，不是无条件置信区间'}


def analyze(records, spec, fixes=(), sample_limit=DEFAULT_SAMPLE_LIMIT, seed=DEFAULT_SEED,
            bootstrap_replicates=0, bootstrap_seed=DEFAULT_BOOTSTRAP_SEED):
    """对候选归属情景做集中度不确定性分析，返回可 JSON 序列化的结果。"""
    fixes = tuple(fixes)
    _check_coverage(records, spec)
    groups = _apply_fixes(spec, fixes)
    scenarios, space = _build_scenarios(groups, spec['incompatible'], sample_limit, seed)

    ordered = sorted(records, key=lambda row: row['observation_id'])
    years = [str(year) for year in sorted({row['year'] for row in ordered})]
    baseline = {year: math.fsum(row['amount'] for row in ordered if str(row['year']) == year)
                for year in years}

    max_deviation = 0.0
    for scenario in scenarios:
        world = dict(spec['fixed'])
        world.update(scenario['assignments'])
        scenario['world'] = world
        scenario['metrics'] = _world_metrics(ordered, years, world)
        for year in years:
            deviation = abs(scenario['metrics'][year]['total'] - baseline[year])
            max_deviation = max(max_deviation, deviation)

    result = {
        'product': PRODUCT,
        'schema_version': SCHEMA_VERSION,
        'analysis': 'concentration_uncertainty',
        'unit': UNIT,
        'input_fingerprint': fingerprint(ordered),
        'linkage_fingerprint': linkage_fingerprint(spec),
        'fixes': [{'group': group, 'option': option} for group, option in fixes],
        'checks': {
            'coverage': 'ok',
            'duplicate_attribution': 'ok',
            'negative_weights': 'ok',
            'feasible_combinations': len(scenarios),
            'amount_conservation': {
                'ok': max_deviation <= 1e-9,
                'max_abs_deviation': max_deviation,
                'year_totals': baseline,
                'note': '每一合法情景中每笔金额恰好归给一家机构，逐年总额与原始明细一致'},
            'parent_hint_used': False,
            'notes': ['parent_hint 仅视为线索，未触发任何合并',
                      '跨组方案落到同一机构时，HHI 在合并后的完整世界上计算，未逐组相加'],
        },
        'scenario_space': dict(space,
                               groups=[{'id': group['id'],
                                        'options': [{'id': option['id'], 'weight': option['weight']}
                                                    for option in group['options']]}
                                       for group in groups],
                               incompatible_pairs=[list(pair) for pair in spec['incompatible']],
                               feasible=len(scenarios),
                               weight_normalization=WEIGHT_NOTE),
        'years': years,
        'scenarios': _scenario_rows(scenarios),
        'range': _range_section(scenarios, years),
        'weighted_distribution': _distribution_section(scenarios, years),
        'weighted_distribution_note': QUANTILE_NOTE,
        'group_influence': _influence_section(scenarios, groups, years),
    }
    if bootstrap_replicates > 0:
        if not records:
            raise ValueError('空数据集无法 bootstrap')
        result['bootstrap'] = _bootstrap(ordered, scenarios, years, bootstrap_replicates, bootstrap_seed)
    for scenario in scenarios:
        scenario.pop('world', None)
    return result
