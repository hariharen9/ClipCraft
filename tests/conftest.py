import os
import sys
import pytest

@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """Exit process cleanly right after pytest prints full summary, preventing PySide6 C++ destructor abort on Windows."""
    yield
    sys.stdout.flush()
    sys.stderr.flush()
    code = exitstatus if isinstance(exitstatus, int) else getattr(exitstatus, "value", 0)
    os._exit(code)
