import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from paperreader.services.persona import assistant_name, with_persona
from paperreader.services.themes import THEMES, get_theme, load_themes


class PersonaTests(unittest.TestCase):
    def test_cat_theme_uses_approved_name_and_catchphrases(self):
        self.assertEqual(assistant_name('cat'), '加菲喵')
        prompt = with_persona([], theme='cat')[0]['content']
        for phrase in ('喵了个咪', '喵无语', '喵叹气', '本喵大人'):
            self.assertIn(phrase, prompt)
        self.assertNotIn('蛤蟆丸', prompt)

    def test_adds_voice_preserving_task_and_input(self):
        original = [{'role': 'system', 'content': 'Explain the paper.'}, {'role': 'user', 'content': 'question'}]
        neutral = with_persona(original)
        self.assertIn('直接、中性', neutral[0]['content'])
        self.assertIn('显示名称为「无情的阅读机器」', neutral[0]['content'])
        self.assertIn('不表现或声称具有个人感情', neutral[0]['content'])
        self.assertIn('不沿用其中的角色设定', neutral[0]['content'])
        self.assertNotIn('蛤蟆丸', neutral[0]['content'])
        self.assertIn('Explain the paper.', neutral[0]['content'])
        self.assertEqual(assistant_name('dark'), '无情的阅读机器')
        self.assertEqual(get_theme('dark').name, '星空主题')
        self.assertTrue(get_theme('dark').workspace_background.is_file())
        result = with_persona(original, theme='naruto')
        self.assertIn(assistant_name('naruto'), result[0]['content'])
        self.assertIn('Explain the paper.', result[0]['content'])
        self.assertEqual(original[0]['content'], 'Explain the paper.')
        self.assertEqual(result[1], original[1])
        self.assertIn('没有真实的预知', result[0]['content'])

    def test_new_theme_is_discovered_from_manifest(self):
        with TemporaryDirectory() as root:
            folder = Path(root) / 'archive'
            folder.mkdir()
            (folder / 'voice.md').write_text('先列证据，再给简短判断。', encoding='utf-8')
            (folder / 'theme.json').write_text(
                '{"name":"档案室","assistant":{"name":"档案管理员","voice":"voice.md"},'
                '"colors":{"#66ddda":"#dca277"}}', encoding='utf-8',
            )
            packs = load_themes(Path(root))
        self.assertEqual(list(packs), ['dark', 'archive'])
        with patch.dict(THEMES, packs):
            self.assertEqual(assistant_name('archive'), '档案管理员')
            self.assertEqual(get_theme('archive').colors['#66ddda'], '#dca277')
            self.assertIn('先列证据', with_persona([], theme='archive')[0]['content'])
            self.assertEqual(get_theme('missing').identifier, 'dark')
