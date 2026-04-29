# PositionGuard — Home Assistant Integration

Privacy-first family location for Home Assistant. PositionGuard exposes
your family group's presence as native `device_tracker` and
`binary_sensor` entities, with area-level granularity — home, school,
grandma's house — instead of exact coordinates.

Built for Home Assistant users who want reliable family presence
detection without handing their family's location data to third-party
services.

---

## What's different about this

- **Area-level, not coordinate-level.** PositionGuard reports presence
  as "in this area" or "not in this area" — never exact GPS coordinates.
  Your dashboard shows where family members are *grouped*, not where
  they stand.
- **One install per person.** Family members install the PositionGuard
  app on their phone once. They don't need a Home Assistant account, the
  HA Companion app, or any HA configuration on their device.
- **Works around iOS Private Wi-Fi Address rotation.** Position is
  reported by the phone, not detected by the router. Family members'
  iPhones report reliably regardless of MAC randomization.
- **Privacy-first by design.** No data sale, no ads, no third-party
  trackers. Sharing can be paused per-person at any time.

---

## What this integration provides

When configured, the integration exposes one device per group with the
following entities per family member:

- **`device_tracker.<member>_in_<group>`** — whole-group presence.
  States: `home` (member is in any area belonging to this group),
  `not_home` (member is outside all group areas), `unknown` (sharing
  paused).
- **`binary_sensor.<member>_at_<area>`** — per-area presence, one per
  (member, area) combination. State `on` (in this specific area), `off`
  (not in this specific area), `unavailable` (sharing paused).
  *Disabled by default* — enable only the ones you want to use.

Each entity exposes useful attributes including `area` (the specific
area within the group, if any) and `sharing_status` (`active` or
`disabled`).

---

## Compatibility

- **Home Assistant**: 2026.3 or later (required for proper icon
  rendering)
- **PositionGuard app**: latest version on iOS App Store
  ([download](https://apps.apple.com/app/id6758687496))
- **HACS**: recommended for installation, though manual install is
  supported

---

## Installation

You'll go through three places: the PositionGuard app (to set up your
account and family), the developer portal (to mint an API key), and HACS
(to install this integration).

### 1. Install the PositionGuard app and set up your family

1. Install [PositionGuard](https://apps.apple.com/app/id6758687496)
   from the App Store.
2. Sign in with your phone number (SMS verification).
3. Create a family group. Default name is "Family"; rename if you like.
4. Add areas to the group: at minimum a "Home" area centered on your
   house. Add others as needed (work, school, grandma's house, etc.).
   The integration will expose every member-area combination as a
   binary sensor.
5. Invite family members to the group. They install the app and accept
   the invite. Sharing can be paused per-person at any time.
6. Confirm your own and family members' positions update on the app's
   map. **Wait at least 30 seconds after any change** for presence
   state to propagate before checking in HA.

### 2. Get your API key from the developer portal

1. Visit [dev.positionguardai.com](https://dev.positionguardai.com).
2. Sign in with the same phone number you used for the app.
3. Click **Create API key**, give it a descriptive name (e.g.,
   "Home Assistant").
4. Copy the key — it's shown once only. Store it somewhere safe (a
   password manager works well).

### 3. Install the integration via HACS

1. In Home Assistant, open HACS.
2. Click the three-dot menu (top right) → **Custom repositories**.
3. Add this repository:
   - **Repository**: `https://github.com/positionguard/positionguard-homeassistant`
   - **Type**: `Integration`
4. Click **Add**.
5. Find PositionGuard in HACS and click **Download**.
6. Restart Home Assistant when prompted.

### 4. Configure the integration

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for "PositionGuard" and select it.
3. Paste your API key.
4. Select which group(s) you want to expose to Home Assistant. You can
   select multiple groups (Family, Work, Activity groups, etc.). Each
   becomes a separate device with its own member entities.
5. Done. Your family members will appear as `device_tracker` entities
   within ~30 seconds.

### Manual installation (without HACS)

If you don't use HACS:

1. Clone or download this repo.
2. Copy `custom_components/positionguard/` into your Home Assistant
   `/config/custom_components/` directory.
3. Restart Home Assistant.
4. Configure as in step 4 above.

### Updates

In-place version updates are supported. When a new version is released,
HACS will offer the update; accept and restart HA. Entity IDs are
preserved across updates — you won't see suffixes like `_2` appended
to your existing entities.

---

## Privacy

PositionGuard is built privacy-first. The integration shows presence at
**area level only**, never exact coordinates. The map in Home Assistant
will display the area boundary, not a precise location point.

What's shared:
- Whether each member is at any area in the group (`home` / `not_home`)
- Which specific area, if any, they're in
- Whether sharing is active or paused

What's never shared:
- Exact GPS coordinates
- Movement history outside of area transitions
- Any data about non-family-members nearby

When a family member pauses sharing in the app, the integration
respects this immediately. Their entities become `unavailable` rather
than reporting stale or fabricated data — automations correctly do not
fire on paused users.

---

## Automation examples

The examples below use a sample LA family group with parents Fred and
Sarah, and kids Peter, John, and Sally. Areas defined: Home, School,
Grandma's House, Beach House.

### Welcome someone home

The simplest case — trigger on a member arriving home:

```yaml
automation:
  - alias: "Welcome John home"
    trigger:
      - platform: state
        entity_id: device_tracker.john_in_family
        to: "home"
    action:
      - service: light.turn_on
        target:
          entity_id: light.living_room
```

This fires when John transitions from outside any group area to inside
any group area. If you want to be specific about *which* area he
arrived at, see the next example.

### Triggering on arrival at a specific area

The `device_tracker` entity exposes an `area` attribute identifying
which specific area within the group the member is in. Use a template
condition to match a particular area:

```yaml
automation:
  - alias: "Music when family arrives at Beach House"
    trigger:
      - platform: state
        entity_id: device_tracker.fred_in_family
        to: "home"
    condition:
      - condition: template
        value_template: >
          {{ state_attr('device_tracker.fred_in_family', 'area')
             == 'Beach House' }}
    action:
      - service: media_player.play_media
        target:
          entity_id: media_player.beach_house_speaker
        data:
          media_content_id: "spotify:playlist:..."
          media_content_type: "playlist"
```

This pattern lets you keep one Family group with multiple areas
(Home, School, Beach House, Grandma's House) and use templates to
distinguish *which* area triggered the automation. You don't need to
create a separate group per area.

### Triggering when a child arrives at school

A reliable "kid arrived at school safely" notification is one of the
killer use cases for family presence. Two approaches — pick whichever
fits your style.

**Using the area attribute (no entity setup needed):**

```yaml
automation:
  - alias: "Notify when Sally arrives at School"
    trigger:
      - platform: state
        entity_id: device_tracker.sally_in_family
        to: "home"
    condition:
      - condition: template
        value_template: >
          {{ state_attr('device_tracker.sally_in_family', 'area')
             == 'School' }}
    action:
      - service: notify.parents
        data:
          message: "Sally arrived at school"
```

**Using the per-area binary sensor (cleaner, requires enabling the
sensor first):**

```yaml
automation:
  - alias: "Notify when Sally arrives at School"
    trigger:
      - platform: state
        entity_id: binary_sensor.sally_at_school
        to: "on"
    action:
      - service: notify.parents
        data:
          message: "Sally arrived at school"
```

The binary sensor approach is more readable in YAML but requires
enabling the sensor first (see next section).

### Per-area binary sensors (advanced)

For each (member, area) combination, a `binary_sensor` exists but is
**disabled by default** to avoid cluttering Home Assistant with dozens
of entities most users won't reference.

To enable a binary sensor:

1. **Settings → Devices & Services → PositionGuard**
2. Click your group device
3. Click the binary sensor entity (e.g.,
   `binary_sensor.sally_at_school`)
4. Toggle "Enabled" on
5. Restart HA or reload the integration

Once enabled, automations using these sensors are simpler than the
template-based approach — no `state_attr` calls, just direct state
checks.

### Multiple-area scenarios

The integration shines when you have multiple meaningful areas in a
single group. Define all your common destinations as areas in the
PositionGuard app, then write automations using the `area` attribute:

```yaml
automation:
  - alias: "Announce who arrived where"
    trigger:
      - platform: state
        entity_id:
          - device_tracker.fred_in_family
          - device_tracker.sarah_in_family
          - device_tracker.john_in_family
          - device_tracker.peter_in_family
          - device_tracker.sally_in_family
        to: "home"
    action:
      - service: notify.family
        data:
          message: >
            {{ trigger.to_state.attributes.friendly_name }}
            arrived at
            {{ trigger.to_state.attributes.area }}
```

This single automation announces every family-member arrival at every
defined area, dynamically including the area name in the notification.

### Respecting sharing status

When a family member pauses sharing in the PositionGuard app, their
entities become `unavailable` rather than `not_home`. Automations that
trigger on `home → not_home` transitions will correctly **not fire**
when someone simply pauses sharing — only on actual departures.

If you want to track sharing status explicitly, each entity exposes a
`sharing_status` attribute (`active` or `disabled`):

```yaml
automation:
  - alias: "Note when sharing is paused"
    trigger:
      - platform: state
        entity_id: device_tracker.peter_in_family
    condition:
      - condition: template
        value_template: >
          {{ state_attr('device_tracker.peter_in_family',
                        'sharing_status') == 'disabled' }}
    action:
      - service: notify.parents
        data:
          message: "Peter has paused location sharing"
```

---

## Companion widgets

[**AlertTicker Card**](https://github.com/djdevil/AlertTicker-Card) by
djdevil pairs nicely with PositionGuard for moment-based presence
notifications on a dashboard. Use `auto_dismiss_after` for transient
arrival/departure alerts that don't clutter the dashboard:

```yaml
type: custom:alertticker-card
alerts:
  - entity: binary_sensor.sally_at_school
    state: "on"
    message: "🎒 Sally arrived at School"
    theme: success
    auto_dismiss_after: 60
  - entity: device_tracker.fred_in_family
    on_change: true
    message: "👤 {{ state_attr('device_tracker.fred_in_family',
                                'friendly_name') }}: {{ state }}"
    auto_dismiss_after: 60
```

The first variant fires only on arrivals at a specific area. The second
fires on any state transition (arrival or departure) and includes the
state in the message.

---

## Limitations

This integration is **read-only**. From Home Assistant, you cannot:

- Create, modify, or delete groups, areas, or members
- Change sharing permissions
- Send messages, invitations, or notifications

These actions remain in the PositionGuard app where group members can
manage their own privacy directly.

The integration polls the PositionGuard API at a regular interval
(typically every 30 seconds). State changes in the app may take up to
that interval to reflect in Home Assistant.

---

## Issues and contributing

Bug reports and feature requests welcome via
[GitHub Issues](https://github.com/positionguard/positionguard-homeassistant/issues).

For questions about PositionGuard the app or developer portal, see
[positionguardai.com](https://positionguardai.com).
