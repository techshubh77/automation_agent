import json
from typing import Any

class JsonParser:
    @staticmethod
    def parse_file_content(file_content: bytes) -> list[dict[str, Any]]:
        """
        Takes raw file bytes, loads it as JSON, and returns the parsed list of dictionaries.
        If the root is a single dictionary, it wraps it in a list.
        """
        try:
            json_data = json.loads(file_content.decode("utf-8"))
            if isinstance(json_data, dict):
                return [json_data]
            elif isinstance(json_data, list):
                return json_data
            else:
                raise ValueError("JSON root must be an object or an array of objects.")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON file: {e!s}") from e
