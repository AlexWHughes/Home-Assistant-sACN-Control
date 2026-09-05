# sACN Control

A Home Assistant custom integration (HACS) that bridges **sACN / E1.31** both ways:

- **sACN → Home Assistant** — a lighting console or media server drives existing `light.*` entities
- **Home Assistant → sACN** — Home Assistant lights transmit DMX to sACN fixtures, nodes, and LED processors

This is the in-process sister of [sACN2HomeLX](https://github.com/AlexWHughes/sACN2LIFX). That app discovers LIFX, Nanoleaf, and Home Assistant lights over the LAN/REST and maps them from a standalone UI. This integration runs *inside* Home Assistant, so inbound updates call `light.turn_on` / `turn_off` directly (no long-lived token) and outbound fixtures show up as normal HA lights.

Channel personalities match sACN2HomeLX whole-fixture modes (RGB / RGBW / HSBK, 8-bit and 16-bit). Home Assistant lights stay whole-fixture; pixel/matrix modes stay in sACN2HomeLX.

## Install with HACS

1. HACS → **⋯** → **Custom repositories**
2. Add [`https://github.com/AlexWHughes/Home-Assistant-sACN-Control`](https://github.com/AlexWHughes/Home-Assistant-sACN-Control) as category **Integration**
3. Search for **sACN Control** and install
4. Restart Home Assistant
5. **Settings → Devices & services → Add integration → sACN Control**

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=AlexWHughes&repository=Home-Assistant-sACN-Control&category=integration)

Manual install: copy `custom_components/sacn_control` into your Home Assistant `config/custom_components/` folder, restart, then add the integration from the UI.

## Configure

On first setup you choose:

| Setting | Meaning |
| --- | --- |
| **Source name** | Name advertised on transmitted sACN (max 63 characters) |
| **Priority** | E1.31 priority 0–200 (default 100). Higher wins when several sources share a universe |
| **Network interface** | NIC used for multicast join / bind. Leave as *All interfaces* unless multicast is picky |
| **Receive / Send** | Enable each direction independently |
| **Inbound update rate** | How often received DMX is applied to HA lights (default 10 Hz, same as sACN2HomeLX) |
| **Transition** | Seconds passed to `light.turn_on` / `turn_off` (default 0.05) |
| **RGBW white blend** | How much the white channel is mixed into RGB on inbound RGBW (default 0.3) |

Then open **Configure** on the integration:

1. **Map sACN → Home Assistant light** — pick a `light.*` entity, universe, start channel, and mode
2. **Add sACN fixture** — creates a new light that transmits on that address
3. **Remove a mapping** or retune network settings

Services `sacn_control.add_inbound`, `sacn_control.add_outbound`, and `sacn_control.remove_map` do the same thing from automations.

The integration ignores its own CID so a universe used in both directions does not feed back into itself.

## Channel modes

16-bit modes default to coarse then fine (MSB then LSB). Fine-first variants reverse that.

### RGB (8bit) — 3 channels

- N: Red, N+1: Green, N+2: Blue

### RGB (16bit) — 6 channels

- Each colour is MSB then LSB (0–65535)

### RGB + Intensity (8bit) — 4 channels

- RGB plus a master intensity that scales RGB

### RGBW (8bit / 16bit) — 4 or 8 channels

- White is mixed into RGB on **inbound** using the white-blend coefficient
- **Outbound** writes R, G, B, and W as separate channels

### HSBK (8bit / 16bit) — 4 or 8 channels

- Hue (0–360°), Saturation, Brightness/value, Kelvin (2500–9000 K)

### HSBK + Intensity (8bit) — 5 channels

- HSBK plus a master intensity that scales value

Example: Universe 1, start channel 1, RGB (8bit) → ch 1 red, ch 2 green, ch 3 blue.

## Entities

| Entity | Role |
| --- | --- |
| `light.<fixture>` | One per outbound mapping |
| `switch.s_acn_control_receive_sacn` | Start/stop inbound reception |
| `switch.s_acn_control_send_sacn` | Start/stop outbound transmission |
| `sensor.s_acn_control_sacn_receive_status` | `receiving` or `idle` |
| `sensor.s_acn_control_sacn_packets_received` | Packet counter |
| `sensor.s_acn_control_active_sacn_universes` | Universes seen recently |

Exact entity IDs follow your entity registry names.

Inbound mappings do **not** create extra lights; they drive lights you already have.

## How this differs from other options

- **Core `sacn` integration** — output only. This one receives and sends, and patches existing HA lights.
- **sACN2HomeLX** — standalone mapper for LIFX, Nanoleaf, and HA-over-REST, including pixel fixtures. Use it when you need LIFX LAN, Nanoleaf streaming, or per-pixel modes. Use this integration when HA should be the hub.

Do not let this integration and another sACN sender share the same universe at the same priority unless you intend HTP/priority takeover.

## Network notes

sACN multicast uses `239.255.x.x:5568`. Home Assistant OS / supervised installs need the host NIC to allow multicast (and IGMP snooping on managed switches). If multicast never arrives, point the console at Home Assistant with **unicast** sACN instead, and still pick the correct bind interface.

## Development

```bash
python3 -m pip install pytest
python3 -m pytest
```

DMX encode/decode tests run without Home Assistant. The `sacn` and `ifaddr` packages are installed by Home Assistant from `manifest.json` when the integration loads.

## License

MIT
