# positionguard-homeassistant
Home Assistant custom component for PositionGuard — privacy-first location sharing for your smart home

## Automation Examples

### Triggering on a specific family member arriving home

The simplest case — use the device_tracker directly:

\`\`\`yaml
automation:
  - alias: "Welcome Chris home"
    trigger:
      - platform: state
        entity_id: device_tracker.christer_in_family
        to: "home"
    action:
      - service: light.turn_on
        target:
          entity_id: light.living_room
\`\`\`

### Triggering on arrival at a specific area

The device_tracker's `area` attribute carries the specific area name within the current group. Use a template condition to match a particular area:

\`\`\`yaml
automation:
  - alias: "Dock music playing when I get to the lake"
    trigger:
      - platform: state
        entity_id: device_tracker.christer_in_family
        to: "home"
    condition:
      - condition: template
        value_template: "{{ state_attr('device_tracker.christer_in_family', 'area') == 'Lake House' }}"
    action:
      - service: media_player.play_media
        target:
          entity_id: media_player.dock_speaker
        data:
          media_content_id: "spotify:playlist:..."
          media_content_type: "playlist"
\`\`\`

### Triggering on arrival at an activity location

For non-home-like groups (e.g., Pickleball, Gym), the device_tracker still uses `home`/`not_home`, but "home" here means "at an area of this group." Use the area attribute to be specific:

\`\`\`yaml
automation:
  - alias: "Log pickleball arrival"
    trigger:
      - platform: state
        entity_id: device_tracker.christer_in_pickleball_at_the_grove
        to: "home"
    action:
      - service: notify.log
        data:
          message: "Arrived at {{ state_attr('device_tracker.christer_in_pickleball_at_the_grove', 'area') }}"
\`\`\`

### Per-area binary sensors (advanced)

For each (member, area) combination, a disabled-by-default `binary_sensor` exists. Enable only the ones you care about via Settings → Devices & Services → PositionGuard → Entities → click the entity → toggle "Enabled."

Once enabled, automations become simpler:

\`\`\`yaml
automation:
  - alias: "Dock music at the lake"
    trigger:
      - platform: state
        entity_id: binary_sensor.christer_at_lake_house
        to: "on"
    action:
      - service: media_player.play_media
        # ...
\`\`\`

### Respecting sharing status

When a family member has sharing disabled in the PositionGuard app, their entities become `unavailable` rather than `not_home`. Automations that trigger on `home → not_home` transitions will correctly not fire when someone simply pauses sharing.

If you want to track sharing status explicitly, each entity exposes a `sharing_status` attribute (`active` or `disabled`).