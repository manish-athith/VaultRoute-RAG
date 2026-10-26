import re

from vaultroute_rag.documents.schemas import TextChunk


class OverlappingWordChunker:
    """Deterministic word-window chunking with source character offsets."""

    def __init__(self, chunk_size_words: int = 220, overlap_words: int = 40) -> None:
        if chunk_size_words < 1:
            raise ValueError("chunk_size_words must be positive")
        if overlap_words < 0 or overlap_words >= chunk_size_words:
            raise ValueError("overlap_words must be between zero and chunk size")
        self.chunk_size_words = chunk_size_words
        self.overlap_words = overlap_words

    def split(self, text: str) -> list[TextChunk]:
        words = list(re.finditer(r"\S+", text))
        if not words:
            return []

        chunks: list[TextChunk] = []
        step = self.chunk_size_words - self.overlap_words
        for start_word in range(0, len(words), step):
            end_word = min(start_word + self.chunk_size_words, len(words))
            char_start = words[start_word].start()
            char_end = words[end_word - 1].end()
            chunks.append(
                TextChunk(
                    index=len(chunks),
                    text=text[char_start:char_end],
                    word_count=end_word - start_word,
                    char_start=char_start,
                    char_end=char_end,
                )
            )
            if end_word == len(words):
                break
        return chunks
