FIELDS = {'observation_id': 'str', 'record': 'str', 'source': 'str', 'name': 'str', 'city': 'str', 'amount': 'float', 'year': 'int', 'registry': 'str', 'parent_hint': 'str'}
REQUIRED = ['observation_id', 'record', 'source', 'name', 'city', 'amount', 'year']
ENTITY = 'record'
GROUP = 'source'
MEASURE = 'amount'
PRODUCT = 'entity-uncertainty'
UNIT = '万元'
