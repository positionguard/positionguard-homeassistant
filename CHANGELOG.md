# Changelog

HACS installs from GitHub releases; the version lives in
`custom_components/positionguard/manifest.json`.

## 0.3.4 — unreleased

- The "outside usual area" binary sensor no longer sets the SAFETY device
  class, so Home Assistant stops rendering it as **Unsafe** / **Safe**. The
  product states a fact — the member is outside their usual area — not a
  judgement about their safety. The states now read **Outside** and
  **Inside**, with plain map-marker icons.
- **Display only.** The state is still `on` / `off`, and entity ids, unique
  ids, attributes and availability are unchanged, so existing automations,
  templates and history keep working untouched.
- **One thing does change:** anyone filtering or grouping entities by
  `device_class: safety` will no longer match this sensor. Match it by
  entity id or by its `outside_usual_area` suffix instead.

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
- Docs: the README said a stale "outside usual area" sensor reads `off`;
  since 0.3.2 it is `unavailable`. Corrected.

## 0.3.2

- Stale safety status renders as unavailable, not off.
