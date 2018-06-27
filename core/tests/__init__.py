from core import LocalFileSystem
from fman.url import splitscheme

class StubUI:
	def __init__(self, test_case):
		self._expected_alerts = []
		self._expected_prompts = []
		self._test_case = test_case
	def expect_alert(self, args, answer):
		self._expected_alerts.append((args, answer))
	def expect_prompt(self, args, answer):
		self._expected_prompts.append((args, answer))
	def verify_expected_dialogs_were_shown(self):
		self._test_case.assertEqual(
			[], self._expected_alerts, 'Did not receive all expected alerts.'
		)
		self._test_case.assertEqual(
			[], self._expected_prompts, 'Did not receive all expected prompts.'
		)
	def show_alert(self, *args, **_):
		if not self._expected_alerts:
			self._test_case.fail('Unexpected alert: %r' % args[0])
			return
		expected_args, answer = self._expected_alerts.pop(0)
		self._test_case.assertEqual(expected_args, args, "Wrong alert")
		return answer
	def show_prompt(self, *args, **_):
		if not self._expected_prompts:
			self._test_case.fail('Unexpected prompt: %r' % args[0])
			return
		expected_args, answer = self._expected_prompts.pop(0)
		self._test_case.assertEqual(expected_args, args, "Wrong prompt")
		return answer
	def show_status_message(self, _):
		pass
	def clear_status_message(self):
		pass

class StubFS:
	def __init__(self, backend=None):
		if backend is None:
			backend = LocalFileSystem()
		self._backend = backend
	def is_dir(self, url):
		return self._backend.is_dir(self._as_path(url))
	def exists(self, url):
		return self._backend.exists(self._as_path(url))
	def samefile(self, url1, url2):
		return self._backend.samefile(self._as_path(url1), self._as_path(url2))
	def iterdir(self, url):
		return self._backend.iterdir(self._as_path(url))
	def makedirs(self, url, exist_ok=False):
		self._backend.makedirs(self._as_path(url), exist_ok=exist_ok)
	def copy(self, src_url, dst_url):
		self._backend.copy(src_url, dst_url)
	def delete(self, url):
		self._backend.delete(self._as_path(url))
	def move(self, src_url, dst_url):
		self._backend.move(src_url, dst_url)
	def touch(self, url):
		self._backend.touch(self._as_path(url))
	def mkdir(self, url):
		self._backend.mkdir(self._as_path(url))
	def query(self, url, fs_method_name):
		path = self._as_path(url)
		return getattr(self._backend, fs_method_name)(path)
	def _as_path(self, url):
		scheme, path = splitscheme(url)
		required_scheme = self._backend.scheme
		if scheme != required_scheme:
			raise ValueError(
				'This stub implementation only supports %s urls.' %
				required_scheme
			)
		return path