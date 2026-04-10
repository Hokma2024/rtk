import json
import uuid

import pytest
import structlog

import common.logging as _logging_mod
from common.logging import (
    bind_trace_id,
    clear_trace_id,
    configure_logging,
    get_logger,
    get_or_create_trace_id,
)


@pytest.fixture(autouse=True)
def _reset():
    """Сброс trace-id и contextvars structlog перед каждым тестом.

    ПРИМЕЧАНИЕ: configure_logging() имеет защиту _configured на уровне модуля,
    чтобы продакшен-сервисы настраивали structlog только один раз. Тесты,
    которым нужно конкретное имя сервиса, должны временно сбросить этот флаг.
    """
    clear_trace_id()
    structlog.contextvars.clear_contextvars()
    yield
    clear_trace_id()
    structlog.contextvars.clear_contextvars()


def test_configure_logging_is_idempotent():
    configure_logging("svc-a", "INFO")
    configure_logging("svc-a", "INFO")  # не должно бросать исключение


def test_get_logger_returns_bound_logger():
    configure_logging("svc-a", "INFO")
    log = get_logger("mymod")
    assert hasattr(log, "info")


def test_get_or_create_trace_id_generates_when_missing():
    tid = get_or_create_trace_id(None)
    uuid.UUID(tid)


def test_get_or_create_trace_id_accepts_valid_uuid():
    incoming = str(uuid.uuid4())
    assert get_or_create_trace_id(incoming) == incoming


def test_get_or_create_trace_id_replaces_invalid_input():
    tid = get_or_create_trace_id("not-a-uuid")
    uuid.UUID(tid)
    assert tid != "not-a-uuid"


def test_bind_trace_id_propagates_into_log_record(capsys):
    # Принудительно заставляем configure_logging перепривязать имя сервиса для этого теста.
    # configure_logging() пропускает переконфигурацию при _configured == True
    # (корректное поведение в продакшене). Здесь мы временно сбрасываем флаг,
    # чтобы протестировать с известным именем сервиса независимо от порядка импортов.
    orig = _logging_mod._configured
    _logging_mod._configured = False
    try:
        configure_logging("svc-a", "INFO")
    finally:
        _logging_mod._configured = orig

    log = get_logger("mymod")
    tid = str(uuid.uuid4())
    bind_trace_id(tid)
    log.info("hello", foo="bar")
    captured = capsys.readouterr().out.strip()
    record = json.loads(captured.splitlines()[-1])
    assert record["trace_id"] == tid
    assert record["service"] == "svc-a"
    assert record["event"] == "hello"
    assert record["foo"] == "bar"
