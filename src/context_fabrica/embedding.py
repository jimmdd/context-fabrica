from __future__ import annotations

import hashlib
from dataclasses import dataclass
from importlib import import_module
from math import sqrt
from typing import Protocol


class Embedder(Protocol):
    dimensions: int

    def embed(self, text: str) -> list[float]: ...


@dataclass(frozen=True)
class Chunk:
    text: str
    chunk_index: int


def chunk_text(text: str, *, max_chars: int = 800, overlap: int = 120) -> list[Chunk]:
    normalized = " ".join(text.split())
    if not normalized:
        return []

    chunks: list[Chunk] = []
    start = 0
    index = 0
    while start < len(normalized):
        end = min(len(normalized), start + max_chars)
        chunks.append(Chunk(text=normalized[start:end], chunk_index=index))
        if end == len(normalized):
            break
        start = max(end - overlap, start + 1)
        index += 1
    return chunks


class HashEmbedder:
    def __init__(self, dimensions: int = 1536) -> None:
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        values = [0.0] * self.dimensions
        tokens = text.lower().split()
        if not tokens:
            return values

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            slot = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            magnitude = (digest[5] / 255.0) + 0.1
            values[slot] += sign * magnitude

        norm = sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        SentenceTransformer = import_module("sentence_transformers").SentenceTransformer
        self._model = SentenceTransformer(model_name)
        self.dimensions = int(self._model.get_sentence_embedding_dimension())

    def embed(self, text: str) -> list[float]:
        return list(self._model.encode(text, normalize_embeddings=True))


class FastEmbedEmbedder:
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        TextEmbedding = import_module("fastembed").TextEmbedding
        self._model = TextEmbedding(model_name=model_name)
        self.dimensions = 384

    def embed(self, text: str) -> list[float]:
        return list(next(self._model.embed([text])))


def build_default_embedder(dimensions: int = 1536, prefer_transformer: bool = False) -> Embedder:
    if dimensions == 384:
        try:
            return FastEmbedEmbedder()
        except ModuleNotFoundError:
            pass
    if prefer_transformer:
        try:
            embedder = SentenceTransformerEmbedder()
            if embedder.dimensions == dimensions:
                return embedder
        except ModuleNotFoundError:
            pass
    return HashEmbedder(dimensions=dimensions)
