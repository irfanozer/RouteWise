import pytest
from alembic.config import Config
from pydantic import ValidationError

from routewise.config import Settings, alembic_database_url


def test_default_database_uses_reserved_local_postgres_port() -> None:
    assert "@localhost:5436/routewise" in Settings().database_url


def test_cors_origins_accept_csv_and_json() -> None:
    csv = Settings(cors_origins="http://one.test, http://two.test")
    json_value = Settings(cors_origins='["http://one.test", "http://two.test"]')

    assert csv.cors_origins == ["http://one.test", "http://two.test"]
    assert json_value.cors_origins == csv.cors_origins


def test_alembic_database_url_accepts_percent_encoded_production_password() -> None:
    database_url = (
        "postgresql+asyncpg://routewise_admin:Rw9%21safe%2Bvalue@database.test:5432/routewise"
        "?ssl=require"
    )
    config = Config()

    config.set_main_option("sqlalchemy.url", alembic_database_url(database_url))

    assert config.get_main_option("sqlalchemy.url") == database_url


def test_cache_size_is_bounded() -> None:
    with pytest.raises(ValidationError):
        Settings(route_cache_entries=1)


def test_route_run_retention_has_safe_default_and_validated_range() -> None:
    assert Settings().max_route_runs == 5_000
    assert Settings(max_route_runs=10).max_route_runs == 10

    with pytest.raises(ValidationError):
        Settings(max_route_runs=9)
    with pytest.raises(ValidationError):
        Settings(max_route_runs=100_001)


def test_route_run_retention_reads_routewise_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ROUTEWISE_MAX_ROUTE_RUNS", "750")

    assert Settings(_env_file=None).max_route_runs == 750
