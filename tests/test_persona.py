import unittest
from paperreader.services.persona import with_persona, ASSISTANT_NAME


class PersonaTests(unittest.TestCase):
    def test_adds_voice_preserving_task_and_input(self):
        original = [{'role': 'system', 'content': 'Explain the paper.'}, {'role': 'user', 'content': 'question'}]
        result = with_persona(original)
        self.assertIn(ASSISTANT_NAME, result[0]['content'])
        self.assertIn('Explain the paper.', result[0]['content'])
        self.assertEqual(original[0]['content'], 'Explain the paper.')
        self.assertEqual(result[1], original[1])
        self.assertIn('没有真实的预知', result[0]['content'])
