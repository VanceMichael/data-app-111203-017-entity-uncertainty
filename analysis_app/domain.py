import math
import statistics
from collections import Counter


def describe(records):
    return {'amount_total': math.fsum(row['amount'] for row in records), 'registry_available': sum(bool(row['registry']) for row in records), 'names': len({row['name'] for row in records})}
