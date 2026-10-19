"""Retrieve the most relevant document chunks for a question."""


def retrieve(collection, question_embedding: list[float], n_results: int = 3) -> list[dict[str, object]]:
    """Query Chroma and return chunk text, metadata, and distance."""
    if collection.count() == 0:
        return []
    results = collection.query(
        query_embeddings=[question_embedding],
        n_results=min(n_results, collection.count()),
        include=["documents", "metadatas", "distances"],
    )
    documents = results["documents"][0] or []
    metadatas = results["metadatas"][0] or []
    distances = results["distances"][0] or []
    return [
        {"text": text, "metadata": metadata, "distance": distance}
        for text, metadata, distance in zip(documents, metadatas, distances)
    ]
