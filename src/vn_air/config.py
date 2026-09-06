"""Strict reviewed metadata, not automatic station or licensing qualification."""

import json
from datetime import date
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator, model_validator


Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$", min_length=1)]
Domain = Literal["weather", "air_quality"]
Kind = Literal["measurement", "reanalysis", "forecast"]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_min_length=1)


class Product(Record):
    id: Identifier
    provider: str
    domain: Domain
    data_kind: Kind
    endpoint: str
    attribution: str
    licence_url: str
    options: dict[str, str] = Field(default_factory=dict)

    @field_validator("endpoint", "licence_url")
    @classmethod
    def safe_url(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Use a credential-free HTTPS URL without query or fragment")
        return value

    @field_validator("options")
    @classmethod
    def public_options(cls, value):
        if set(value) - {"models", "domains", "timezone", "timeformat", "wind_speed_unit", "temperature_unit", "precipitation_unit"}:
            raise ValueError("Unknown option: credentials and arbitrary API parameters do not belong in metadata")
        return value


class Variable(Record):
    code: Identifier
    domain: Domain
    representation: Literal["weather", "concentration", "index"]
    canonical_unit: str
    minimum: FiniteFloat | None = None
    maximum: FiniteFloat | None = None
    temporal_support: Literal["instant", "preceding_hour_mean", "preceding_hour_sum"]

    @model_validator(mode="after")
    def check_bounds(self):
        if self.minimum is not None and self.maximum is not None and self.minimum >= self.maximum:
            raise ValueError("Invalid physical bounds")
        if (self.domain == "weather") != (self.representation == "weather"):
            raise ValueError("Variable domain/representation mismatch")
        return self


class Location(Record):
    id: Identifier
    name: str
    kind: Literal["city", "station"]
    parent_id: Identifier | None = None
    country_code: Literal["VN"]
    latitude: Annotated[FiniteFloat, Field(ge=-90, le=90)]
    longitude: Annotated[FiniteFloat, Field(ge=-180, le=180)]
    timezone: Literal["Asia/Ho_Chi_Minh"]
    provider_timezone: str
    geonames_id: Annotated[int, Field(gt=0)] | None = None

    @field_validator("provider_timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (KeyError, ValueError) as error:
            raise ValueError("Unknown provider timezone") from error
        return value

    @model_validator(mode="after")
    def parent_contract(self):
        if (self.kind == "city") != (self.parent_id is None):
            raise ValueError("Cities are roots; stations require a city-context parent")
        if self.geonames_id is not None and self.kind != "city":
            raise ValueError("GeoNames IDs describe city seeds, not sensor IDs")
        return self


class Sensor(Record):
    id: Identifier
    location_id: Identifier
    product_id: Identifier
    external_sensor_id: Annotated[str, Field(pattern=r"^[1-9][0-9]*$")]
    external_location_id: Annotated[str, Field(pattern=r"^[1-9][0-9]*$")]
    variable_code: Identifier
    canonical_unit: str
    instrument: str
    is_reference_monitor: bool
    licence_url: str
    licence_valid_from: date
    licence_valid_to: date | None = None
    attribution: str
    qualification_notes: str

    @field_validator("licence_url")
    @classmethod
    def safe_licence(cls, value):
        return Product.safe_url(value)

    @model_validator(mode="after")
    def licence_period(self):
        if self.licence_valid_to is not None and self.licence_valid_to < self.licence_valid_from:
            raise ValueError("Licence date range is reversed")
        return self


class StudyConfig(Record):
    version: Literal[1]
    products: list[Product] = Field(min_length=1)
    variables: list[Variable] = Field(min_length=1)
    locations: list[Location] = Field(min_length=1)
    sensors: list[Sensor]

    @model_validator(mode="after")
    def references(self):
        for rows, key in ((self.products, "id"), (self.variables, "code"), (self.locations, "id"), (self.sensors, "id")):
            identifiers = [getattr(row, key) for row in rows]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError("Duplicate reference identifier")
        products = {row.id: row for row in self.products}
        variables = {row.code: row for row in self.variables}
        locations = {row.id: row for row in self.locations}
        external = [(row.product_id, row.external_sensor_id) for row in self.sensors]
        if len(external) != len(set(external)):
            raise ValueError("Duplicate external sensor identity")
        geonames = [row.geonames_id for row in self.locations if row.geonames_id is not None]
        if len(geonames) != len(set(geonames)):
            raise ValueError("Duplicate GeoNames identifier")
        for row in self.locations:
            if row.parent_id is not None and (row.parent_id not in locations or locations[row.parent_id].kind != "city"):
                raise ValueError("Station parent must reference a configured city")
        for row in self.sensors:
            if row.location_id not in locations or locations[row.location_id].kind != "station":
                raise ValueError("Sensor must reference a station")
            if row.product_id not in products or (products[row.product_id].domain, products[row.product_id].data_kind) != ("air_quality", "measurement"):
                raise ValueError("Sensor product must supply measured air-quality data")
            if row.variable_code not in variables:
                raise ValueError("Unknown sensor variable")
            variable = variables[row.variable_code]
            if (variable.domain, variable.representation, variable.canonical_unit) != ("air_quality", "concentration", row.canonical_unit):
                raise ValueError("Sensor must use the canonical concentration variable/unit")
        return self


def load_config(path: Path) -> StudyConfig:
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON object key")
            result[key] = value
        return result

    content = path.read_text(encoding="utf-8")
    json.loads(content, object_pairs_hook=unique_keys)
    return StudyConfig.model_validate_json(content)
