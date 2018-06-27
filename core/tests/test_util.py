from core import strformat_dict_values
from unittest import TestCase

class TestStrformatDictValues(TestCase):
	def test_empty(self):
		self.assertEqual({}, strformat_dict_values({}, {'a': 'b'}))
	def test_simple_replacement(self):
		self.assertEqual(
			{'a': 'a was replaced', 'c': 'd'},
			strformat_dict_values(
				{'a': '{a}', 'c': 'd'},
				{'a': 'a was replaced'}
			)
		)
	def test_list(self):
		self.assertEqual(
			{'list': ['replaced']},
			strformat_dict_values(
				{'list': ['{replaceme}']},
				{'replaceme': 'replaced'}
			)
		)
	def test_list_ints(self):
		dict_ = {'list': [1]}
		self.assertEqual(dict_, strformat_dict_values(dict_, {'a': 'b'}))