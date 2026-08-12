# Thai Easy Pass for Home Assistant

Unofficial, read-only Home Assistant integration for cards shown in the Thai
Easy Pass member portal. It creates one Home Assistant device per card and
updates balances and current-month usage every 30 minutes.

> [!IMPORTANT]
> This project is not affiliated with or endorsed by EXAT. It uses endpoints
> used internally by the member portal, not a documented public API. Portal
> changes can break the integration without notice.

## Entities

Each card gets these sensors:

- Balance (THB)
- Toll this month (THB)
- Top-up this month (THB)
- Trips this month
- Last trip, with time, lane, amount, and balance-after attributes

All cards in the account are discovered automatically, including accounts with
more than ten cards.

## Install during beta

1. In HACS, open the three-dot menu and choose **Custom repositories**.
2. Add `https://github.com/jarovkipt/easypass-ha` as an **Integration**.
3. Download **Thai Easy Pass** and restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration** and search for
   **Thai Easy Pass**.
5. Enter the username and password used by the Easy Pass member portal.

Home Assistant stores the credentials in its local config entry storage. This
integration sends them only to `member-thaieasypass.exat.co.th` and does not
send telemetry to the project maintainer.

## Limitations and safety

- Accounts requiring 2FA/OTP are not supported. The integration does not
  recommend disabling 2FA.
- The member portal warns that repeated invalid logins may lock an account.
  Invalid credentials and 2FA stop polling immediately and require an explicit
  reauthentication; they are never retried automatically.
- Only read endpoints for card lists and usage are called. The integration does
  not freeze cards, top up, rename cards, or change account data.
- Diagnostics exclude credentials, card/account numbers, registration plates,
  and raw portal responses.

## Running beside the Docker/MQTT monitor

The native integration does not publish, subscribe to, or delete MQTT topics.
It can run beside the existing Docker monitor during beta. Home Assistant may
append `_2` to native entity IDs when a name is already owned by an MQTT entity.
Do not remove retained MQTT discovery topics until you intentionally cut over.

## Development

Runtime code lives entirely in `custom_components/thai_easypass`. Tests use
synthetic responses only; real portal dumps and credentials must never be
committed.

```bash
python -m pip install -e '.[test]'
python -m pytest
ruff check .
```

## License

[MIT](LICENSE)
