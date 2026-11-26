# Small mmWave radars as pointing cues for 2 m / 70 cm Yagis (Ember guide)

Written for Ember's radio library (CC0). This guide is for club ham use: a thumbnail-size 60/77 GHz radar sees a nearby moving object (a drone carrying a fox-hunt transmitter, a balloon, a light aircraft near the field) and turns it into azimuth/elevation for a rotator or a phased array, so a 2 m/70 cm beam follows it. The TI and D3 datasheets and user guides aren't redistributable, so this guide summarises them in Ember's own words and links to them. Check the originals before you rely on a number.

## Bottom line first: range

- These radars see **tens of metres for a small drone and a few hundred metres for an aircraft**. A 250 g drone has a radar cross-section (RCS) of about 0.01-0.05 m²; a person is about 1 m²; a car about 10 m²; a light aircraft about 1-5 m²; an airliner about 10-100 m².
- Detection range grows only with the fourth root of RCS and of transmit power × antenna gain², so 16 times the RCS only doubles the range.
- **Aircraft scatter needs aircraft 50-400 km away at 10 km altitude.** No small radar can see that; use **ADS-B** (an RTL-SDR at 1090 MHz with dump1090-fa or readsb) to cue the Yagis. It is passive, free and gives exact positions. The radar is useful only for aircraft close to the field, such as approaches to a nearby airstrip.
- **Drone fox hunts:** the fox is a transmitter, so **RF direction finding** (a KrakenSDR or a 2 m/70 cm Yagi with an attenuator) finds it at kilometres. The radar is for the last 20-80 m: it shows exactly where the drone is in the sky.

Rough ranges, from TI's published person/car figures and D3's drone test, scaled by RCS^(1/4):

| Board | Small drone (0.01-0.05 m²) | Light aircraft (~2 m²) | Large aircraft (~50 m²) |
|---|---|---|---|
| IWR6843AOPEVM | ~15-25 m | ~60 m | ~130 m |
| IWR1843BOOST | ~15-40 m | ~45-95 m (person 37-80 m) | ~200-300 m (car 199 m) |
| D3 RS-6843 24-patch | ~75-80 m (measured, 250 g drone) | ~150 m (chirp limit) | ~150 m; ~500-800 m with a long-range chirp |

The chirp sets a hard ceiling too: max range = IF bandwidth × c / (2 × chirp slope). With a 10 MHz IF (xWR18xx/68xx), a 10 MHz/µs slope gives 150 m and a 2 MHz/µs slope gives 750 m (with coarser range resolution).

## The three boards

| | TI IWR1843BOOST | D3 DesignCore RS-6843 (24-patch) | TI IWR6843AOPEVM |
|---|---|---|---|
| Band | 76-81 GHz | 60-64 GHz | 60-64 GHz |
| TX / RX | 3 / 4 (12 virtual), PCB patch antennas | 3 / 4, 24-patch arrays per channel (4×6 TX, 6×4 RX), about 19 dBi each | 3 / 4, antenna on package, about 5-6 dBi |
| FoV (az / el) | ±60° / ±15° (6 dB; 3 dB about ±28° / ±14°) | ~20° beam (3 dB), both planes | ±60° / ±60° |
| Angular resolution (az / el) | 15° / 58° (8 az virtual channels, 2 in el) | not used in D3's drone demo: the array isn't λ/2 spaced, so treat it as a narrow "staring" beam | 29° / 29° (4 × 4 virtual layout) |
| TI's range figures | person 37-80 m, car 199 m | 250 g drone 75-80 m (D3 demo, 128 chirps, 3 TX at once, ~150 m max range, ~3 m range bins) | person 49 m, car 87 m |
| Processing | R4F MCU + C674x DSP + HWA | same chip family (IWR6843) | IWR6843: R4F + C674x DSP + HWA |
| Interfaces | XDS110 micro-USB (CLI + data UART), 5 V 3 A barrel | USB-serial (with its interface board), CAN, SPI, I2C; 5 V, under 2 W | micro-USB, CP2105 dual UART; USB powered |
| Price (late 2026) | about $299 from TI, $345-425 at distributors | quote from D3 (custom antenna variant) | about $175-210 (DigiKey lead time up to 12 weeks) |
| Best use | wide-azimuth cue for drones and nearby aircraft | longest reach on small drones; mount it on the Yagi boom or rotator and point it | very wide view overhead, compact, shortest reach |

A useful pattern: one wide-FoV board (1843BOOST or AOP) spots the target and gives a coarse bearing, then the rotator turns, and a narrow-beam RS-6843 on the boom confirms and holds it.

### Links (TI and D3 documents; read them there)

- IWR1843BOOST: https://www.ti.com/tool/IWR1843BOOST, with its user guide at https://www.ti.com/lit/pdf/spruim4 (SOP switches, antenna patterns).
- IWR6843AOPEVM: https://www.ti.com/tool/IWR6843AOPEVM, with the 60 GHz EVM user guide at https://www.ti.com/lit/pdf/swru546.
- Antenna comparison and range table: https://www.ti.com/lit/pdf/swra758.
- mmWave SDK 3.x (out-of-box demo, binaries, `mmw_demo` UART format): https://www.ti.com/tool/MMWAVE-SDK.
- Radar Toolbox (3D people tracking, long-range people detection; UART TLV docs): https://dev.ti.com/tirex → Radar Toolbox → "Understanding UART Data Output Format".
- UniFlash: https://www.ti.com/tool/UNIFLASH. mmWave Demo Visualizer and Sensing Estimator: https://dev.ti.com/gallery.
- D3 RS-1843A/RS-6843 datasheet: https://www.d3embedded.com (DesignCore radar catalog), and D3's drone detection note with the 24-patch RS-6843 (Edge AI and Vision Alliance, 8 Sept 2026).

## Flashing and configuring

**1. Flash the demo firmware (once)**

| | IWR1843BOOST | IWR6843AOPEVM (standalone) | D3 RS-6843 |
|---|---|---|---|
| Flash mode | SOP2:0 = 101 on S1 (SOP5) | S1.1-4 off, S2.1 on, S2.2 on, S2.3-4 off, S3 on | per D3's guide: SOP header/switch to flash, then UniFlash like a TI EVM |
| Run mode | SOP 001 (SOP4) | S2.1 off, S2.2-4 on, S3 off | per D3 |
| Port for UniFlash | XDS110 "User UART" | CP2105 "Enhanced" port | D3 USB-serial |
| Image | `xwr18xx_mmw_demo.bin` (mmWave SDK 3.x) or a Radar Toolbox `.bin` | `xwr64xxAOP_mmw_demo.bin` (SDK 3.x) or the 3D people tracking `.bin` | D3-supplied or TI 68xx `.bin` |

Steps:
1. Set flash mode and press NRST.
2. In UniFlash pick the device (IWR1843 / IWR6843) and set the COM port.
3. Load the image as "Meta Image 1" and click **Load Images**.
4. Set run mode and press NRST again.
5. Always reset after moving SOP switches, because the mode is read only at boot.

**2. Configure each power-up with a .cfg file.** The board exposes two serial ports:
- **CLI** at 115200 baud (XDS110 User UART; CP2105 Standard port on the AOP). Send it the text commands.
- **Data** at 921600 baud (XDS110 Auxiliary Data Port; CP2105 Enhanced port). Binary frames come out here.

The TI visualizer sends the file for you, or use `mmwave_cue.py --cli PORT --cfg file.cfg`. The key lines:

```
sensorStop
flushCfg
dfeDataOutputMode 1            % 1 = frame based chirps
channelCfg 15 7 0              % RX mask 1111, TX mask 111
adcCfg 2 1
profileCfg 0 60 7 5 40 0 0 20 1 256 7200 0 0 30   % id, start GHz, idle us, ADC start us, ramp end us, ..., slope MHz/us, ..., samples, sample rate ksps, ..., RX gain
chirpCfg 0 0 0 0 0 0 0 1       % one chirp per TX (repeat with TX masks 2 and 4)
frameCfg 0 2 64 0 100 1 0      % chirp loops, frame period ms, trigger (1 = software, 2 = hardware sync)
cfarCfg ...                    % detection threshold per range/Doppler
aoaFovCfg -1 -60 60 -20 20     % limit azimuth/elevation (SDK 3.x)
guiMonitor -1 1 0 0 0 0 0      % 1 = send the point cloud (TLV 1)
sensorStart
```

The profile line above shows the fields; don't copy its numbers. Generate a real profile for your range and speed with the mmWave Sensing Estimator or Demo Visualizer, save it as a `.cfg`, and keep it with the station notes.

Useful chirp formulas:
- range resolution = c / (2 × bandwidth): 4 GHz gives 3.75 cm; 300 MHz gives 0.5 m.
- max range = IF max × c / (2 × slope).
- max speed = λ / (4 × chirp period × number of TX in TDM).

For drones and aircraft, use long frames with many chirps for SNR, a slower slope for range, and a wide enough speed span (aircraft on approach do 30-70 m/s).

## UART output format (little endian)

Each frame is:
- an 8-byte magic word `02 01 04 03 06 05 08 07`;
- then 8 × uint32: version, total packet length (bytes, including the header), platform, frame number, CPU cycles, number of detected points, number of TLVs, subframe;
- then that many TLVs, each with a uint32 type and a uint32 length (payload bytes) followed by the payload.

| TLV | From | Payload |
|---|---|---|
| 1 | SDK out-of-box demo | per point: float x, y, z (m), doppler (m/s). x = right, y = boresight, z = up |
| 2, 3 | SDK demo | range and noise profiles (uint16 per bin) |
| 6 | SDK demo | timing and CPU stats |
| 7 | SDK demo | per point: int16 SNR, int16 noise (0.1 dB) |
| 1020 | Radar Toolbox tracking | 5 float units (elevation, azimuth, doppler, range, snr), then per point int8 el, int8 az, int16 doppler, uint16 range, uint16 snr; multiply each by its unit (radians, m/s, m) |
| 1010 | Radar Toolbox tracking (group tracker) | per track 112 bytes: uint32 id, float pos xyz, vel xyz, acc xyz, ec[16] error covariance, gating gain, confidence |
| 1011 | tracking | uint8 track id per point from the previous frame (253-255 = none) |
| 1012 | tracking | track id plus min/max height |

Older Industrial Toolbox labs used other header layouts, so check the user guide for the exact demo you flash.

## Python reader

`scripts/mmwave_cue.py` in the Ember repo (CC0, about 200 lines, needs only pyserial):
- finds frames by the magic word;
- parses TLV 1, 1010 and 1020, preferring tracks;
- applies the mounting transform, lever arm, alpha-beta smoothing and latency prediction;
- sends `P az el` to rotctld (with a deadband) or prints JSON lines for an array pointer.

The core loop:

```python
import struct, serial
MAGIC = bytes([2, 1, 4, 3, 6, 5, 8, 7])
s = serial.Serial("/dev/ttyUSB1", 921600, timeout=1)
buf = b""
while True:
    buf += s.read(4096)
    i = buf.find(MAGIC)
    if i < 0 or len(buf) < i + 40:
        continue
    total = struct.unpack_from("<I", buf, i + 12)[0]
    if len(buf) < i + total:
        continue
    body, buf = buf[i + 40:i + total], buf[i + total:]
    off = 0
    while off + 8 <= len(body):
        kind, n = struct.unpack_from("<2I", body, off); off += 8
        if kind == 1:
            for k in range(n // 16):
                x, y, z, v = struct.unpack_from("<4f", body, off + 16 * k)
                print(f"x={x:.1f} y={y:.1f} z={z:.1f} v={v:.1f}")
        off += n
```

Run it:

```
python3 scripts/mmwave_cue.py --cli /dev/ttyUSB0 --cfg drone.cfg --data /dev/ttyUSB1 \
  --yaw 135 --pitch 15 --offset 0,-2,0.5 --latency 0.3 --rotctld 127.0.0.1:4533
```

## From detections to az/el (the important part)

1. **Sensor frame.** TI uses x to the right, y along the boresight and z up. For one point: azimuth_sensor = atan2(x, y), elevation_sensor = atan2(z, √(x²+y²)).
2. **Mounting.** Measure three angles:
   - **yaw**: the compass bearing of the boresight, from true north. Correct magnetic declination, or sight a known landmark or the sun.
   - **pitch**: boresight tilt up, measured with a phone inclinometer.
   - **roll**.

   Rotate sensor → ENU: roll about the boresight, then pitch about x, then yaw about up. Errors here map straight into pointing errors: 3° of yaw error is 3° of beam error.
3. **Lever arm.** If the radar isn't at the antenna, add (radar − antenna) in east/north/up metres before computing az/el. The angle error from a 2 m offset is 2/range radians: 6° at 20 m and 0.4° at 300 m. It matters a lot for drones.
4. **Az/el for the antenna.** az = atan2(E, N) mod 360, el = atan2(U, √(E²+N²)).
   - If the radar rides on the rotator, the mounting yaw changes with the rotator position: add the current rotator azimuth (read it back with rotctld `p`).
   - Or mount the radar fixed and keep the geometry simple.
5. **Smoothing.**
   - Use an alpha-beta filter (α ≈ 0.3-0.6, β ≈ 0.05-0.2), or the radar's own group tracker (TLV 1010), which is better for clutter.
   - Unwrap azimuth across 359→0.
   - Drop points with near-zero Doppler (ground clutter) and points outside the expected range.
6. **Latency.** Add up the frame period, UART time (a 2 KB frame at 921600 baud takes about 20 ms), the filter, and the rotator's travel or the array's phase update. Predict the target that far ahead.
   - Rotators slew at only 2-6°/s. A drone 30 m away crossing at 10 m/s moves 19°/s, so a rotator can't follow it closely. Use a wide-beam Yagi, or a phased array, which re-points in milliseconds.
7. **Deadband.**
   - Rotator: only command a move when the change is more than about a fifth of the Yagi's 3 dB beamwidth. That's about 10° for a 5-element 2 m Yagi and about 5° for a 13-element 70 cm one.
   - Phased array: update at the radar frame rate (10-20 Hz) and clamp to its scan limits.
8. **rotctld.**
   - Start it with `rotctld -m <model> -r /dev/ttyUSB2 -t 4533`.
   - Send `P 123.4 12.0` and expect `RPRT 0` back. Read the position with `p`.
   - Gpredict can't take radar input; run the cue script instead of Gpredict while you use it, or switch between them.

## Rules and safety

- 60 GHz (57-71 GHz) and 76-81 GHz radars have their own FCC rules (Part 15.255 and Part 95 Subpart M) outside the amateur service. EVMs are sold as evaluation kits.
- Keep the 5-20 cm separation in TI's user guides.
- Point the radar where you need it and keep it low power.
- The 2 m/70 cm transmissions follow Part 97 as usual.

## Better choices? A comparison for drone fox hunts and radar-cued Yagi pointing

| Option | Small-drone range | Aircraft range | FoV | Angular resolution | Cost (late 2026) | Availability | Tiling / sync | Software |
|---|---|---|---|---|---|---|---|---|
| **ADS-B: RTL-SDR + dump1090-fa/readsb** | – | 200-400 km (all transponder-equipped aircraft) | all-round | exact position (lat/lon/alt) | $30-60 | everywhere | many receivers merge easily | open source (GPL), mature; best for aircraft scatter |
| **KrakenSDR** (5-ch coherent RF direction finding, 24-1766 MHz) | finds the drone's **transmitter** at km range | – | 360° with a circular array | a few degrees bearing | $749 + antennas | in stock from KrakenRF | coherent within a unit; combine units by bearing triangulation | open source (GPL-3) on a Raspberry Pi; Android app free for non-commercial use |
| TI IWR1843BOOST | ~15-40 m | ~200-300 m (large) | ±60° / ±15° | 15° / 58° | ~$299 | in stock at TI | independent radars only (no shared LO); hardware frame trigger lets you interleave chirps | mmWave SDK 3.x, Radar Toolbox, many open parsers, ROS driver |
| D3 RS-6843 24-patch | **~75-80 m** (measured) | ~150 m+ (chirp-limited) | ~20° | none in demo (staring beam) | quote | made to order | same as TI | TI SDK + D3 tools |
| TI IWR6843AOPEVM | ~15-25 m | ~130 m (large) | ±60° / ±60° | 29° / 29° | ~$175-210 | lead times up to 12 weeks | same as TI | SDK 3.x, Radar Toolbox 3D tracking |
| **TI IWR6843ISK** | ~30-45 m | ~175 m (car) to ~260-310 m (large) | ±60° / ±20° | 15° / 58° | ~$243 | in stock | same as TI | same as AOP; best-documented 60 GHz long-range people lab |
| **TI AWR2944EVM** (4 TX / 4 RX, 77 GHz) | ~40-55 m | ~250 m (chirp-limited, car) | ±80° az | ~9.5° az | ~$549 | in stock at TI | same as TI | newer MCU+ SDK; more work than SDK 3.x |
| TI MMWCAS-RF-EVM + DSP-EVM (4-chip cascade) | ~50-70 m | 350 m+ (car, beamforming) | ±70° az / ±30° el | **1.4° az** / ~18° el | $1,300-6,800 per board, plus the DSP board | distributors | true coherent LO across 4 chips | heavy: mmWave Studio/MATLAB or a TDA2 real-time stack |
| Infineon DEMO BGT60TR13C | ~5-8 m | – | ~90° | coarse (1 TX / 3 RX, L-shaped) | ~$135-230 | constrained | independent | Infineon Radar SDK (Python/C) |
| Acconeer XE121 (A121 pulsed coherent) | ~5-10 m | – | ~60-80° | none (1-D range only) | low (under ~$150) | good | many on one host | Acconeer Exploration Tool (Python, BSD-3) |

**Recommendation**
1. **Aircraft scatter:** use **ADS-B**, not radar. It reaches 100× farther than any of these radars, is passive and costs about $40. Feed its aircraft positions into Ember's cued-steering geometry and on to rotctld.
2. **Drone fox hunts:** buy a **KrakenSDR** (or start with a handheld Yagi and attenuator) to find the transmitter at range. Add **one narrow-beam radar** for the last 50-80 m. Of Matt's picks, the **D3 RS-6843 24-patch** reaches farthest on small drones; mount it on the rotator or Yagi boom so it looks where the antenna looks.
3. **Wide-FoV radar cue:**
   - The **IWR1843BOOST** is the best of the three for range with a usable azimuth angle.
   - The **IWR6843ISK** (~$243) is the 60 GHz alternative with about twice the AOP's range and the same SDK, and is a better buy than the AOPEVM unless you need the ±60° elevation for overhead coverage.
   - Step up to the **AWR2944EVM** only if you want ~9.5° angular resolution and don't mind the newer SDK.
   - The cascade board is the only real "imaging" option, but it costs too much and is too heavy for a club project.
4. **Skip** the Infineon BGT60 and Acconeer parts for this job: they're great for presence detection at a few metres, but they can't see a drone at fox-hunt distances.
