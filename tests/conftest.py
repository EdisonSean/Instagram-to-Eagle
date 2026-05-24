from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture
def project_tmp_path() -> Path:
    path = Path(".tmp") / "tests" / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path
