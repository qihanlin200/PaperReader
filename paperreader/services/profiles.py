"""Versioned multi-model configuration; secrets remain in the system keyring."""
import uuid


def normalize_profiles(config):
    if config.get('profiles'):
        result = {'profiles': [dict(p) for p in config['profiles']], 'active_id': config.get('active_id')}
    else:
        result = {'profiles': [{'id': 'legacy', 'name': '默认模型',
                  'endpoint': config.get('endpoint', 'https://api.openai.com/v1'),
                  'model': config.get('model', ''), 'key_account': 'api'}], 'active_id': 'legacy'}
    for profile in result['profiles']:
        profile.setdefault('max_input_chars', 50000)
    if result['active_id'] not in [p['id'] for p in result['profiles']]:
        result['active_id'] = result['profiles'][0]['id']
    return result


def new_profile():
    identifier = uuid.uuid4().hex
    return dict(id=identifier, name='新模型', endpoint='https://api.openai.com/v1', model='', key_account='model:'+identifier, max_input_chars=50000)


def active_profile(config):
    return next(p for p in config['profiles'] if p['id'] == config['active_id'])
