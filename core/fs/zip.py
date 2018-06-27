from collections import namedtuple
from core.os_ import is_arch
from core.util import filenotfounderror
from datetime import datetime
from fman import PLATFORM, load_json
from fman.fs import FileSystem
from fman.url import as_url, splitscheme
from io import UnsupportedOperation, TextIOWrapper
from os.path import join, dirname
from pathlib import PurePosixPath, Path
from subprocess import Popen, PIPE, DEVNULL, CalledProcessError
from tempfile import TemporaryDirectory

import fman.fs
import os
import os.path

class _7ZipFileSystem(FileSystem):
	def __init__(self, fs=fman.fs, suffixes=None):
		if suffixes is None:
			suffixes = self._load_suffixes_from_json()
		super().__init__()
		self._fs = fs
		self._suffixes = suffixes
	def _load_suffixes_from_json(self):
		settings = load_json('Core Settings.json', default={})
		archive_handlers = settings.get('archive_handlers', {})
		return set(
			suffix for suffix, scheme in archive_handlers.items()
			if scheme == self.scheme
		)

	def get_default_columns(self, path):
		return 'core.Name', 'core.Size', 'core.Modified'
	def resolve(self, path):
		for suffix in self._suffixes:
			if suffix in path.lower():
				# Return zip:// + path:
				return super().resolve(path)
		return as_url(path)
	def iterdir(self, path):
		path_in_zip = self._split(path)[1]
		already_yielded = set()
		for file_info in self._iter_infos(path):
			candidate = file_info.path
			while candidate:
				candidate_path = PurePosixPath(candidate)
				parent = str(candidate_path.parent)
				if parent == '.':
					parent = ''
				if parent == path_in_zip:
					name = candidate_path.name
					if name not in already_yielded:
						yield name
						already_yielded.add(name)
				candidate = parent
	def is_dir(self, existing_path):
		zip_path, path_in_zip = self._split(existing_path)
		if not path_in_zip:
			if Path(zip_path).exists():
				return True
			raise filenotfounderror(existing_path)
		result = self._query_info_attr(existing_path, 'is_dir', True)
		if result is not None:
			return result
		raise filenotfounderror(existing_path)
	def exists(self, path):
		try:
			zip_path, path_in_zip = self._split(path)
		except FileNotFoundError:
			return False
		if not path_in_zip:
			return Path(zip_path).exists()
		try:
			next(iter(self._iter_infos(path)))
		except (StopIteration, FileNotFoundError):
			return False
		return True
	def copy(self, src_url, dst_url):
		src_scheme, src_path = splitscheme(src_url)
		dst_scheme, dst_path = splitscheme(dst_url)
		if src_scheme == self.scheme and dst_scheme == 'file://':
			zip_path, path_in_zip = self._split(src_path)
			self._extract(zip_path, path_in_zip, dst_path)
		elif src_scheme == 'file://' and dst_scheme == self.scheme:
			zip_path, path_in_zip = self._split(dst_path)
			self._add_to_zip(src_path, zip_path, path_in_zip)
		elif src_scheme == dst_scheme:
			# Guaranteed by fman's file system implementation:
			assert src_scheme == self.scheme
			with TemporaryDirectory() as tmp_dir:
				tmp_dst = join(as_url(tmp_dir), 'tmp')
				self.copy(src_url, tmp_dst)
				self.copy(tmp_dst, dst_url)
		else:
			raise UnsupportedOperation()
	def move(self, src_url, dst_url):
		src_scheme, src_path = splitscheme(src_url)
		dst_scheme, dst_path = splitscheme(dst_url)
		if src_scheme == dst_scheme:
			# Guaranteed by fman's file system implementation:
			assert src_scheme == self.scheme
			src_zip, src_pth_in_zip = self._split(src_path)
			dst_zip, dst_pth_in_zip = self._split(dst_path)
			if src_zip == dst_zip:
				with self._preserve_empty_parent(src_zip, src_pth_in_zip):
					self._run_7zip(
						['rn', src_zip, src_pth_in_zip, dst_pth_in_zip]
					)
			else:
				with TemporaryDirectory() as tmp_dir:
					tmp_dst = join(as_url(tmp_dir), 'tmp')
					self.copy(src_url, tmp_dst)
					self.move(tmp_dst, dst_url)
					self.delete(src_path)
		else:
			self.copy(src_url, dst_url)
			src_scheme, src_path = splitscheme(src_url)
			if src_scheme == 'zip://':
				self.delete(src_path)
			else:
				self._fs.delete(src_url)
	def mkdir(self, path):
		if self.exists(path):
			raise FileExistsError(path)
		zip_path, path_in_zip = self._split(path)
		if not path_in_zip:
			self._create_empty_archive(zip_path)
		elif not self.exists(str(PurePosixPath(path).parent)):
			raise filenotfounderror(path)
		else:
			with TemporaryDirectory() as tmp_dir:
				self._add_to_zip(tmp_dir, zip_path, path_in_zip)
	def _create_empty_archive(self, zip_path):
		# Run 7-Zip in an empty temporary directory. Create this directory next
		# to the Zip file to ensure Path.rename(...) works because it's on the
		# same file system.
		with self._create_temp_dir_next_to(zip_path) as tmp_dir:
			name = PurePosixPath(zip_path).name
			self._run_7zip(['a', name], cwd=tmp_dir)
			Path(tmp_dir, name).rename(zip_path)
	def _create_temp_dir_next_to(self, path):
		return TemporaryDirectory(
			dir=str(PurePosixPath(path).parent), prefix='', suffix='.tmp'
		)
	def delete(self, path):
		if not self.exists(path):
			raise filenotfounderror(path)
		zip_path, path_in_zip = self._split(path)
		with self._preserve_empty_parent(zip_path, path_in_zip):
			self._run_7zip(['d', zip_path, path_in_zip])
	def size_bytes(self, path):
		return self._query_info_attr(path, 'size_bytes', None)
	def modified_datetime(self, path):
		return self._query_info_attr(path, 'mtime', None)
	def _query_info_attr(self, path, attr, folder_default):
		def compute_value():
			path_in_zip = self._split(path)[1]
			if not path_in_zip:
				return folder_default
			for info in self._iter_infos(path):
				if info.path == path_in_zip:
					return getattr(info, attr)
				return folder_default
		return self.cache.query(path, attr, compute_value)
	def _preserve_empty_parent(self, zip_path, path_in_zip):
		# 7-Zip deletes empty directories that remain after an operation. For
		# instance, when deleting the last file from a directory, or when moving
		# it out of the directory. We don't want this to happen. The present
		# method allows us to preserve the parent directory, even if empty:
		parent = str(PurePosixPath(path_in_zip).parent)
		parent_fullpath = zip_path + '/' + parent
		class CM:
			def __enter__(cm):
				if parent != '.':
					cm._parent_wasdir_before = self.is_dir(parent_fullpath)
				else:
					cm._parent_wasdir_before = False
			def __exit__(cm, exc_type, exc_val, exc_tb):
				if not exc_val:
					if cm._parent_wasdir_before:
						if not self.exists(parent_fullpath):
							self.makedirs(parent_fullpath)
		return CM()
	def _extract(self, zip_path, path_in_zip, dst_path):
		# Create temp dir next to dst_path to ensure Path.replace(...) works
		# because it's on the same file system.
		tmp_dir = self._create_temp_dir_next_to(dst_path)
		try:
			args = ['x', zip_path, '-o' + tmp_dir.name]
			if path_in_zip:
				args.insert(2, path_in_zip)
			self._run_7zip(args)
			root = Path(tmp_dir.name, *path_in_zip.split('/'))
			root.replace(dst_path)
		finally:
			try:
				tmp_dir.cleanup()
			except FileNotFoundError:
				# This happens when path_in_zip = ''
				pass
	def _add_to_zip(self, src_path, zip_path, path_in_zip):
		if not path_in_zip:
			raise ValueError(
				'Must specify the destination path inside the archive'
			)
		with TemporaryDirectory() as tmp_dir:
			dest = Path(tmp_dir, *path_in_zip.split('/'))
			dest.parent.mkdir(parents=True, exist_ok=True)
			src = Path(src_path)
			try:
				dest.symlink_to(src, src.is_dir())
			except OSError:
				# This for instance happens on non-NTFS drives on Windows.
				# We need to incur the cost of physically copying the file:
				self._fs.copy(as_url(src), as_url(dest))
			args = ['a', zip_path, path_in_zip]
			if PLATFORM != 'Windows':
				args.insert(1, '-l')
			self._run_7zip(args, cwd=tmp_dir)
	def _split(self, path):
		for suffix in self._suffixes:
			try:
				split_point = path.lower().index(suffix) + len(suffix)
			except ValueError as suffix_not_found:
				continue
			else:
				return path[:split_point], path[split_point:].lstrip('/')
		raise filenotfounderror(self.scheme + path) from None
	def _iter_infos(self, path):
		zip_path, path_in_zip = self._split(path)
		self._raise_filenotfounderror_if_not_exists(zip_path)
		args = ['l', '-ba', '-slt', zip_path]
		if path_in_zip:
			args.append(path_in_zip)
		# We can hugely improve performance by making 7-Zip exclude children of
		# the given directory. Unfortunately, this has a drawback: If you have
		# a/b.txt in an archive but no separate entry for a/, then excluding */*
		# filters out a/. We thus exclude */*/*/*. This works for all folders
		# that contain at least one subdirectory with a file.
		exclude = (path_in_zip + '/' if path_in_zip else '') + '*/*/*/*'
		args.append('-x!' + exclude)
		with _7zip(args, kill=True) as stdout:
			file_info = self._read_file_info(stdout)
			if path_in_zip and not file_info:
				raise filenotfounderror(self.scheme + path)
			while file_info:
				self._put_in_cache(zip_path, file_info)
				yield file_info
				file_info = self._read_file_info(stdout)
	def _raise_filenotfounderror_if_not_exists(self, zip_path):
		os.stat(zip_path)
	def _run_7zip(self, args, cwd=None):
		with _7zip(args, cwd=cwd):
			pass
	def _read_file_info(self, stdout):
		path = size = mtime = None
		is_dir = False
		for line in stdout:
			line = line.rstrip('\n')
			if not line:
				break
			if line.startswith('Path = '):
				path = line[len('Path = '):].replace(os.sep, '/')
			elif line.startswith('Folder = '):
				folder = line[len('Folder = '):]
				is_dir = is_dir or folder == '+'
			elif line.startswith('Size = '):
				size_str = line[len('Size = '):]
				if size_str:
					size = int(size_str)
			elif line.startswith('Modified = '):
				mtime_str = line[len('Modified = '):]
				if mtime_str:
					mtime = datetime.strptime(mtime_str, '%Y-%m-%d %H:%M:%S')
			elif line.startswith('Attributes = '):
				attributes = line[len('Attributes = '):]
				is_dir = is_dir or attributes.startswith('D')
		if path:
			return _FileInfo(path, is_dir, size, mtime)
	def _put_in_cache(self, zip_path, file_info):
		for field in file_info._fields:
			if field != 'path':
				self.cache.put(
					zip_path + '/' + file_info.path, field,
					getattr(file_info, field)
				)

class _7zip:

	_7ZIP_WARNING = 1

	def __init__(self, args, cwd=None, kill=False):
		self._args = args
		self._cwd = cwd
		self._kill = kill
		self._process = self._stdout = None
	def __enter__(self):
		extra_kwargs = {}
		if PLATFORM == 'Windows':
			from subprocess import STARTF_USESHOWWINDOW, SW_HIDE, STARTUPINFO
			si = STARTUPINFO()
			si.dwFlags = STARTF_USESHOWWINDOW
			si.wShowWindow = SW_HIDE
			extra_kwargs['startupinfo'] = si
			env = {}
			# Force an output encoding that works with universal_newlines:
			args = ['-sccWIN'] + self._args
			encoding = None
		else:
			# According to the README in its source code distribution, p7zip can
			# only handle unicode file names properly if the environment is
			# UTF-8:
			env = {
				'LANG': 'en_US.UTF-8'
			}
			args = self._args
			# Set the encoding ourselves because Popen(...)'s universal_newlines
			# uses ASCII if locale.getpreferredencoding(False) happens to be
			# None.
			encoding = 'utf-8'
		self._process = Popen(
			[self._get_7zip_binary()] + args, stdout=PIPE, stderr=DEVNULL,
			cwd=self._cwd,
			# We use our own env to prevent potential interferences with the
			# user's environment variables:
			env=env,
			**extra_kwargs
		)
		self._stdout = TextIOWrapper(self._process.stdout, encoding=encoding)
		return self._stdout
	def __exit__(self, exc_type, exc_val, exc_tb):
		try:
			if self._kill:
				self._process.kill()
				self._process.wait()
			else:
				exit_code = self._process.wait()
				if exit_code and exit_code != self._7ZIP_WARNING:
					raise CalledProcessError(exit_code, self._process.args)
		finally:
			self._stdout.close()
			self._process.stdout.close()
	def _get_7zip_binary(self):
		if is_arch():
			bin_dir = '/usr/bin'
		else:
			bin_dir = join(
				dirname(dirname(dirname(__file__))), 'bin', PLATFORM.lower()
			)
		return join(bin_dir, '7za' + ('.exe' if PLATFORM == 'Windows' else ''))

class ZipFileSystem(_7ZipFileSystem):
	scheme = 'zip://'

class SevenZipFileSystem(_7ZipFileSystem):
	scheme = '7z://'

class TarFileSystem(_7ZipFileSystem):
	scheme = 'tar://'

_FileInfo = namedtuple('_FileInfo', ('path', 'is_dir', 'size_bytes', 'mtime'))