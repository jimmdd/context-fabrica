from src.context_fabrica.embedding import HashEmbedder, chunk_text


def test_chunk_text_splits_long_text() -> None:
    chunks = chunk_text("alpha " * 400, max_chars=100, overlap=20)
    assert len(chunks) > 1
    assert chunks[0].chunk_index == 0


def test_hash_embedder_returns_unit_length_vectors() -> None:
    embedder = HashEmbedder(dimensions=16)
    vector = embedder.embed("AuthService depends on TokenSigner")
    assert len(vector) == 16
    assert round(sum(value * value for value in vector), 5) == 1.0
