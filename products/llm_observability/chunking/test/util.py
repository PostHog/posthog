import os
from contextlib import contextmanager


@contextmanager
def load_fixture(file_name: str):
    file_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(file_dir, "fixtures", file_name)) as f:
        yield f.read()
