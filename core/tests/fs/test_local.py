from fman import PLATFORM
from core import LocalFileSystem
from os.path import join
from unittest import TestCase

class LocalFileSystemTest(TestCase):
	def test_mkdir_root(self):
		with self.assertRaises(FileExistsError):
			self._fs.mkdir('C:' if PLATFORM == 'Windows' else '/')
	def test_iterdir_nonexistent(self):
		root = 'C:\\' if PLATFORM == 'Windows' else '/'
		with self.assertRaises(FileNotFoundError):
			next(iter(self._fs.iterdir(join(root, 'nonexistent'))))
	def setUp(self):
		super().setUp()
		self._fs = LocalFileSystem()