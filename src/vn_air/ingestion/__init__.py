"""Bounded ingestion of measured and modeled environmental data."""

PIPELINE_VERSION = "0.3.0"


class IngestionError(Exception):
    """Only constant diagnostic codes belong in user-visible errors."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)
