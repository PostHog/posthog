"""Early-loaded pytest plugin (see `-p pytest_boot_gc` in pytest.ini) that opens the
boot GC window before django.setup() runs.

The boot window itself (freeze + re-enable + thresholds) lives in the root
conftest.py (`_end_gc_boot_window`). But conftest files load *after*
pytest-django's load_initial_conftests has run django.setup(), so the several
million permanent allocations of settings + app population still paid automatic
GC pauses (~0.2s per process). `-p` plugins load before initial conftests, which
puts django.setup() inside the window too. Everything here must stay import-light:
this module runs before any of the test session's real setup.
"""

import gc

gc.disable()
