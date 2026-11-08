# sACN Control

A Home Assistant custom integration (HACS) that bridges **sACN / E1.31** both ways:

- **sACN → Home Assistant** — a lighting console or media server drives existing `light.*` entities
- **Home Assistant → sACN** — Home Assistant lights transmit DMX to sACN fixtures, nodes, and LED processors

This is the in-process sister of [sACN2HomeLX](https://github.com/AlexWHughes/sACN2LIFX). That app discovers LIFX, Nanoleaf, and Home Assistant lights over the LAN/REST and maps them from a standalone UI. This integration runs *inside* Home Assistant, so inbound updates call `light.turn_on` / `turn_off` directly (no long-lived token) and outbound fixtures show up as normal HA lights.

Channel personalities match sACN2HomeLX whole-fixture modes (RGB / RGBW / HSBK, 8-bit and 16-bit). One outbound fixture can cover a strip or bar (up to 170 RGB pixels, clamped to the remaining channels on that universe). 2D matrix layouts stay in sACN2HomeLX.

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

During setup you will be asked to:

1. **Select Home Assistant lights** that incoming sACN should drive (multi-select). New lights are patched from the start channel, in order. Leave empty to skip.
2. **Add an sACN fixture** — type a name to create a Home Assistant light that transmits on that universe/channel. Set **Pixels** above 1 to drive a whole strip from that one light. Leave the name blank to skip.

Later, open **Configure** on the integration to change those mappings: pick which lights follow sACN, add more fixtures, remove a patch, or retune network settings.

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

## Multi-pixel fixtures

An outbound fixture still appears as **one** Home Assistant light. The patch occupies `pixels × channels-per-cell` on the universe (RGB 8-bit × 30 pixels = 90 channels). Existing mappings without these fields stay 1 pixel / whole fixture.

| Pixel layout | What it does |
| --- | --- |
| **Whole fixture** | The same colour is written to every pixel. Effects that need spatial layout fall back to one cell. |
| **Full pixel** | One DMX cell per pixel. Rainbow / chase / theater can address each pixel. |
| **RGB 8 / 4 / 2 pixel groups** | Effects paint 8, 4, or 2 addressable groups, then those cells are stretched across the physical pixels. |

A solid colour (or **off**) always writes every physical pixel. Pixel count is clamped so the fixture cannot run past channel 512.

### Effects

Outbound lights support Home Assistant’s built-in **Effect** control (about 20 fps):

| Effect | Behaviour |
| --- | --- |
| **off** | Solid colour on every pixel |
| **rainbow** | Hue steps across groups or pixels |
| **chase** | A bright cell walks the fixture |
| **colorloop** | Whole-fixture hue cycle |
| **strobe** | Alternating on / black |
| **theater** | Every third cell lit, walking |

Use `light.turn_on` with `effect: rainbow` (or any name above) from an automation the same way you would on a native effect light.

## Entities

| Entity | Role |
| --- | --- |
| `light.<fixture>` | One per outbound mapping (colour, brightness, and effect) |
| `switch.s_acn_control_receive_sacn` | Start/stop inbound reception |
| `switch.s_acn_control_send_sacn` | Start/stop outbound transmission |
| `sensor.s_acn_control_sacn_receive_status` | `receiving` or `idle` |
| `sensor.s_acn_control_sacn_packets_received` | Packet counter |
| `sensor.s_acn_control_active_sacn_universes` | Universes seen recently |

Exact entity IDs follow your entity registry names.

Inbound mappings do **not** create extra lights; they drive lights you already have.

## Using sACN from another integration

Other integrations can take raw DMX from this integration's receiver instead of opening their own socket on port 5568. This suits devices that cannot receive sACN themselves but have a real-time protocol an integration can speak, for example pixel strings driven per pixel. Devices with native E1.31 support, such as ESPHome lights with the `e131` component, are better sent sACN directly.

```python
from homeassistant.core import HomeAssistant, callback


async def async_setup_entry(hass: HomeAssistant, entry) -> bool:
    registry = hass.data.get("sacn_control_listeners")
    if registry is not None:

        @callback
        def on_dmx(universe: int, dmx: tuple[int, ...]) -> None:
            ...  # all 512 slots, each time the data on the universe changes

        @callback
        def on_lost(universe: int) -> None:
            ...  # stream stopped (data loss timeout or termination) or reception stopped

        entry.async_on_unload(registry.register([1, 2], on_dmx, on_lost))
    return True
```

Add `"after_dependencies": ["sacn_control"]` to your manifest so the registry exists before your integration sets up. `custom_components.sacn_control.async_register_dmx_listener(hass, universes, on_dmx, on_lost)` does the same if you would rather import it.

- Callbacks run on the event loop. `on_dmx` gets each changed frame as it arrives, not at the inbound update rate, and a new subscriber gets the current frame of any live universe straight away, so a static scene is not missed. Frames are tuples, shared between listeners.
- The receiver joins subscribed universes as well as those used by inbound light mappings, starts when either needs it, and changes subscriptions without reopening its socket.
- Priority and sequence checks happen in the receiver: data comes from the highest-priority source, and sources at equal priority interleave. Any source terminating its stream on a universe, including a lower-priority backup, ends it for a moment: listeners get `on_lost`, then data again with the next packet from a source still sending.
- Subscriptions survive the config entry reloading when mappings change, but each reload stops reception briefly, so listeners get `on_lost` and then the next frame.
- The **Receive** switch applies: switching it off stops delivery and calls `on_lost` for every subscribed universe.
- Register from the event loop; `async_register_dmx_listener` checks this.

## How this differs from other options

- **Core `sacn` integration** — output only. This one receives and sends, and patches existing HA lights.
- **sACN2HomeLX** — standalone mapper for LIFX, Nanoleaf, and HA-over-REST, including 2D pixel/matrix fixtures. Use it when you need LIFX LAN, Nanoleaf streaming, or matrix layouts. Use this integration when HA should be the hub.

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
