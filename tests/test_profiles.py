import unittest
from paperreader.services.profiles import normalize_profiles, new_profile, active_profile


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
