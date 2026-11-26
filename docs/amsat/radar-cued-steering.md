# Radar-cued beam steering for ham radio links (Ember design notes)

Written for Ember's radio library (CC0). This is a design for amateur radio **communications**: an attached sensor (a small microwave radar, ADS-B or orbit prediction) tells a phased array or rotator where the other end of the link is, so the beam stays on a LEO satellite or on an aircraft that is reflecting signals between two stations. Check 47 CFR Part 97 (and Part 15 for licence-free radar modules) and RF exposure limits (97.13) before transmitting.

## 1. What each cue source is good for

| Cue source | Works for | Range | Notes |
|---|---|---|---|
| **TLE + SGP4 (Gpredict, Skyfield, predict)** | LEO satellites | whole pass | The primary cue for satellites. Accurate to well under 0.1 degrees with fresh TLEs, which is far better than any amateur radar could manage at 500-2000 km. |
| **Signal-driven (monopulse, sequential lobing, beacon peaking)** | Satellites with a beacon or downlink; aircraft scatter signal | link range | Closes the loop on the real signal. Use it to trim the TLE pointing. |
| **ADS-B (dump1090/readsb + RTL-SDR at 1090 MHz)** | Aircraft | 200-400 km | Passive (receive only), gives position, altitude, speed and ID once a second. The best cue for aircraft scatter. |
| **Small microwave radar (24 GHz FMCW modules, 10 GHz Doppler modules, SDR radar)** | Nearby aircraft, drones, balloons, local test targets | hundreds of m to a few km for small modules | Useful as a local cue, for testing the steering loop and for targets without ADS-B. It can't see LEO satellites. |

So the practical "radar-cued" mode is a **fusion** of tracks: TLE for satellites, ADS-B for aircraft, the radar for close-in targets and loop testing, and the received signal to fine-trim. They all reduce to the same thing: a target track in az/el with a time stamp.

## 2. Pipeline

1. **Sensor input** produces a measurement: radar (range, azimuth, elevation, radial velocity); ADS-B (lat, lon, altitude); TLE (az, el, range, range-rate at time t).
2. **Convert to one local frame**: east-north-up (ENU) centred on the array's phase centre.
   - ADS-B and TLE positions go geodetic to ECEF to ENU.
   - Radar measurements: if the radar isn't at the array, add the lever-arm offset (radar position minus array position in ENU) and correct for the radar's mounting rotation.
3. **Track filter**: an alpha-beta filter for one target, or a Kalman filter with a constant-velocity (aircraft) or orbit-model (satellite) motion model. It smooths noise and gives velocity.
4. **Latency compensation**: predict the track forward by the whole pipeline delay (sensor + filter + network + phase-shifter update, often 50-300 ms), so the beam points where the target *will* be when the new weights take effect.
5. **Pointing**: az/el to array steering (element phases or true-time delays, see the phased-array guide) or to a rotator command (rotctld `P az el`). Clamp to the array's scan limits (typically +/-45 to 60 degrees from broadside) and hand over to another panel or array face beyond that.
6. **Doppler**: from the same track take the range-rate (satellite) or bistatic range-rate (aircraft scatter) to correct the radio frequency through rigctld.
7. **Signal trim (optional)**: dither the beam slightly (or use monopulse sum/difference) on the received signal and add a small correction to the cue.
8. **Log** everything with time stamps (UTC): cue, filtered track, commanded beam, received SNR. This is how you find latency and alignment errors.

### Update rates

- A beam must move less than about a tenth of its beamwidth per update. A 10-degree beam on a LEO satellite at its fastest (about 1 degree per second overhead for a low pass, more for an aircraft overhead) needs updates every 0.5-1 s at most; an aircraft passing close at 250 m/s and 5 km needs about 3 degrees per second, so 10 Hz updates are comfortable.
- Phase shifters and digital beamformers can update in microseconds to milliseconds, so the limit is usually the cue rate (ADS-B ~1-2 Hz per aircraft, radar 10-50 Hz, TLE any rate).

## 3. Aircraft scatter (AS) on 2 m, 70 cm and 23 cm

- **What it is:** two stations up to about 800-900 km apart both see the same airliner at cruise altitude (10-12 km). The aircraft reflects (forward-scatters) signals for typically 5-60 seconds. Larger aircraft and a crossing point near the path midpoint give the strongest reflections.
- **Geometry:**
  - Both stations point at the aircraft, not at each other.
  - The best aircraft are near the great-circle midpoint, visible to both stations (each station's radio horizon to 11 km altitude is roughly 4.12 x (sqrt(h_antenna_m) + sqrt(11000)) km, about 430 km plus your own horizon term).
  - Elevation angles are low, usually 0-5 degrees, so fixed-elevation Yagis work. An array that steers in azimuth to follow the aircraft keeps the link up longer.
- **Doppler:** the reflected signal is shifted by the bistatic Doppler, -(f/c) x d(R1+R2)/dt, where R1 and R2 are the distances from each station to the aircraft. On 2 m this is a few hundred Hz; on 23 cm and up, several kHz. Tracking it (like satellite Doppler) narrows the receive filter and helps digital modes.
- **Scheduling with ADS-B:**
  - Decode ADS-B locally (dump1090-fa or readsb with an RTL-SDR at 1090 MHz) or use a shared feed.
  - Predict which aircraft will cross the common visible area in the next minutes.
  - Rank them by size (wake category), distance from the path midpoint and how long both stations can see them.
  - Exchange the plan with the other station (beam heading and start time).
  - Software such as AirScout (DL2ALF) automates this for amateurs. Ember can do the geometry from a simple list of aircraft positions and both locators.
- **Steering from the cue:**
  - Aircraft position (ADS-B, or radar for close-in) goes into the track filter, then az/el from each station.
  - Steer the array or rotator and update Doppler each second. Hand over to the next aircraft (make before break, see the phased-array guide) when the current one leaves the common area.
- **Modes:** MSK144 (WSJT-X) on 2 m is built for short pings and works well; FT8/Q65 work on longer reflections. CW and SSB are fine on strong ones.

## 4. VHF/UHF contests and aircraft scatter (rules overview)

This is a short overview; always read the current official rules for the contest you enter.

- **ARRL VHF contests (January, June, September)** and the **ARRL 222 MHz and Up Distance Contest** and **10 GHz and Up** events:
  - Exchange is the 4-character Maidenhead grid square.
  - Score is QSO points multiplied by grid squares per band.
  - Any propagation mode counts, including aircraft scatter, tropo, meteor scatter and Es. EME is allowed in some contests.
  - Categories include single-op (low power, high power, portable), Limited and Unlimited multi-op and Rover. Some categories limit "assistance" such as spotting networks. Check whether your category allows real-time aids before using shared spotting or shared ADS-B data.
- **CQ World Wide VHF Contest (July)** and **IARU Region 1 VHF/UHF contests (September/October)**:
  - Similar grid-based exchanges; Region 1 events also exchange a serial number and score by distance.
  - Aircraft scatter is a major mode in Europe for these.
- **Common points:**
  - Each contact needs a complete exchange copied by both stations.
  - Self-spotting and arranging contacts on spotting chats is restricted or banned in some rules.
  - Contacts through repeaters (and in many rules, FM simplex calling frequencies) don't count.
  - Satellites are usually not allowed in the main VHF contests.
- **Part 97:** stay inside the band plan for weak-signal work (144.0-144.3, 432.0-432.3 MHz for CW/SSB/digital), identify every 10 minutes and at the end of contact, and use only the power needed.

## 5. Using a radar as a sensor responsibly

- Licence-free radar modules (for example 24 GHz FMCW or 10 GHz Doppler units sold for motion sensing) operate under Part 15 limits. Amateur-band radar experiments must follow Part 97 rules for the band and emission type, including station identification and RF exposure limits.
- Keep transmit power low and beams away from people, airports' approach paths and other stations' equipment. Never aim at aircraft with transmitters in ways that could interfere with aviation systems; ADS-B is passive and is the preferred aircraft cue.
- Radar output is a cue for pointing a comms antenna; Ember helps with that geometry, filtering and steering software.

## 6. Minimal software layout

- `cue_adsb.py`: read dump1090's SBS-1 output (TCP 30003) or `aircraft.json`, convert to ENU, and emit tracks.
- `cue_tle.py`: Skyfield/sgp4 with the radio library's TLE files, emitting az/el/range-rate at 10 Hz.
- `cue_radar.py`: read the radar module's serial/UDP stream (range, angle, velocity), apply the lever-arm offset and emit tracks.
- `tracker.py`: an alpha-beta or Kalman filter per target, latency prediction, and target selection/handover.
- `steer.py`: az/el to element phases (phased-array guide) or rotctld commands; Doppler to rigctld `F`/`I` commands.
- Test the loop first with the radar on a slow local target (a person walking with a corner reflector, a drone in a legal area) and with recorded ADS-B logs, then go live on satellites and aircraft.
