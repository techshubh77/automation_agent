class MarkdownParser:
    @staticmethod
    def parse_file_content(file_content: bytes) -> str:
        """
        Takes raw Markdown file bytes and converts them into a plain text string.
        """
        # Decode the raw bytes to a UTF-8 string and strip leading/trailing whitespace
        return file_content.decode("utf-8").strip()
