from fman import PLATFORM
from fman.url import join, as_url
from core import LocalFileSystem
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipIf

import os

class LocalFileSystemTest(TestCase):
	def test_mkdir_root(self):
		with self.assertRaises(FileExistsError):
			self._fs.mkdir('C:' if PLATFORM == 'Windows' else '/')
	def test_iterdir_nonexistent(self):
		root = 'C:/' if PLATFORM == 'Windows' else '/'
		path = root + 'nonexistent'
		with self.assertRaises(FileNotFoundError):
			next(iter(self._fs.iterdir(path)))
	def test_empty_path_does_not_exist(self):
		self.assertFalse(self._fs.exists(''))
	def test_relative_paths(self):
		subdir_name = 'subdir'
		with TemporaryCwd() as tmp_dir:
			Path(tmp_dir, subdir_name).mkdir()
			self.assertFalse(self._fs.exists(subdir_name))
			with self.assertRaises(FileNotFoundError):
				list(self._fs.iterdir(subdir_name))
			with self.assertRaises(FileNotFoundError):
				self._fs.is_dir(subdir_name)
			with self.assertRaises(FileNotFoundError):
				self._fs.stat(subdir_name)
			with self.assertRaises(FileNotFoundError):
				self._fs.size_bytes(subdir_name)
			with self.assertRaises(FileNotFoundError):
				self._fs.modified_datetime(subdir_name)
			with self.assertRaises(ValueError):
				self._fs.touch('test.txt')
			with self.assertRaises(ValueError):
				self._fs.mkdir('other_dir')
			src_url = join(as_url(tmp_dir), subdir_name)
			dst_url = as_url('dir2')
			with self.assertRaises(ValueError):
				self._fs.move(src_url, dst_url)
			with self.assertRaises(ValueError):
				self._fs.prepare_move(src_url, dst_url)
			with self.assertRaises(ValueError):
				self._fs.copy(src_url, dst_url)
			with self.assertRaises(ValueError):
				self._fs.prepare_copy(src_url, dst_url)
			with self.assertRaises(FileNotFoundError):
				self._fs.move_to_trash(subdir_name)
			with self.assertRaises(FileNotFoundError):
				list(self._fs.prepare_trash(subdir_name))
			with self.assertRaises(FileNotFoundError):
				self._fs.delete(subdir_name)
			file_name = 'test.txt'
			Path(tmp_dir, file_name).touch()
			with self.assertRaises(FileNotFoundError):
				self._fs.delete(file_name)
			with self.assertRaises(FileNotFoundError):
				self._fs.resolve(subdir_name)
	@skipIf(PLATFORM != 'Windows', 'Skip Windows-only test')
	def test_isabs_windows(self):
		self.assertTrue(self._fs._isabs(r'\\host'))
		self.assertTrue(self._fs._isabs(r'\\host\share'))
		self.assertTrue(self._fs._isabs(r'\\host\share\subfolder'))
		self.assertFalse(self._fs._isabs('dir'))
		self.assertFalse(self._fs._isabs(r'dir\subdir'))
	def setUp(self):
		super().setUp()
		self._fs = LocalFileSystem()

class TemporaryCwd:
	def __init__(self):
		self._cwd_before = None
		self._tmp_dir = None
	def __enter__(self):
		self._cwd_before = os.getcwd()
		self._tmp_dir = TemporaryDirectory()
		tmp_dir_path = self._tmp_dir.name
		os.chdir(tmp_dir_path)
		return tmp_dir_path
	def __exit__(self, *_):
		os.chdir(self._cwd_before)
		self._tmp_dir.cleanup()