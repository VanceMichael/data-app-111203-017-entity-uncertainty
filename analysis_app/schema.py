FIELDS = {'observation_id': 'str', 'record': 'str', 'source': 'str', 'name': 'str', 'city': 'str', 'amount': 'float', 'year': 'int', 'registry': 'str', 'parent_hint': 'str'}
REQUIRED = ['observation_id', 'record', 'source', 'amount']
ENTITY = 'record'
GROUP = 'source'
MEASURE = 'amount'
PRODUCT = 'entity-uncertainty'
UNIT = '万元'
