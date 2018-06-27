"""
shutil.rmtree fails on Windows when we have a QFileSystemWatcher watching a
subdirectory of the directory we are trying to delete:

	from os import mkdir
	mkdir('tmp')
	mkdir(r'tmp\sub')
	from PyQt5.QtCore import QFileSystemWatcher
	watcher = QFileSystemWatcher()
	assert watcher.addPath(r'tmp\sub')
	from shutil import rmtree
	# Fails with OSError "The directory is not empty: 'tmp'":
	rmtree('tmp')

The present module works around this problem. It is based on Python's
test.support.rmtree(...) and on shutil.rmtree(...).
"""

import os
import stat
import sys
import time

def rmtree(path, onerror=None):
	if onerror is None:
		def onerror(*args):
			raise
	def _rmtree_inner(path):
		names = []
		try:
			names = _force_run(path, os.listdir, path)
		except OSError:
			onerror(os.listdir, path, sys.exc_info())
		for name in names:
			fullname = os.path.join(path, name)
			try:
				mode = os.lstat(fullname).st_mode
			except OSError:
				mode = 0
			if stat.S_ISDIR(mode):
				_wait_until_deleted(_rmtree_inner, fullname, waitall=True)
			else:
				try:
					_force_run(fullname, os.unlink, fullname)
				except OSError:
					onerror(os.unlink, fullname, sys.exc_info())
		try:
			_wait_until_deleted(lambda p: _force_run(p, os.rmdir, p), path)
		except OSError:
			onerror(os.rmdir, path, sys.exc_info())
	_wait_until_deleted(_rmtree_inner, path, waitall=True)

def _force_run(path, func, *args):
	try:
		return func(*args)
	except OSError as err:
		os.chmod(path, stat.S_IRWXU)
		return func(*args)

def _wait_until_deleted(func, pathname, waitall=False):
	# Perform the operation
	func(pathname)
	# Now setup the wait loop
	if waitall:
		dirname = pathname
	else:
		dirname, name = os.path.split(pathname)
		dirname = dirname or '.'
	# Check for `pathname` to be removed from the filesystem.
	# The exponential backoff of the timeout amounts to a total
	# of ~1 second after which the deletion is probably an error
	# anyway.
	# Testing on an i7@4.3GHz shows that usually only 1 iteration is
	# required when contention occurs.
	timeout = 0.001
	while timeout < 1.0:
		# Note we are only testing for the existence of the file(s) in
		# the contents of the directory regardless of any security or
		# access rights.  If we have made it this far, we have sufficient
		# permissions to do that much using Python's equivalent of the
		# Windows API FindFirstFile.
		# Other Windows APIs can fail or give incorrect results when
		# dealing with files that are pending deletion.
		try:
			L = os.listdir(dirname)
		except FileNotFoundError:
			return
		if not (L if waitall else name in L):
			return
		# Increase the timeout and try again
		time.sleep(timeout)
		timeout *= 2
	raise OSError(
		'Timeout expired while waiting for %s to be deleted.' % pathname
	)