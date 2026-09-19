# Changelog

HACS installs from GitHub releases; the version lives in
`custom_components/positionguard/manifest.json`.

## 0.3.3 — unreleased

- `position_fresh` is exposed as an attribute on the "outside usual area"
  binary sensor and on the device tracker, beside `position_age_seconds`,
  when the server sends it. It is `false` while PositionGuard holds a quiet
  phone at the saved place it was last confirmed in (`safety_status` stays
  `at_area`). Servers that don't send it leave the attribute out, never
  `False`.
- Availability is unchanged: the sensor is unavailable for `stale` only,
  never because `position_fresh` is `false`, so a held `at_area` stays
  available and off. A test pins this.

## 0.3.2

- Stale safety status renders as unavailable, not off.
