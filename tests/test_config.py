"""Reference metadata contracts; no API calls or database required."""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from vn_air.config import StudyConfig, load_config
from vn_air.database.setup import database_engine


ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads((ROOT / "configs/study.json").read_text())

    def test_reviewed_configuration(self):
        config = load_config(ROOT / "configs/study.json")
        self.assertEqual(len(config.locations), 5)
        self.assertEqual({s.external_sensor_id for s in config.sensors}, {"11357424", "14581375"})
        self.assertFalse(any(s.location_id == "da_nang" for s in config.sensors))

    def test_unknown_keys_and_secret_options_rejected(self):
        for change in ({"secret": "not-a-real-key"}, {"options": {"apikey": "not-a-real-key"}}):
            with self.subTest(change=change):
                document = json.loads(json.dumps(self.document))
                document["products"][0].update(change)
                with self.assertRaises(ValidationError):
                    StudyConfig.model_validate_json(json.dumps(document))

    def test_coordinate_country_timezone_and_type_validation(self):
        for name, value in (("latitude", 91), ("longitude", float("nan")), ("country_code", "US"), ("provider_timezone", "Bad/Zone"), ("latitude", "21.0")):
            with self.subTest(name=name):
                document = json.loads(json.dumps(self.document))
                document["locations"][0][name] = value
                with self.assertRaises(ValidationError):
                    StudyConfig.model_validate_json(json.dumps(document))

    def test_unknown_station_or_modeled_sensor_source_rejected(self):
        for name, value in (("location_id", "da_nang"), ("product_id", "open_meteo_cams_global"), ("canonical_unit", "USAQI")):
            with self.subTest(name=name):
                document = json.loads(json.dumps(self.document))
                document["sensors"][0][name] = value
                with self.assertRaises(ValidationError):
                    StudyConfig.model_validate_json(json.dumps(document))

    def test_duplicate_identifiers_rejected(self):
        self.document["locations"].append(self.document["locations"][0])
        with self.assertRaises(ValidationError):
            StudyConfig.model_validate_json(json.dumps(self.document))

    def test_database_selection_is_explicit_and_postgres_only(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError):
                database_engine()
        for url in ("sqlite:///:memory:", "postgresql:///postgres", "postgresql:///template1"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                database_engine(url)
        engine = database_engine("postgresql://user@example.supabase.co/postgres")
        self.assertEqual(engine.url.query["sslmode"], "require")
        engine.dispose()
        engine = database_engine("postgresql://user@example.supabase.co/postgres?sslmode=require")
        self.assertEqual(engine.url.database, "postgres")
        engine.dispose()
