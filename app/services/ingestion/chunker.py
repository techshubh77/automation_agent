# Chunker placeholder

from langchain_text_splitters import RecursiveCharacterTextSplitter


class TextChunker:
    @staticmethod
    def chunk_text(
        text: str, chunk_size: int = 1000, chunk_overlap: int = 100
    ) -> list[str]:
        """
        Splits a large text block into smaller overlapping chunks.
        We use characters instead of strict tokens for speed in this MVP.
        1000 characters is roughly equal to ~250 tokens.
        """
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
            separators=[
                "\n\n",
                "\n",
                " ",
                "",
            ],  # Tries to split on double newlines first to keep JSON blocks together
        )

        return text_splitter.split_text(text)
