"""Tests for the privacy boundary and portal parser."""

from datetime import date, datetime
from decimal import Decimal
from http.cookies import SimpleCookie
from typing import Any

import pytest

from custom_components.thai_easypass.api import (
    BANGKOK,
    EasyPassClient,
    InvalidAuth,
    TwoFactorUnsupported,
    extract_csrf_token,
    parse_money,
    parse_transaction_datetime,
    summarize_usage,
)


class FakeResponse:
    """Small aiohttp response double."""

    def __init__(
        self,
        *,
        status: int = 200,
        text: str = "",
        payload: Any = None,
    ) -> None:
        self.status = status
        self._text = text
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def text(self) -> str:
        return self._text

    async def json(self, *, content_type=None) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeCookieJar:
    def filter_cookies(self, url: str) -> SimpleCookie:
        cookies = SimpleCookie()
        cookies["XSRF-TOKEN"] = "encoded%20token"
        return cookies


class FakeSession:
    """Queue-backed aiohttp ClientSession double."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.cookie_jar = FakeCookieJar()

    def _next(self, method: str, url: str, kwargs: dict[str, Any]) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._next("GET", url, kwargs)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._next("POST", url, kwargs)


def card_row(card_id: str, balance: str, account: str) -> dict[str, str]:
    """Return a synthetic card without real customer data."""
    return {
        "SmartcardID": card_id,
        "AccountNumber": account,
        "AC_Balance": balance,
        "CardName": f"Test card {card_id[-1]}",
        "PlateNo": "TEST-0000",
    }


def test_extract_csrf_token_from_supported_markup() -> None:
    assert extract_csrf_token('<meta name="csrf-token" content="meta-token">') == (
        "meta-token"
    )
    assert extract_csrf_token(
        '<form><input name="_token" value="input-token"></form>'
    ) == "input-token"
    assert extract_csrf_token("<html></html>") is None


def test_money_and_transaction_time_parsing() -> None:
    assert parse_money("1,234.567") == Decimal("1234.57")
    assert parse_money("-60", absolute=True) == Decimal("60.00")
    assert parse_money("-60") == Decimal("-60.00")
    assert parse_transaction_datetime("11/08/2026 08:48:32") == datetime(
        2026, 8, 11, 8, 48, 32, tzinfo=BANGKOK
    )
    assert parse_transaction_datetime("11/08/2569 08:48") == datetime(
        2026, 8, 11, 8, 48, tzinfo=BANGKOK
    )


def test_usage_summary_handles_languages_cancellation_and_unsorted_rows() -> None:
    rows = [
        {
            "txn_desc": "ผ่านทาง",
            "txn_amt": "60",
            "txn_date": "10/08/2026 08:00:00",
            "txn_balance": "440",
            "location": "Gate A",
            "position": "01",
        },
        {
            "txn_desc": "Topup",
            "txn_amt": "500",
            "txn_date": "01/08/2026 12:00:00",
        },
        {
            "txn_desc": "Cancel Pass Through",
            "txn_amt": "10",
            "txn_date": "10/08/2026 09:00:00",
        },
        {
            "txn_desc": "Pass Through",
            "txn_amt": "50",
            "txn_date": "12/08/2026 18:30:00",
            "txn_balance": "390",
            "location": "Gate B",
            "position": "02",
        },
        {"txn_desc": "Synthetic other", "txn_amt": "5"},
    ]
    result = summarize_usage(rows, date(2026, 8, 12))

    assert result.toll_total == Decimal("100.00")
    assert result.topup_total == Decimal("500.00")
    assert result.other_total == Decimal("5.00")
    assert result.trip_count == 2
    assert result.last_trip is not None
    assert result.last_trip.location == "Gate B"
    assert result.period_start == datetime(2026, 8, 1, tzinfo=BANGKOK)


@pytest.mark.asyncio
async def test_login_success_and_fatal_outcomes_do_not_retry() -> None:
    success_session = FakeSession(
        [
            FakeResponse(text='<input name="_token" value="login-token">'),
            FakeResponse(payload={"status": "success", "mfa_flag": 0}),
        ]
    )
    await EasyPassClient(success_session, "test-user", "secret").async_login()
    assert len(success_session.calls) == 2
    assert success_session.calls[1][2]["headers"]["X-XSRF-TOKEN"] == (
        "encoded token"
    )

    invalid_session = FakeSession(
        [
            FakeResponse(text='<input name="_token" value="login-token">'),
            FakeResponse(payload={"status": "unsuccess"}),
        ]
    )
    with pytest.raises(InvalidAuth):
        await EasyPassClient(invalid_session, "test-user", "wrong").async_login()
    assert len(invalid_session.calls) == 2

    mfa_session = FakeSession(
        [
            FakeResponse(text='<input name="_token" value="login-token">'),
            FakeResponse(payload={"status": "success", "mfa_flag": 1}),
        ]
    )
    with pytest.raises(TwoFactorUnsupported):
        await EasyPassClient(mfa_session, "test-user", "secret").async_login()
    assert len(mfa_session.calls) == 2


@pytest.mark.asyncio
async def test_fetches_all_paginated_cards() -> None:
    session = FakeSession(
        [
            FakeResponse(text='<meta name="csrf-token" content="card-token">'),
            FakeResponse(
                payload={
                    "easyPassCardsData": {
                        "data": [card_row("9000000001", "100.00", "ACCOUNT-A")],
                        "last_page": 2,
                    }
                }
            ),
            FakeResponse(
                payload={
                    "easyPassCardsData": {
                        "data": [card_row("9000000002", "250.50", "ACCOUNT-B")],
                        "last_page": 2,
                    }
                }
            ),
        ]
    )
    cards, token = await EasyPassClient(
        session, "test-user", "secret"
    ).async_fetch_cards_with_token()

    assert token == "card-token"
    assert [card.card_id for card in cards] == ["9000000001", "9000000002"]
    assert cards[1].balance == Decimal("250.50")
    assert session.calls[2][2]["params"]["page"] == 2


@pytest.mark.asyncio
async def test_usage_discards_profile_pii_at_api_boundary() -> None:
    session = FakeSession(
        [
            FakeResponse(
                payload={
                    "status_code": "200",
                    "data": {
                        "profile": {
                            "customer_id": "SHOULD-NOT-LEAVE-CLIENT",
                            "address1": "PRIVATE",
                            "phone": "PRIVATE",
                        },
                        "tag_usage": [
                            {
                                "txn_desc": "ผ่านทาง",
                                "txn_amt": "45",
                                "txn_date": "12/08/2026 07:00:00",
                                "txn_balance": "155",
                                "location": "Synthetic Gate",
                                "position": "03",
                                "customer_id": "ALSO-PRIVATE",
                            }
                        ],
                    },
                }
            )
        ]
    )
    summary = await EasyPassClient(
        session, "test-user", "secret"
    ).async_fetch_usage("token", "ACCOUNT-A", date(2026, 8, 12))

    assert summary.toll_total == Decimal("45.00")
    assert summary.last_trip is not None
    assert not hasattr(summary, "profile")
    assert "SHOULD-NOT-LEAVE-CLIENT" not in repr(summary)

