import json
from typing import Any


class JsonParser:
    @staticmethod
    def _flatten(data: Any, parent_key: str = "", sep: str = " -> ") -> list[str]:
        if isinstance(data, dict):
            return JsonParser._flatten_dict(data, parent_key, sep)
        if isinstance(data, list):
            return JsonParser._flatten_list(data, parent_key, sep)
        return [f"{parent_key}: {data}"] if parent_key else [str(data)]

    @staticmethod
    def _flatten_dict(data: dict[str, Any], parent_key: str, sep: str) -> list[str]:
        items = []
        for k, v in data.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else str(k)
            items.extend(JsonParser._flatten(v, new_key, sep))
        return items

    @staticmethod
    def _flatten_list(data: list, parent_key: str, sep: str) -> list[str]:
        items = []
        for i, v in enumerate(data):
            new_key = f"{parent_key}[{i}]" if parent_key else f"[{i}]"
            items.extend(JsonParser._flatten(v, new_key, sep))
        return items

    @staticmethod
    def flatten_json(
        data: dict[str, Any] | list, parent_key: str = "", sep: str = " -> "
    ) -> str:
        """
        Recursively flattens a nested JSON object into a readable text format.
        Example: {"user": {"name": "John"}} becomes "user -> name: John"
        """
        items = JsonParser._flatten(data, parent_key, sep)
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
