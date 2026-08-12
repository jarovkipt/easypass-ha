"""Async client for the unofficial Thai Easy Pass member portal endpoints."""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from http import HTTPStatus
from typing import Any
from urllib.parse import unquote
from zoneinfo import ZoneInfo

from aiohttp import ClientError, ClientResponse, ClientSession, ClientTimeout

from .models import CardInfo, LastTrip, UsageSummary

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://member-thaieasypass.exat.co.th"
LOGIN_URL = f"{BASE_URL}/eservice/login"
CARDLIST_URL = f"{BASE_URL}/eservice/easypasscardlist"
GET_ALL_URL = f"{CARDLIST_URL}/get-all"
USAGE_URL = f"{CARDLIST_URL}/usage"

BANGKOK = ZoneInfo("Asia/Bangkok")
REQUEST_TIMEOUT = ClientTimeout(total=60)

TOLL_DESCRIPTIONS = {"ผ่านทาง", "Pass Through"}
TOPUP_DESCRIPTIONS = {"เติมเงิน", "Topup"}
CANCEL_DESCRIPTIONS = {"ยกเลิกรายการผ่านทาง", "Cancel Pass Through"}

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class EasyPassError(RuntimeError):
    """Base exception for the portal client."""


class CannotConnect(EasyPassError):
    """The portal could not be reached or returned an invalid response."""


class InvalidAuth(EasyPassError):
    """The supplied credentials were rejected."""


class TwoFactorUnsupported(EasyPassError):
    """The account requires an unsupported OTP/2FA flow."""


class SessionExpired(EasyPassError):
    """The authenticated portal session expired."""


class NoCards(EasyPassError):
    """The account contains no Easy Pass cards."""


class PortalProtocolError(CannotConnect):
    """The portal response no longer matches the expected shape."""


class _CsrfParser(HTMLParser):
    """Extract a Laravel CSRF token without a third-party HTML dependency."""

    def __init__(self) -> None:
        super().__init__()
        self.token: str | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = dict(attrs)
        if tag == "meta" and values.get("name") == "csrf-token":
            self.token = values.get("content") or self.token
        elif (
            tag == "input"
            and values.get("name") == "_token"
            and values.get("value")
        ):
            self.token = values["value"]


def extract_csrf_token(html: str) -> str | None:
    """Return the first supported CSRF token from HTML."""
    parser = _CsrfParser()
    parser.feed(html)
    return parser.token


def parse_money(value: Any, *, absolute: bool = False) -> Decimal:
    """Convert portal money strings to two-decimal Decimal values."""
    if value in (None, ""):
        return Decimal("0.00")
    try:
        result = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation as err:
        raise PortalProtocolError("Portal returned an invalid monetary value") from err
    if absolute:
        result = abs(result)
    return result.quantize(Decimal("0.01"))


def parse_transaction_datetime(value: Any) -> datetime | None:
    """Parse a portal transaction timestamp in Bangkok time."""
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            parsed = datetime.strptime(str(value).strip(), fmt)
        except (TypeError, ValueError):
            continue
        if parsed.year > 2400:
            parsed = parsed.replace(year=parsed.year - 543)
        return parsed.replace(tzinfo=BANGKOK)
    return None


def summarize_usage(rows: list[dict[str, Any]], today: date) -> UsageSummary:
    """Aggregate safe transaction fields for the current month."""
    toll = Decimal("0.00")
    topup = Decimal("0.00")
    other = Decimal("0.00")
    trips = 0
    last_trip: LastTrip | None = None
    last_at: datetime | None = None
    unknown_count = 0

    for row in rows:
        description = str(row.get("txn_desc") or "").strip()
        amount = parse_money(row.get("txn_amt"), absolute=True)

        if description in TOLL_DESCRIPTIONS:
            toll += amount
            trips += 1
            occurred_at = parse_transaction_datetime(row.get("txn_date"))
            if last_trip is None or (
                occurred_at is not None
                and (last_at is None or occurred_at > last_at)
            ):
                last_at = occurred_at
                last_trip = LastTrip(
                    location=str(row.get("location") or "-")[:255],
                    position=(str(row["position"]) if row.get("position") else None),
                    occurred_at=occurred_at,
                    amount=amount,
                    balance_after=parse_money(row.get("txn_balance")),
                )
        elif description in TOPUP_DESCRIPTIONS:
            topup += amount
        elif description in CANCEL_DESCRIPTIONS:
            toll -= amount
        else:
            other += amount
            unknown_count += 1

    if unknown_count:
        _LOGGER.debug("Portal returned %d unrecognised transaction rows", unknown_count)

    period_start = datetime(today.year, today.month, 1, tzinfo=BANGKOK)
    return UsageSummary(
        toll_total=toll.quantize(Decimal("0.01")),
        topup_total=topup.quantize(Decimal("0.01")),
        other_total=other.quantize(Decimal("0.01")),
        trip_count=trips,
        last_trip=last_trip,
        period_start=period_start,
    )


class EasyPassClient:
    """Stateful, cookie-backed async client for one Easy Pass account."""

    def __init__(
        self, session: ClientSession, username: str, password: str
    ) -> None:
        self._session = session
        self._username = username
        self._password = password

    @property
    def session(self) -> ClientSession:
        """Return the owned session for lifecycle management."""
        return self._session

    async def _text(self, response: ClientResponse) -> str:
        if response.status >= HTTPStatus.BAD_REQUEST:
            raise CannotConnect(f"Portal returned HTTP {response.status}")
        return await response.text()

    async def _json(self, response: ClientResponse) -> dict[str, Any]:
        if response.status in (
            HTTPStatus.MOVED_PERMANENTLY,
            HTTPStatus.FOUND,
            HTTPStatus.SEE_OTHER,
            HTTPStatus.TEMPORARY_REDIRECT,
            HTTPStatus.PERMANENT_REDIRECT,
            HTTPStatus.UNAUTHORIZED,
            HTTPStatus.FORBIDDEN,
            419,
        ):
            raise SessionExpired("Portal session expired")
        if response.status >= HTTPStatus.BAD_REQUEST:
            raise CannotConnect(f"Portal returned HTTP {response.status}")
        try:
            payload = await response.json(content_type=None)
        except (ValueError, TypeError) as err:
            raise PortalProtocolError("Portal returned non-JSON data") from err
        if not isinstance(payload, dict):
            raise PortalProtocolError("Portal returned an invalid JSON object")
        return payload

    async def async_login(self) -> None:
        """Authenticate once. This method deliberately has no retry loop."""
        try:
            async with self._session.get(
                f"{BASE_URL}/", timeout=REQUEST_TIMEOUT
            ) as response:
                html = await self._text(response)
            token = extract_csrf_token(html)
            if not token:
                raise PortalProtocolError("Login page did not contain a CSRF token")

            headers = {
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{BASE_URL}/",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            }
            cookies = self._session.cookie_jar.filter_cookies(BASE_URL)
            if xsrf := cookies.get("XSRF-TOKEN"):
                headers["X-XSRF-TOKEN"] = unquote(xsrf.value)

            async with self._session.post(
                LOGIN_URL,
                data={
                    "_token": token,
                    "user_name": self._username,
                    "password": self._password,
                },
                headers=headers,
                allow_redirects=False,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                payload = await self._json(response)
        except (InvalidAuth, TwoFactorUnsupported, EasyPassError):
            raise
        except (ClientError, TimeoutError) as err:
            raise CannotConnect("Unable to connect to the Easy Pass portal") from err

        if payload.get("status") != "success":
            raise InvalidAuth("The Easy Pass portal rejected the credentials")
        if payload.get("mfa_flag") not in (0, "0", None):
            raise TwoFactorUnsupported("This account requires 2FA/OTP")

    async def _async_cardlist_token(self) -> str:
        try:
            async with self._session.get(
                CARDLIST_URL,
                allow_redirects=False,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                if response.status in (HTTPStatus.MOVED_PERMANENTLY, HTTPStatus.FOUND):
                    raise SessionExpired("Portal redirected to login")
                html = await self._text(response)
        except EasyPassError:
            raise
        except (ClientError, TimeoutError) as err:
            raise CannotConnect("Unable to load Easy Pass cards") from err

        token = extract_csrf_token(html)
        if not token:
            raise SessionExpired("Card page did not contain a CSRF token")
        return token

    def _ajax_headers(self) -> dict[str, str]:
        return {
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": CARDLIST_URL,
        }

    async def _async_card_page(
        self, token: str, page: int
    ) -> tuple[list[dict[str, Any]], int]:
        try:
            async with self._session.get(
                GET_ALL_URL,
                params={"_token": token, "page": page},
                headers=self._ajax_headers(),
                allow_redirects=False,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                payload = await self._json(response)
        except EasyPassError:
            raise
        except (ClientError, TimeoutError) as err:
            raise CannotConnect("Unable to load Easy Pass card data") from err

        container = payload.get("easyPassCardsData")
        if not isinstance(container, dict):
            raise PortalProtocolError("Card response did not contain card data")
        rows = container.get("data") or []
        if isinstance(rows, dict):
            rows = list(rows.values())
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise PortalProtocolError("Card response contained an invalid card list")
        try:
            last_page = max(1, int(container.get("last_page") or 1))
        except (TypeError, ValueError) as err:
            raise PortalProtocolError("Card response had invalid pagination") from err
        if last_page > 100:
            raise PortalProtocolError("Card response pagination exceeded safety limit")
        return rows, last_page

    @staticmethod
    def _parse_card(row: dict[str, Any]) -> CardInfo:
        card_id = str(row.get("SmartcardID") or "").strip()
        if not card_id:
            raise PortalProtocolError("A card did not contain SmartcardID")
        balance_raw = next(
            (
                row.get(key)
                for key in ("AC_Balance", "AC_Balance2", "AC_BalanceShow")
                if row.get(key) is not None
            ),
            None,
        )
        if balance_raw is None:
            raise PortalProtocolError("A card did not contain a balance")

        def optional(key: str) -> str | None:
            value = row.get(key)
            return str(value).strip() if value not in (None, "") else None

        return CardInfo(
            card_id=card_id,
            account_number=optional("AccountNumber"),
            balance=parse_money(balance_raw),
            card_name=optional("CardName"),
            tag_status=optional("TagStatusText"),
            tag_action=optional("TagActionText"),
            plate_no=optional("PlateNo"),
            car_model=optional("CarModel"),
            car_color=optional("CarColor"),
            account_status=optional("CustomerAccountStatus"),
        )

    async def async_fetch_cards(self) -> list[CardInfo]:
        """Fetch every card across the portal's pagination."""
        token = await self._async_cardlist_token()
        rows, last_page = await self._async_card_page(token, 1)
        for page in range(2, last_page + 1):
            page_rows, _ = await self._async_card_page(token, page)
            rows.extend(page_rows)
        cards = [self._parse_card(row) for row in rows]
        if not cards:
            raise NoCards("The account contains no Easy Pass cards")
        return cards

    async def async_fetch_usage(
        self, token: str, account_number: str, today: date
    ) -> UsageSummary:
        """Fetch and aggregate current-month usage for one card."""
        start = today.replace(day=1)
        try:
            async with self._session.post(
                USAGE_URL,
                data={
                    "_token": token,
                    "cust_acct_id": account_number,
                    "start_date": start.isoformat(),
                    "end_date": today.isoformat(),
                    "language": "th",
                    "flag": "card_history_search",
                    "choice": "",
                },
                headers=self._ajax_headers(),
                allow_redirects=False,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                payload = await self._json(response)
        except EasyPassError:
            raise
        except (ClientError, TimeoutError) as err:
            raise CannotConnect("Unable to load Easy Pass usage") from err

        if str(payload.get("status_code")) != "200":
            raise PortalProtocolError("Portal rejected the usage request")
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            raise PortalProtocolError("Usage response did not contain data")
        raw_rows = data.get("tag_usage") or []
        if not isinstance(raw_rows, list):
            raise PortalProtocolError("Usage response contained invalid transactions")

        safe_rows: list[dict[str, Any]] = []
        allowed = {
            "location",
            "position",
            "txn_date",
            "txn_desc",
            "txn_amt",
            "txn_balance",
        }
        for raw_row in raw_rows:
            if not isinstance(raw_row, dict):
                raise PortalProtocolError("Usage response contained an invalid row")
            safe_rows.append({key: raw_row.get(key) for key in allowed})
        return summarize_usage(safe_rows, today)

    async def async_fetch_cards_with_token(self) -> tuple[list[CardInfo], str]:
        """Fetch every card while retaining the fresh token needed by usage calls."""
        token = await self._async_cardlist_token()
        rows, last_page = await self._async_card_page(token, 1)
        for page in range(2, last_page + 1):
            page_rows, _ = await self._async_card_page(token, page)
            rows.extend(page_rows)
        cards = [self._parse_card(row) for row in rows]
        if not cards:
            raise NoCards("The account contains no Easy Pass cards")
        return cards, token
