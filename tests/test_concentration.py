import copy
import csv
import json
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from analysis_app.concentration import analyze
from analysis_app.io import load_records
from analysis_app.linkage import load_linkage
from analysis_app.schema import FIELDS


def make_row(obs_id, record, amount, year=2024, parent_hint=None):
    return {'observation_id': obs_id, 'record': record, 'source': 'S0',
            'name': '名称' + record, 'city': 'C0', 'amount': float(amount),
            'year': year, 'registry': None, 'parent_hint': parent_hint}


def hand_rows():
    # 可手算夹具：F1→X 30，F2→Y 30，待审 P1=10、P2=20（g1），Q1=10（g2），总额 100
    return [make_row('obs-f1', 'F1', 30), make_row('obs-f2', 'F2', 30),
            make_row('obs-p1', 'P1', 10), make_row('obs-p2', 'P2', 20),
            make_row('obs-q1', 'Q1', 10)]


def hand_spec():
    return {'fixed': {'F1': 'X', 'F2': 'Y'},
            'groups': [
                {'id': 'g1', 'options': [
                    {'id': 'o1', 'weight': 1.0, 'assignments': {'P1': 'X', 'P2': 'Y'}},
                    {'id': 'o2', 'weight': 3.0, 'assignments': {'P1': 'X', 'P2': 'X'}}]},
                {'id': 'g2', 'options': [
                    {'id': 'p1', 'weight': 1.0, 'assignments': {'Q1': 'Y'}},
                    {'id': 'p2', 'weight': 1.0, 'assignments': {'Q1': 'Z'}}]}],
            'incompatible': [(('g1', 'o2'), ('g2', 'p2'))]}


def write_json(directory, payload, name='linkage.json'):
    path = Path(directory) / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return path


def linkage_payload(spec):
    return {'schema_version': 1, 'fixed_assignments': spec['fixed'],
            'groups': [{'id': group['id'], 'options': [
                {'id': option['id'], 'weight': option['weight'],
                 'assignments': option['assignments']} for option in group['options']]}
                       for group in spec['groups']],
            'incompatible_options': [[list(endpoint) for endpoint in pair]
                                     for pair in spec['incompatible']]}


class HandComputedTest(unittest.TestCase):
    """两组交叉情景：HHI、互斥归一、金额守恒全部可手算。"""

    @classmethod
    def setUpClass(cls):
        cls.result = analyze(hand_rows(), hand_spec())

    def test_feasible_set_after_incompatibility(self):
        space = self.result['scenario_space']
        self.assertEqual(space['mode'], 'exact')
        self.assertEqual(space['product_space'], 4)
        self.assertEqual(space['excluded_by_incompatibility'], 1)
        self.assertEqual(space['feasible'], 3)
        choices = [scenario['choices'] for scenario in self.result['scenarios']]
        self.assertNotIn({'g1': 'o2', 'g2': 'p2'}, choices)

    def test_hand_computed_hhi(self):
        # S1=(o1,p1)：X=40,Y=60 → 0.16+0.36=0.52；S2=(o1,p2)：X=40,Y=50,Z=10 → 0.42；
        # S3=(o2,p1)：X=60,Y=40 → 0.52
        expected = {'S1': 0.52, 'S2': 0.42, 'S3': 0.52}
        for scenario in self.result['scenarios']:
            self.assertAlmostEqual(scenario['years']['2024']['hhi'],
                                   expected[scenario['id']], places=12)
            self.assertEqual(scenario['years']['2024']['total'], 100.0)
        top3 = self.result['scenarios'][0]['years']['2024']['top3']
        self.assertEqual([item['institution'] for item in top3], ['Y', 'X'])
        self.assertAlmostEqual(top3[0]['share'], 0.6, places=12)

    def test_weight_normalization_after_exclusion(self):
        # 原始权重 1、1、3（被排除的 3 不参与归一）→ 0.2、0.2、0.6
        normalized = {scenario['id']: scenario['normalized_weight']
                      for scenario in self.result['scenarios']}
        self.assertAlmostEqual(normalized['S1'], 0.2, places=12)
        self.assertAlmostEqual(normalized['S2'], 0.2, places=12)
        self.assertAlmostEqual(normalized['S3'], 0.6, places=12)
        dist = self.result['weighted_distribution']['2024']
        self.assertAlmostEqual(dist['mean'], 0.5, places=12)
        self.assertAlmostEqual(dist['p10'], 0.42, places=12)
        self.assertAlmostEqual(dist['p50'], 0.52, places=12)
        self.assertAlmostEqual(dist['p90'], 0.52, places=12)

    def test_amount_conservation(self):
        conservation = self.result['checks']['amount_conservation']
        self.assertTrue(conservation['ok'])
        self.assertEqual(conservation['year_totals'], {'2024': 100.0})
        self.assertLessEqual(conservation['max_abs_deviation'], 1e-9)

    def test_range(self):
        entry = self.result['range']['2024']['hhi']
        self.assertAlmostEqual(entry['min']['value'], 0.42, places=12)
        self.assertEqual(entry['min']['scenarios'], ['S2'])
        self.assertAlmostEqual(entry['max']['value'], 0.52, places=12)
        self.assertEqual(entry['max']['scenarios'], ['S1', 'S3'])

    def test_group_influence_ranking(self):
        # g1：o1 条件均值 (0.52+0.42)/2=0.47，o2 为 0.52，极差 0.05
        # g2：p1 条件均值 0.52，p2 为 0.42，极差 0.10 → g2 更敏感
        ranking = self.result['group_influence']['2024']
        self.assertEqual([item['group'] for item in ranking], ['g2', 'g1'])
        self.assertAlmostEqual(ranking[0]['hhi_spread'], 0.10, places=12)
        self.assertAlmostEqual(ranking[1]['hhi_spread'], 0.05, places=12)
        g1_options = {option['option']: option for option in ranking[1]['options']}
        self.assertAlmostEqual(g1_options['o1']['conditional_mean_hhi'], 0.47, places=12)
        self.assertAlmostEqual(g1_options['o2']['conditional_mean_hhi'], 0.52, places=12)

    def test_fix_option_recomputes(self):
        fixed = analyze(hand_rows(), hand_spec(), fixes=(('g1', 'o2'),))
        self.assertEqual(len(fixed['scenarios']), 1)
        self.assertEqual(fixed['scenarios'][0]['choices'], {'g1': 'o2', 'g2': 'p1'})
        self.assertAlmostEqual(fixed['scenarios'][0]['normalized_weight'], 1.0, places=12)
        self.assertEqual(fixed['fixes'], [{'group': 'g1', 'option': 'o2'}])

    def test_fix_unknown_option_rejected(self):
        with self.assertRaisesRegex(ValueError, '不存在的方案'):
            analyze(hand_rows(), hand_spec(), fixes=(('g1', 'nope'),))
        with self.assertRaisesRegex(ValueError, '不存在的待审组'):
            analyze(hand_rows(), hand_spec(), fixes=(('g9', 'o1'),))


class BoundaryTest(unittest.TestCase):
    def test_no_pending_groups(self):
        rows = [make_row('obs-f1', 'F1', 30), make_row('obs-f2', 'F2', 30)]
        spec = {'fixed': {'F1': 'X', 'F2': 'Y'}, 'groups': [], 'incompatible': []}
        result = analyze(rows, spec)
        self.assertEqual(len(result['scenarios']), 1)
        self.assertAlmostEqual(result['scenarios'][0]['years']['2024']['hhi'], 0.5, places=12)
        self.assertAlmostEqual(result['scenarios'][0]['normalized_weight'], 1.0, places=12)
        self.assertEqual(result['group_influence']['2024'], [])

    def test_zero_total_year(self):
        rows = [make_row('obs-f1', 'F1', 0), make_row('obs-f2', 'F2', 0)]
        spec = {'fixed': {'F1': 'X', 'F2': 'Y'}, 'groups': [], 'incompatible': []}
        result = analyze(rows, spec)
        metrics = result['scenarios'][0]['years']['2024']
        self.assertIsNone(metrics['hhi'])
        self.assertEqual(metrics['top3'], [])
        self.assertEqual(metrics['total'], 0.0)
        self.assertIsNone(result['range']['2024']['hhi'])
        self.assertIsNone(result['weighted_distribution']['2024']['mean'])
        self.assertTrue(result['checks']['amount_conservation']['ok'])

    def test_empty_dataset(self):
        spec = {'fixed': {}, 'groups': [], 'incompatible': []}
        result = analyze([], spec)
        self.assertEqual(result['years'], [])
        self.assertEqual(len(result['scenarios']), 1)

    def test_all_combinations_excluded(self):
        spec = hand_spec()
        spec['incompatible'] = [(('g1', 'o1'), ('g2', 'p1')), (('g1', 'o1'), ('g2', 'p2')),
                                (('g1', 'o2'), ('g2', 'p1')), (('g1', 'o2'), ('g2', 'p2'))]
        with self.assertRaisesRegex(ValueError, '无可行情景'):
            analyze(hand_rows(), spec)

    def test_parent_hint_does_not_change_result(self):
        base = analyze(hand_rows(), hand_spec())
        hinted = [dict(row, parent_hint='GROUP%d' % (index % 2))
                  for index, row in enumerate(hand_rows())]
        changed = analyze(hinted, hand_spec())
        self.assertFalse(base['checks']['parent_hint_used'])
        for key in ('scenarios', 'range', 'weighted_distribution', 'group_influence'):
            self.assertEqual(base[key], changed[key])

    def test_bootstrap_is_separate_and_reproducible(self):
        plain = analyze(hand_rows(), hand_spec())
        first = analyze(hand_rows(), hand_spec(), bootstrap_replicates=60, bootstrap_seed=99)
        second = analyze(hand_rows(), hand_spec(), bootstrap_replicates=60, bootstrap_seed=99)
        self.assertIn('record', first['bootstrap']['resampling_unit'])
        self.assertEqual(len(first['bootstrap']['per_scenario']), 3)
        self.assertEqual(first['bootstrap'], second['bootstrap'])
        # bootstrap 不改变情景层面的加权分布，两类不确定性分列
        self.assertEqual(plain['weighted_distribution'], first['weighted_distribution'])
        band = first['bootstrap']['weighted_mean_hhi']['2024']
        self.assertEqual(band['n'], 60)
        self.assertLessEqual(band['p2.5'], band['p50'])
        self.assertLessEqual(band['p50'], band['p97.5'])


def sampled_spec():
    groups = []
    for index in range(6):
        record = 'P%d' % index
        groups.append({'id': 'g%d' % index, 'options': [
            {'id': 'a', 'weight': 1.0, 'assignments': {record: 'X'}},
            {'id': 'b', 'weight': 2.0, 'assignments': {record: 'Y'}},
            {'id': 'c', 'weight': 3.0, 'assignments': {record: 'Z'}}]})
    return {'fixed': {'F0': 'X'},
            'groups': groups,
            'incompatible': [(('g0', 'a'), ('g1', 'a'))]}


def sampled_rows():
    rows = [make_row('obs-f0', 'F0', 100)]
    for index in range(6):
        rows.append(make_row('obs-p%d' % index, 'P%d' % index, index + 1))
    return rows


class SamplingTest(unittest.TestCase):
    def test_seeded_sampling_disclosure_and_constraints(self):
        result = analyze(sampled_rows(), sampled_spec(), sample_limit=10, seed=7)
        space = result['scenario_space']
        self.assertEqual(space['mode'], 'sampled')
        self.assertEqual(space['product_space'], 729)
        self.assertEqual(space['seed'], 7)
        self.assertFalse(space['coverage_complete'])
        self.assertIn('sampling_note', space)
        self.assertEqual(space['unique_feasible_found'], len(result['scenarios']))
        forbidden = (('g0', 'a'), ('g1', 'a'))
        for scenario in result['scenarios']:
            choices = set(scenario['choices'] if isinstance(scenario['choices'], list)
                          else scenario['choices'].items())
            self.assertFalse(forbidden[0] in choices and forbidden[1] in choices)
        self.assertTrue(result['checks']['amount_conservation']['ok'])

    def test_fixed_seed_reshuffle_invariant(self):
        rows = sampled_rows()
        spec = sampled_spec()
        base = analyze(rows, spec, sample_limit=10, seed=2024)
        repeat = analyze(rows, spec, sample_limit=10, seed=2024)
        self.assertEqual(base, repeat)
        shuffled_rows = copy.deepcopy(rows)
        random.Random(5).shuffle(shuffled_rows)
        shuffled_spec = copy.deepcopy(spec)
        random.Random(6).shuffle(shuffled_spec['groups'])
        for group in shuffled_spec['groups']:
            random.Random(8).shuffle(group['options'])
        with tempfile.TemporaryDirectory() as directory:
            path = write_json(directory, linkage_payload(shuffled_spec))
            loaded = load_linkage(path)
        reshuffled = analyze(shuffled_rows, loaded, sample_limit=10, seed=2024)
        self.assertEqual(base, reshuffled)


class LinkageValidationTest(unittest.TestCase):
    def load(self, spec):
        with tempfile.TemporaryDirectory() as directory:
            return load_linkage(write_json(directory, linkage_payload(spec)))

    def test_negative_weight_rejected(self):
        spec = hand_spec()
        spec['groups'][0]['options'][0]['weight'] = -1.0
        with self.assertRaisesRegex(ValueError, '负权重'):
            self.load(spec)

    def test_all_zero_weights_rejected(self):
        spec = hand_spec()
        for option in spec['groups'][0]['options']:
            option['weight'] = 0.0
        with self.assertRaisesRegex(ValueError, '权重全为零'):
            self.load(spec)

    def test_duplicate_attribution_across_groups_rejected(self):
        spec = hand_spec()
        spec['groups'][1]['options'][0]['assignments'] = {'P1': 'Y'}
        spec['groups'][1]['options'][1]['assignments'] = {'P1': 'Z'}
        with self.assertRaisesRegex(ValueError, '重复归属'):
            self.load(spec)

    def test_duplicate_attribution_with_fixed_rejected(self):
        spec = hand_spec()
        spec['groups'][1]['options'][0]['assignments'] = {'F1': 'Y'}
        spec['groups'][1]['options'][1]['assignments'] = {'F1': 'Z'}
        with self.assertRaisesRegex(ValueError, '重复归属'):
            self.load(spec)

    def test_inconsistent_option_coverage_rejected(self):
        spec = hand_spec()
        spec['groups'][0]['options'][1]['assignments'] = {'P1': 'X'}
        with self.assertRaisesRegex(ValueError, '方案覆盖不一致'):
            self.load(spec)

    def test_duplicate_json_key_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'linkage.json'
            path.write_text('{"schema_version": 1, "fixed_assignments": {"A": "X", "A": "Y"},'
                            ' "groups": [], "incompatible_options": []}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '重复键'):
                load_linkage(path)

    def test_unknown_incompatible_option_rejected(self):
        spec = hand_spec()
        spec['incompatible'] = [(('g1', 'o9'), ('g2', 'p2'))]
        with self.assertRaisesRegex(ValueError, '不存在的方案'):
            self.load(spec)

    def test_same_group_incompatibility_rejected(self):
        spec = hand_spec()
        spec['incompatible'] = [(('g1', 'o1'), ('g1', 'o2'))]
        with self.assertRaisesRegex(ValueError, '同组'):
            self.load(spec)

    def test_coverage_gap_against_observations(self):
        rows = hand_rows() + [make_row('obs-extra', 'EXTRA', 5)]
        with self.assertRaisesRegex(ValueError, '方案覆盖不足'):
            analyze(rows, hand_spec())

    def test_unknown_record_reference(self):
        spec = hand_spec()
        spec['fixed']['GHOST'] = 'X'
        with self.assertRaisesRegex(ValueError, '观测中不存在'):
            analyze(hand_rows(), spec)


class RealDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = analyze(load_records('data/observations.csv'),
                             load_linkage('data/linkage_options.json'))

    def test_feasible_space(self):
        space = self.result['scenario_space']
        self.assertEqual(space['mode'], 'exact')
        self.assertEqual(space['product_space'], 4)
        self.assertEqual(space['excluded_by_incompatibility'], 1)
        self.assertEqual(space['feasible'], 3)

    def test_conservation_per_year(self):
        conservation = self.result['checks']['amount_conservation']
        self.assertTrue(conservation['ok'])
        self.assertEqual(conservation['year_totals'], {'2024': 5112.0, '2025': 5976.0})

    def test_hhi_values(self):
        expected = {'S1': 0.04800359276157729, 'S2': 0.04800359276157729,
                    'S3': 0.047985530991548314}
        for scenario in self.result['scenarios']:
            self.assertAlmostEqual(scenario['years']['2024']['hhi'],
                                   expected[scenario['id']], places=15)
            self.assertAlmostEqual(scenario['years']['2025']['hhi'],
                                   0.04630368865018306, places=15)
        top = self.result['scenarios'][0]['years']['2024']['top3'][0]
        self.assertEqual(top['institution'], 'institution-23')
        self.assertAlmostEqual(top['share'], 351.0 / 5112.0, places=15)

    def test_normalized_weights(self):
        weights = {scenario['id']: scenario['normalized_weight']
                   for scenario in self.result['scenarios']}
        self.assertAlmostEqual(weights['S1'], 3 / 11, places=15)
        self.assertAlmostEqual(weights['S2'], 6 / 11, places=15)
        self.assertAlmostEqual(weights['S3'], 2 / 11, places=15)

    def test_most_influential_group(self):
        ranking = self.result['group_influence']['2024']
        self.assertEqual(ranking[0]['group'], 'group-b')
        self.assertGreater(ranking[0]['hhi_spread'], ranking[1]['hhi_spread'])

    def test_fix_shared_leaves_single_scenario(self):
        fixed = analyze(load_records('data/observations.csv'),
                        load_linkage('data/linkage_options.json'),
                        fixes=(('group-b', 'shared'),))
        self.assertEqual(len(fixed['scenarios']), 1)
        self.assertEqual(fixed['scenarios'][0]['choices'],
                         {'group-a': 'separate', 'group-b': 'shared'})


class CliTest(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run([sys.executable, '-m', 'analysis_app', 'concentration', *arguments],
                              text=True, capture_output=True)

    def test_cli_writes_json_and_explanation(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'result.json'
            explain = Path(directory) / 'explain.md'
            run = self.run_cli('--output', str(output), '--explain', str(explain))
            self.assertEqual(run.returncode, 0, run.stderr)
            payload = json.loads(run.stdout)
            self.assertEqual(json.loads(output.read_text(encoding='utf-8')), payload)
            text = explain.read_text(encoding='utf-8')
            self.assertIn('经费集中度不确定性说明', text)
            self.assertIn('group-b', text)

    def test_cli_failure_keeps_output_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            bad = Path(directory) / 'bad.json'
            bad.write_text(json.dumps({'schema_version': 1, 'fixed_assignments': {},
                                       'groups': [{'id': 'g', 'options': [
                                           {'id': 'o', 'weight': -1,
                                            'assignments': {'P': 'X'}}]}],
                                       'incompatible_options': []}), encoding='utf-8')
            output = Path(directory) / 'result.json'
            run = self.run_cli('--linkage', str(bad), '--output', str(output))
            self.assertEqual(run.returncode, 2)
            self.assertIn('负权重', run.stderr)
            self.assertFalse(output.exists())

    def test_cli_fix_and_bootstrap(self):
        run = self.run_cli('--fix', 'group-b=shared', '--bootstrap', '20', '--bootstrap-seed', '3')
        self.assertEqual(run.returncode, 0, run.stderr)
        payload = json.loads(run.stdout)
        self.assertEqual(len(payload['scenarios']), 1)
        self.assertEqual(payload['bootstrap']['replicates'], 20)


if __name__ == '__main__':
    unittest.main()
