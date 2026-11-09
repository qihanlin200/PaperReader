import unittest
from paperreader.services.profiles import normalize_profiles, new_profile, active_profile, export_profiles, import_profiles


class ProfileTests(unittest.TestCase):
    def test_legacy_keeps_key_account(self):
        config = normalize_profiles({'endpoint': 'https://example.org/v1', 'model': 'legacy-model'})
        self.assertEqual(active_profile(config)['key_account'], 'api')
        self.assertEqual(active_profile(config)['model'], 'legacy-model')

    def test_unique_keys_and_active_fallback(self):
        first, second = new_profile(), new_profile()
        self.assertNotEqual(first['key_account'], second['key_account'])
        config = normalize_profiles({'profiles': [first, second], 'active_id': 'missing'})
        self.assertEqual(active_profile(config)['id'], first['id'])

    def test_portable_export_import_omits_keys_by_default(self):
        first, second = new_profile(), new_profile()
        first.update(name='主要', endpoint='http://localhost:8000/v1', model='local', max_input_chars=64000)
        second.update(name='备用', endpoint='https://example.org/v1', model='remote')
        document = export_profiles({'profiles': [first, second], 'active_id': second['id']})
        self.assertNotIn('api_key', str(document))
        self.assertNotIn(first['id'], str(document))
        self.assertNotIn('key_account', str(document))
        profiles, active_id, secrets = import_profiles(document)
        self.assertEqual(profiles[0]['max_input_chars'], 64000)
        self.assertEqual(active_id, profiles[1]['id'])
        self.assertNotEqual(profiles[0]['id'], first['id'])
        self.assertEqual(secrets, {})

    def test_portable_export_can_include_explicit_keys(self):
        profile = new_profile()
        document = export_profiles({'profiles': [profile], 'active_id': profile['id']}, {profile['id']: 'example-secret'})
        profiles, active_id, secrets = import_profiles(document)
        self.assertEqual(secrets[active_id], 'example-secret')
        self.assertNotEqual(profiles[0]['key_account'], profile['key_account'])

    def test_import_rejects_invalid_file(self):
        profile = new_profile()
        document = export_profiles({'profiles': [profile], 'active_id': profile['id']})
        for change in ({'format': 'other'}, {'active': 3}, {'profiles': []}):
            bad = dict(document, **change)
            with self.assertRaises(ValueError): import_profiles(bad)
