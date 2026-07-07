import json
from typing import Any


class JsonParser:
    @staticmethod
    def flatten_json(
        data: dict[str, Any] | list, parent_key: str = "", sep: str = " -> "
    ) -> str:
        """
        Recursively flattens a nested JSON object into a readable text format.
        Example: {"user": {"name": "John"}} becomes "user -> name: John"
        """
        items = []
        if isinstance(data, dict):
            for k, v in data.items():
                new_key = f"{parent_key}{sep}{k}" if parent_key else k
                if isinstance(v, (dict, list)):
                    items.extend(
                        JsonParser.flatten_json(v, new_key, sep=sep).split("\n")
                    )
                else:
                    items.append(f"{new_key}: {v}")
        elif isinstance(data, list):
            for i, v in enumerate(data):
                new_key = f"{parent_key}[{i}]" if parent_key else f"[{i}]"
                if isinstance(v, (dict, list)):
                    items.extend(
                        JsonParser.flatten_json(v, new_key, sep=sep).split("\n")
                    )
                else:
                    items.append(f"{new_key}: {v}")

        return "\n".join(items)

    @staticmethod
    def parse_file_content(file_content: bytes) -> str:
        """
        Takes raw file bytes, loads it as JSON, and flattens it into text.
        """
        try:
            # Decode bytes to string and load JSON
            json_data = json.loads(file_content.decode("utf-8"))
            return JsonParser.flatten_json(json_data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON file: {e!s}") from e
