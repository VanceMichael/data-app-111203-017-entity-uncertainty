"""上游候选归属交换文件的加载与校验。

只读取 data/linkage_options.json 这类交换文件，不做名称匹配，也不维护机构主数据。
校验规则：方案覆盖、重复归属、负权重、互斥引用完整性。
"""
import hashlib
import json
import math
from pathlib import Path

SCHEMA_VERSION = 1


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('归属文件存在重复键：' + str(key))
        result[key] = value
    return result


def _require_text(value, label):
    if not isinstance(value, str) or not value:
        raise ValueError('归属文件字段应为非空字符串：' + label)
    return value


def _require_weight(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('权重应为数值：' + label)
    weight = float(value)
    if not math.isfinite(weight):
        raise ValueError('权重不是有限数：' + label)
    if weight < 0:
        raise ValueError('负权重不允许：' + label)
    return weight


def _require_assignments(value, label):
    if not isinstance(value, dict) or not value:
        raise ValueError('方案归属应为非空映射：' + label)
    assignments = {}
    for record, institution in value.items():
        _require_text(record, label + ' 记录键')
        _require_text(institution, label + ' 机构值')
        assignments[record] = institution
    return assignments


def load_linkage(path):
    """读取并校验候选归属文件，返回规范化结构。

    返回 {'fixed': {记录: 机构}, 'groups': [...], 'incompatible': [((组,方案),(组,方案))...]}，
    组与组内方案均按标识排序，保证后续结果与文件内书写顺序无关。
    """
    try:
        raw = json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as error:
        raise ValueError('归属文件不是合法 JSON：' + str(error)) from None
    if not isinstance(raw, dict):
        raise ValueError('归属文件顶层应为对象')
    if raw.get('schema_version') != SCHEMA_VERSION:
        raise ValueError('归属文件 schema_version 应为 %d' % SCHEMA_VERSION)

    fixed_raw = raw.get('fixed_assignments')
    if not isinstance(fixed_raw, dict):
        raise ValueError('fixed_assignments 应为映射')
    fixed = {}
    for record, institution in fixed_raw.items():
        _require_text(record, 'fixed_assignments 记录键')
        _require_text(institution, 'fixed_assignments 机构值')
        fixed[record] = institution

    groups_raw = raw.get('groups')
    if not isinstance(groups_raw, list):
        raise ValueError('groups 应为列表')
    groups = []
    group_records = {}
    claimed = set()
    for position, group_raw in enumerate(groups_raw):
        label = 'groups[%d]' % position
        if not isinstance(group_raw, dict):
            raise ValueError(label + ' 应为对象')
        group_id = _require_text(group_raw.get('id'), label + '.id')
        options_raw = group_raw.get('options')
        if not isinstance(options_raw, list) or not options_raw:
            raise ValueError('待审组没有候选方案：' + group_id)
        options = []
        seen_options = set()
        for option_raw in options_raw:
            if not isinstance(option_raw, dict):
                raise ValueError('方案应为对象：' + group_id)
            option_id = _require_text(option_raw.get('id'), group_id + ' 方案 id')
            if option_id in seen_options:
                raise ValueError('组内方案标识重复：' + group_id + '/' + option_id)
            seen_options.add(option_id)
            weight = _require_weight(option_raw.get('weight'), group_id + '/' + option_id)
            assignments = _require_assignments(option_raw.get('assignments'), group_id + '/' + option_id)
            options.append({'id': option_id, 'weight': weight, 'assignments': assignments})
        covered = set(options[0]['assignments'])
        for option in options[1:]:
            if set(option['assignments']) != covered:
                raise ValueError('方案覆盖不一致：' + group_id + ' 内各方案必须覆盖同一组记录')
        if not any(option['weight'] > 0 for option in options):
            raise ValueError('待审组权重全为零，无法归一：' + group_id)
        if group_id in group_records:
            raise ValueError('待审组标识重复：' + group_id)
        overlap = covered & claimed
        if overlap:
            raise ValueError('重复归属：记录出现在多个待审组：' + ','.join(sorted(overlap)))
        duplicate_fixed = covered & set(fixed)
        if duplicate_fixed:
            raise ValueError('重复归属：记录同时出现在固定归属与待审组：' + ','.join(sorted(duplicate_fixed)))
        group_records[group_id] = covered
        claimed |= covered
        groups.append({'id': group_id, 'options': sorted(options, key=lambda option: option['id'])})
    groups.sort(key=lambda group: group['id'])

    incompatible_raw = raw.get('incompatible_options', [])
    if not isinstance(incompatible_raw, list):
        raise ValueError('incompatible_options 应为列表')
    option_index = {(group['id'], option['id']) for group in groups for option in group['options']}
    incompatible = []
    seen_pairs = set()
    for pair in incompatible_raw:
        if (not isinstance(pair, list) or len(pair) != 2 or
                any(not isinstance(endpoint, list) or len(endpoint) != 2 for endpoint in pair)):
            raise ValueError('互斥项应为 [组,方案] 对')
        endpoints = []
        for group_id, option_id in pair:
            _require_text(group_id, '互斥组标识')
            _require_text(option_id, '互斥方案标识')
            if (group_id, option_id) not in option_index:
                raise ValueError('互斥引用了不存在的方案：%s/%s' % (group_id, option_id))
            endpoints.append((group_id, option_id))
        if endpoints[0] == endpoints[1]:
            raise ValueError('互斥项两端相同：%s/%s' % endpoints[0])
        if endpoints[0][0] == endpoints[1][0]:
            raise ValueError('同组方案天然互斥，无需声明：' + endpoints[0][0])
        canonical = tuple(sorted(endpoints))
        if canonical not in seen_pairs:
            seen_pairs.add(canonical)
            incompatible.append(canonical)
    incompatible.sort()

    return {'fixed': fixed, 'groups': groups, 'incompatible': incompatible}


def linkage_fingerprint(spec):
    payload = json.dumps(spec, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()
