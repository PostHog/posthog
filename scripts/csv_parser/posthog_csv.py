import csv
from typing import Dict
from datetime import datetime
from requests import sessions

import pandas as pd
import posthog


class PosthogCSV():
    """
    Interface for managing CSVs in Posthog.
    """

    def __init__(self, path: str, settings: Dict) -> None:
        """
        Constructs the object.

        Arguments:
            path(str): Path to the CSV.
            settings(Dict): Settings for parsing and publishing.
        """
        self.path = path
        self.settings = settings
        self.parsed_csv = None
        self.session = sessions.Session()

    def _parse_csv(self) -> pd.DataFrame:
        """
        Parse a csv according to the specified settings.

        Returns:
            Parsed CSV according to the specified settings.
        """
        return pd.read_csv(self.path, **self.settings["parsing"])

    def preview(self) -> None:
        """
        Preview the CSV.
        """
        self.parsed_csv = self._parse_csv()

        print(self.parsed_csv.head(5))
        return None

    def _data_for_post(self, df):
        return[
            {"properties": row, "event": "test", "timestamp": datetime.now()}
            for row in df.to_dict(orient='records')
        ]

    def send(self) -> None:
        """
        Publish the parsed csv to posthog.
        """
        print("Sending")
        self.parsed_csv = self._parse_csv()

        data = {
            "api_key": "api_key",
            "batch": self._data_for_post(self.parsed_csv)
        }

        request = self.session.post(
            "http://127.0.0.1:8000/batch",
            data=data,
            headers={'Content-Type': 'application/json'},
        )

        return None