# Changelog

All notable changes to Thai Easy Pass for Home Assistant are documented here.

## [0.1.0-beta.1] - 2026-08-12

Initial public beta.

### Added

- Async, config-flow based Home Assistant integration under the
  `thai_easypass` domain.
- Automatic discovery of every Easy Pass card in an account, including paged
  card lists.
- One device per full card number and five sensors per card: balance, toll this
  month, top-up this month, trips this month, and last trip.
- Fixed 30-minute coordinator refresh with one session-expiry reauthentication
  attempt.
- Multiple accounts and password-only reauthentication.
- English and Thai setup/error translations.
- Privacy-safe diagnostics and a generic integration brand icon.
- HACS metadata, hassfest validation, Ruff linting, and automated tests.

### Safety and limitations

- The integration is read-only and uses the unofficial Easy Pass member portal
  endpoints. Portal changes may break it.
- Accounts requiring 2FA/OTP are not supported in this release.
- Invalid credentials are never retried automatically because repeated failed
  logins may lock the portal account.
- The existing Docker/MQTT monitor can continue running in parallel; this
  integration does not alter MQTT topics or retained discovery messages.

[0.1.0-beta.1]: https://github.com/jarovkipt/easypass-ha/releases/tag/v0.1.0-beta.1
