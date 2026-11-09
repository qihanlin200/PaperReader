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


PROFILE_FILE_FORMAT = 'paperreader-model-profiles'


def export_profiles(config, secrets=None):
    """Create a portable model-settings document without local keyring identifiers."""
    secrets = secrets or {}
    profiles = []
    for profile in config['profiles']:
        item = {field: profile[field] for field in ('name', 'endpoint', 'model', 'max_input_chars')}
        if profile['id'] in secrets and secrets[profile['id']]:
            item['api_key'] = secrets[profile['id']]
        profiles.append(item)
    active = next((i for i, p in enumerate(config['profiles']) if p['id'] == config['active_id']), 0)
    return {'format': PROFILE_FILE_FORMAT, 'version': 1, 'active': active, 'profiles': profiles}


def import_profiles(document):
    """Validate a portable document and assign fresh local profile/keyring IDs."""
    if not isinstance(document, dict) or document.get('format') != PROFILE_FILE_FORMAT or document.get('version') != 1:
        raise ValueError('不是受支持的 PaperReader 模型配置文件。')
    rows = document.get('profiles')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise ValueError('配置文件须包含 1 至 100 个模型。')
    active = document.get('active')
    if type(active) is not int or not 0 <= active < len(rows):
        raise ValueError('配置文件的默认模型位置无效。')
    profiles, secrets = [], {}
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f'第 {index} 个模型配置格式错误。')
        for field in ('name', 'endpoint', 'model'):
            if not isinstance(row.get(field), str) or (field != 'model' and not row[field].strip()) or len(row[field]) > 2048:
                raise ValueError(f'第 {index} 个模型的 {field} 无效。')
        limit = row.get('max_input_chars')
        if type(limit) is not int or not 4096 <= limit <= 2000000:
            raise ValueError(f'第 {index} 个模型的最大输入长度无效。')
        secret = row.get('api_key')
        if secret is not None and (not isinstance(secret, str) or len(secret) > 16384):
            raise ValueError(f'第 {index} 个模型的 API Key 无效。')
        profile = new_profile()
        profile.update(name=row['name'].strip(), endpoint=row['endpoint'].strip(),
                       model=row['model'].strip(), max_input_chars=limit)
        profiles.append(profile)
        if secret:
            secrets[profile['id']] = secret
    return profiles, profiles[active]['id'], secrets
