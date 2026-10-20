import os
import sys
import pytest

TEST_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test_lab.db")
os.environ["LAB_DB_PATH"] = TEST_DB_PATH

@pytest.fixture(scope="session", autouse=True)
def cleanup_test_db():
    yield
    # Cleanup test db files after test session
    for ext in ["", "-wal", "-shm"]:
        fpath = TEST_DB_PATH + ext
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except OSError:
                pass
