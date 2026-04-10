"""Общие pytest-фикстуры для тестового набора."""

from __future__ import annotations

import copy
from datetime import datetime

import pytest

from common.models import Ticket
from services.mcp_server import storage

# Снимок исходного состояния делается на этапе импорта, чтобы зафиксировать
# данные до того, как какой-либо тест их модифицирует.
_ORIG_LOGS_DB = copy.deepcopy(storage.LOGS_DB)
_ORIG_ORDERS_DB = copy.deepcopy(storage.ORDERS_DB)
_ORIG_EISSD_DB = copy.deepcopy(storage.EISSD_DB)
_ORIG_OTRS_TICKETS = copy.deepcopy(storage.OTRS_TICKETS)
_ORIG_OTRS_COMMENTS = copy.deepcopy(storage.OTRS_COMMENTS)


@pytest.fixture(autouse=True)
def reset_storage():
    storage.LOGS_DB.clear()
    storage.LOGS_DB.update(copy.deepcopy(_ORIG_LOGS_DB))
    storage.ORDERS_DB.clear()
    storage.ORDERS_DB.update(copy.deepcopy(_ORIG_ORDERS_DB))
    storage.EISSD_DB.clear()
    storage.EISSD_DB.update(copy.deepcopy(_ORIG_EISSD_DB))
    storage.OTRS_TICKETS.clear()
    storage.OTRS_TICKETS.update(copy.deepcopy(_ORIG_OTRS_TICKETS))
    storage.OTRS_COMMENTS.clear()
    storage.OTRS_COMMENTS.extend(copy.deepcopy(_ORIG_OTRS_COMMENTS))
    yield
    storage.LOGS_DB.clear()
    storage.LOGS_DB.update(copy.deepcopy(_ORIG_LOGS_DB))
    storage.ORDERS_DB.clear()
    storage.ORDERS_DB.update(copy.deepcopy(_ORIG_ORDERS_DB))
    storage.EISSD_DB.clear()
    storage.EISSD_DB.update(copy.deepcopy(_ORIG_EISSD_DB))
    storage.OTRS_TICKETS.clear()
    storage.OTRS_TICKETS.update(copy.deepcopy(_ORIG_OTRS_TICKETS))
    storage.OTRS_COMMENTS.clear()
    storage.OTRS_COMMENTS.extend(copy.deepcopy(_ORIG_OTRS_COMMENTS))


@pytest.fixture
def sample_ticket() -> Ticket:
    return Ticket(
        id="TKT-001",
        order_id="1800003902272",
        subject="Test ticket",
        annotation="Order denied",
        description="Order was denied, need investigation",
        region="MSK",
        queue=None,
        created_at=datetime(2025, 9, 15, 12, 0, 0),
    )


@pytest.fixture
def sample_ticket_no_error() -> Ticket:
    return Ticket(
        id="TKT-002",
        order_id="1800003879400",
        subject="Normal ticket",
        annotation="Routine check",
        description="Routine check on order status",
        region="SPB",
        queue=None,
        created_at=datetime(2025, 9, 15, 12, 0, 0),
    )


@pytest.fixture
def sample_ticket_unknown() -> Ticket:
    return Ticket(
        id="TKT-003",
        order_id="9999999999999",
        subject="Unknown order",
        annotation="",
        description="Order not found in system",
        region="COMMON",
        queue=None,
        created_at=datetime(2025, 9, 15, 12, 0, 0),
    )
