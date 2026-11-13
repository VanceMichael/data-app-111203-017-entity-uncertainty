import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from .concentration import (DEFAULT_BOOTSTRAP_SEED, DEFAULT_SAMPLE_LIMIT, DEFAULT_SEED,
                            analyze)
from .explain import render_explanation
from .io import load_records
from .linkage import load_linkage
from .summary import summarize


def _atomic_write(destination, write):
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.analysis-', dir=destination.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            write(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_json(path, result):
    destination = Path(path)

    def write(handle):
        json.dump(result, handle, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2)
        handle.write('\n')

    _atomic_write(destination, write)


def save_text(path, text):
    destination = Path(path)

    def write(handle):
        handle.write(text)

    _atomic_write(destination, write)


def _parse_fix(value):
    if '=' not in value:
        raise argparse.ArgumentTypeError('--fix 需要 组=方案 形式：' + value)
    group, option = value.split('=', 1)
    if not group or not option:
        raise argparse.ArgumentTypeError('--fix 需要 组=方案 形式：' + value)
    return (group, option)


def main():
    parser = argparse.ArgumentParser(description='本地观测数据分析')
    commands = parser.add_subparsers(dest='command', required=True)

    summary = commands.add_parser('summary', help='按业务维度核对观测口径')
    summary.add_argument('--input', type=Path, default=Path('data/observations.csv'))
    summary.add_argument('--output', type=Path)

    concentration = commands.add_parser('concentration', help='候选归属情景下的集中度不确定性分析')
    concentration.add_argument('--input', type=Path, default=Path('data/observations.csv'))
    concentration.add_argument('--linkage', type=Path, default=Path('data/linkage_options.json'))
    concentration.add_argument('--output', type=Path)
    concentration.add_argument('--explain', type=Path, help='把供规划会阅读的中文说明写入该文件')
    concentration.add_argument('--fix', type=_parse_fix, action='append', default=[],
                               metavar='组=方案', help='固定某待审组的方案后重新计算，可重复')
    concentration.add_argument('--sample-limit', type=int, default=DEFAULT_SAMPLE_LIMIT,
                               help='可行情景枚举上限，超过则改为有种子抽样')
    concentration.add_argument('--seed', type=int, default=DEFAULT_SEED, help='抽样种子')
    concentration.add_argument('--bootstrap', type=int, default=0, metavar='N',
                               help='资助记录抽样误差复制次数（整记录重采样），默认关闭')
    concentration.add_argument('--bootstrap-seed', type=int, default=DEFAULT_BOOTSTRAP_SEED)

    args = parser.parse_args()
    try:
        if args.command == 'summary':
            result = summarize(load_records(args.input))
            explanation = None
        else:
            if args.sample_limit < 1:
                raise ValueError('--sample-limit 应为正整数')
            if args.bootstrap < 0:
                raise ValueError('--bootstrap 不能为负')
            result = analyze(load_records(args.input), load_linkage(args.linkage),
                             fixes=args.fix, sample_limit=args.sample_limit, seed=args.seed,
                             bootstrap_replicates=args.bootstrap, bootstrap_seed=args.bootstrap_seed)
            explanation = render_explanation(result)
        if args.output:
            save_json(args.output, result)
        if getattr(args, 'explain', None):
            save_text(args.explain, explanation)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
