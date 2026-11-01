"""Данные для тестов интеграции."""

from decimal import Decimal

import pytest


@pytest.fixture
def account_data():
    return {
        "client_id": "99",
        "contracts": {
            "123": {
                "id": 10,
                "balance": Decimal("1859.25"),
                "number": "TEST-001",
                "loyalty_member_balance": 150,
                "account_balance_dt": "2026-11-01T10:00:00",
                "devices": {
                    "7": {
                        "pan": "TEST-TRANSPONDER",
                        "status": "valid",
                        "status_id": 3,
                        "interoperability": "connected",
                        "iop_status_id": 2,
                    }
                },
            }
        },
        "vehicles": {
            "test-vehicle": {
                "plate": "А000АА00",
                "country": "RUS",
                "debt": Decimal("150.50"),
                "violations_count": 2,
            }
        },
    }
