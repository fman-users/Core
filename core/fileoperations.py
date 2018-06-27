from core.util import is_parent
from fman import YES, NO, YES_TO_ALL, NO_TO_ALL, ABORT, OK
from fman.url import basename, join, dirname, splitscheme, relpath, \
	as_human_readable
from os.path import pardir

import fman.fs

class FileTreeOperation:
	def __init__(
		self, descr_verb, ui, files, dest_dir, src_dir=None, dest_name=None,
		fs=fman.fs
	):
		if dest_name and len(files) > 1:
			raise ValueError(
				'Destination name can only be given when there is one file.'
			)
		self._ui = ui
		self._files = files
		self._dest_dir = dest_dir
		self._descr_verb = descr_verb
		self._src_dir = src_dir
		self._dest_name = dest_name
		self._fs = fs
		self._cannot_move_to_self_shown = False
		self._override_all = None
	def _perform_on_dir_dest_doesnt_exist(self, src, dest):
		raise NotImplementedError()
	def _perform_on_file(self, src, dest):
		raise NotImplementedError()
	def _perform_on_samefile(self, src, dest):
		raise NotImplementedError()
	def __call__(self):
		for i, src in enumerate(self._files):
			is_last = i == len(self._files) - 1
			if not self._call_on_file(src, is_last):
				break
		self._ui.clear_status_message()
	def _call_on_file(self, src, is_last):
		self._report_processing_of_file(src)
		dest = self._get_dest_url(src)
		if is_parent(src, dest, self._fs):
			if src != dest:
				try:
					is_samefile = self._fs.samefile(src, dest)
				except OSError:
					is_samefile = False
				if is_samefile and self._perform_on_samefile(src, dest):
					return True
			self._show_self_warning()
			return True
		try:
			if self._fs.is_dir(src):
				if self._fs.exists(dest):
					for top_dir, _, files in self._walk_bottom_up(src):
						for file_url in files:
							dst = self._get_dest_url(file_url)
							try:
								if not self.perform_on_file(file_url, dst):
									return False
							except (OSError, IOError) as e:
								return self._handle_exception(
									file_url, is_last, e
								)
						self.postprocess_directory(top_dir)
				else:
					self._perform_on_dir_dest_doesnt_exist(src, dest)
			else:
				if not self.perform_on_file(src, dest):
					return False
		except (OSError, IOError) as e:
			return self._handle_exception(src, is_last, e)
		return True
	def _walk_bottom_up(self, url):
		dirs = []
		nondirs = []
		for file_name in self._fs.iterdir(url):
			file_url = join(url, file_name)
			try:
				is_dir = self._fs.is_dir(file_url)
			except OSError:
				is_dir = False
			if is_dir:
				dirs.append(file_url)
				yield from self._walk_bottom_up(file_url)
			else:
				nondirs.append(file_url)
		yield url, dirs, nondirs
	def _handle_exception(self, file_url, is_last, exc):
		if exc.strerror:
			cause = exc.strerror[0].lower() + exc.strerror[1:]
		else:
			cause = exc.__class__.__name__
		message = 'Could not %s %s (%s).' % \
				  (self._descr_verb, as_human_readable(file_url), cause)
		if is_last:
			buttons = OK
			default_button = OK
		else:
			buttons = YES | YES_TO_ALL | ABORT
			default_button = YES
			message += ' Do you want to continue?'
		choice = self._ui.show_alert(message, buttons, default_button)
		if is_last:
			return choice & OK
		else:
			return choice & YES or choice & YES_TO_ALL
	def _report_processing_of_file(self, file_):
		verb = self._descr_verb.capitalize()
		verbing = (verb[:-1] if verb.endswith('e') else verb) + 'ing'
		self._ui.show_status_message('%s %s...' % (verbing, basename(file_)))
	def perform_on_file(self, src, dest):
		self._report_processing_of_file(src)
		if self._fs.exists(dest):
			if self._fs.samefile(src, dest):
				self._show_self_warning()
				return True
			if self._override_all is None:
				choice = self._ui.show_alert(
					"%s exists. Do you want to overwrite it?" % basename(src),
					YES | NO | YES_TO_ALL | NO_TO_ALL | ABORT, YES
				)
				if choice & NO:
					return True
				elif choice & NO_TO_ALL:
					self._override_all = False
				elif choice & YES_TO_ALL:
					self._override_all = True
				elif choice & ABORT:
					return False
			if self._override_all is False:
				return True
		self._fs.makedirs(dirname(dest), exist_ok=True)
		self._perform_on_file(src, dest)
		return True
	def _show_self_warning(self):
		if not self._cannot_move_to_self_shown:
			self._ui.show_alert(
				"You cannot %s a file to itself." % self._descr_verb
			)
			self._cannot_move_to_self_shown = True
	def postprocess_directory(self, src_dir_path):
		pass
	def _get_dest_url(self, src_file):
		dest_name = self._dest_name or basename(src_file)
		if self._src_dir:
			try:
				rel_path = \
					relpath(join(dirname(src_file), dest_name), self._src_dir)
			except ValueError as e:
				raise ValueError(
					'Could not construct path. '
					'src_file: %r, dest_name: %r, src_dir: %r' %
					(src_file, dest_name, self._src_dir)
				) from e
			is_in_src_dir = not rel_path.startswith(pardir)
			if is_in_src_dir:
				try:
					splitscheme(self._dest_dir)
				except ValueError as no_scheme:
					return join(self._src_dir, self._dest_dir, rel_path)
				else:
					return join(self._dest_dir, rel_path)
		return join(self._dest_dir, dest_name)

class CopyFiles(FileTreeOperation):
	def __init__(self, *super_args, **super_kwargs):
		super().__init__('copy', *super_args, **super_kwargs)
	def _perform_on_dir_dest_doesnt_exist(self, src, dest):
		self._fs.copy(src, dest)
	def _perform_on_file(self, src, dest):
		self._fs.copy(src, dest)
	def _perform_on_samefile(self, src, dest):
		# Can never copy to the same file.
		return False

class MoveFiles(FileTreeOperation):
	def __init__(self, *super_args, **super_kwargs):
		super().__init__('move', *super_args, **super_kwargs)
	def postprocess_directory(self, src_dir_path):
		if self._is_empty(src_dir_path):
			try:
				self._fs.delete(src_dir_path)
			except OSError:
				pass
	def _is_empty(self, dir_url):
		try:
			next(iter(self._fs.iterdir(dir_url)))
		except StopIteration:
			return True
		return False
	def _perform_on_dir_dest_doesnt_exist(self, src, dest):
		self._fs.move(src, dest)
	def _perform_on_file(self, src, dest):
		self._fs.move(src, dest)
	def _perform_on_samefile(self, src, dest):
		# May be able to move to the same file on case insensitive file systems.
		# Consider a/ and A/: They are the "same" file yet it does make sense to
		# rename one to the other.
		self._fs.move(src, dest)
		return True