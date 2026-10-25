from __future__ import annotations

from collections.abc import Iterator

import pytest

from schemadiff import urls


@pytest.fixture(autouse=True)
def _fresh_secret_registry() -> Iterator[None]:
    urls._secrets.clear()
    yield
    urls._secrets.clear()
