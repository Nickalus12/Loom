from typing import Protocol, runtime_checkable


@runtime_checkable
class LanguageParser(Protocol):
    extensions: list[str]

    def parse(self, content: str) -> list[dict]: ...


@runtime_checkable
class MemoryBackend(Protocol):
    async def build_indices_and_constraints(self) -> None: ...

    async def search_(self, query: str, limit: int) -> object: ...

    async def close(self) -> None: ...
