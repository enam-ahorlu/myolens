"""An in-memory ``DocumentStore``, used only by tests.

Implements the same get/set/update/query surface the real Firestore adapter does, so a test
exercises the contract the routers were written against rather than a router-specific mock. See
``app.adapters.firestore_repo.DocumentStore``.
"""

from __future__ import annotations

from typing import Any


class FakeDocumentStore:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict[str, Any]]] = {}

    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        doc = self._data.get(collection, {}).get(doc_id)
        return dict(doc) if doc is not None else None

    def set(self, collection: str, doc_id: str, data: dict[str, Any]) -> None:
        self._data.setdefault(collection, {})[doc_id] = dict(data)

    def update(self, collection: str, doc_id: str, data: dict[str, Any]) -> None:
        self._data.setdefault(collection, {}).setdefault(doc_id, {}).update(data)

    def delete(self, collection: str, doc_id: str) -> None:
        # Idempotent, like Firestore's own delete: removing an already-absent document is not
        # an error.
        self._data.get(collection, {}).pop(doc_id, None)

    def query(self, collection: str, **filters: Any) -> list[dict[str, Any]]:
        docs = self._data.get(collection, {}).values()
        return [
            dict(doc)
            for doc in docs
            if all(doc.get(field) == value for field, value in filters.items())
        ]
