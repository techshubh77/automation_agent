class MarkdownParser:
    @staticmethod
    def parse_file_content(file_content: bytes) -> str:
        """
        Takes raw Markdown file bytes and converts them into a plain text string.

        Why is this so simple compared to JsonParser?
        Markdown is already human-readable text. Unlike JSON (which is a nested
        data structure that we need to flatten and label), Markdown is written
        to be read as-is. The headings (# Title), bullet points (- item), and
        paragraphs are already in a format that makes perfect semantic sense for
        an AI embedding model to understand.

        So we just decode the bytes to a UTF-8 string and hand it directly to
        the TextChunker. No transformation needed.
        """
        # Decode the raw bytes to a UTF-8 string and strip leading/trailing whitespace
        return file_content.decode("utf-8").strip()
