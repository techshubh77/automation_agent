from enum import StrEnum


class SourceType(StrEnum):
    """
    Enum for validating the source type of an ingested document.
    Only these two values are accepted by the ingestion API.
    """
    KNOWLEDGE_BASE = "knowledge_base"
    API_DOC = "api_doc"
