from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import pytest


class _PatchProxy:
    def __init__(self, active_patches: list[patch]) -> None:
        self._active_patches = active_patches

    def object(self, target, attribute: str, *args, **kwargs):
        active = patch.object(target, attribute, *args, **kwargs)
        mocked = active.start()
        self._active_patches.append(active)
        return mocked


class SimpleMocker:
    def __init__(self) -> None:
        self._active_patches: list[patch] = []
        self.patch = _PatchProxy(self._active_patches)

    def stopall(self) -> None:
        while self._active_patches:
            active = self._active_patches.pop()
            active.stop()


@pytest.fixture
def mocker() -> Generator[SimpleMocker, None, None]:
    fixture = SimpleMocker()
    try:
        yield fixture
    finally:
        fixture.stopall()
