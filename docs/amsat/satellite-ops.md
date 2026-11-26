# Amateur satellite operating guide (Ember)

Written for Ember's offline radio library. Licence: same as the Ember repo. Formulas are standard; check
numbers against the sources in the radio library (SatNOGS DB, Hamlib, Gpredict, Wikipedia) before you rely on them.

## TLEs and pass prediction

- A TLE (two-line element set) describes one satellite's orbit at an epoch. SGP4 turns it into position and
  velocity at any time. Gpredict, Hamlib-based trackers, `predict` and Python `skyfield`/`sgp4` all use SGP4.
- Freshness: LEO TLE error grows roughly 1-3 km per day. Refresh at least weekly, daily for new launches or
  low, decaying satellites. Ember's copies: `~/.local/share/ember/radio-kb/tle/` (CelesTrak amateur group and
  AMSAT nasabare). Refresh online with `.venv/bin/python scripts/fetch_radio_kb.py --only amsat`.
- Gpredict offline: Edit > Update TLE > from local files, and point it at the `tle/` folder.
- A pass is AOS (rise above your elevation mask), TCA/max elevation, LOS (set). Plan for passes above about
  15-20 degrees; low passes are short and blocked by terrain.
- Ground station position: latitude, longitude and altitude must be right; a wrong clock is the most common
  fault. Keep the computer on NTP or GPS time (within about 1 second).

## Doppler

- Received frequency: f_rx = f0 * (1 - v_r / c), where v_r is the range rate (positive when the satellite moves away).
- Size: about +/-3.4 kHz on 145.9 MHz and about +/-10 kHz on 437 MHz for a LEO pass (v_r up to about 7 km/s).
  It changes fastest at closest approach.
- Downlink: tune the receiver to f_down * (1 - v_r/c). Uplink: transmit at f_up / (1 - v_r/c) so the satellite
  hears its nominal frequency.
- FM satellites: preset 5 kHz steps on 70 cm (e.g. +10, +5, 0, -5, -10 kHz across the pass); 2 m usually needs no change.
- Linear transponders (SSB/CW): keep the frequency *at the satellite* constant ("one true frequency rule"); let
  the tracker correct both links, or correct the higher-frequency link fully and the other by ear.
- Inverting transponders: uplink up = downlink down, so tuning directions are opposite.

## Rig control with Hamlib (rigctld)

- Hamlib's network daemon lets Gpredict (or any client) set frequencies: `rigctld -m MODEL -r PORT -s BAUD -t 4532`.
  Find the model number with `rigctl -l | grep -i 7300`. For the Icom IC-7300 set the radio's CI-V USB baud
  rate and use the same `-s` value; CI-V address is 0x94 by default.
- Test: `rigctl -m 2 -r localhost:4532 f` reads the frequency through the daemon (model 2 = NET rigctl).
- **IC-7300 limit:** it covers 160 m to 6 m (and 4 m in some regions) only. Most amateur satellites use 2 m and
  70 cm, so the IC-7300 is useful only for HF/10 m/6 m links (for example 10 m downlinks) or as an IF rig with
  transverters. For FM and linear 2 m/70 cm satellites use a VHF/UHF rig (IC-9700, IC-910, FT-847, TS-2000);
  Gpredict's notes for those rigs are in the library.
- In Gpredict: Edit > Preferences > Interfaces > Radios: host `localhost`, port 4532, type RX only, TX only,
  simplex or duplex to match the rig; then open the Radio Control window from the module menu and engage.

## Rotator control (rotctld) and Gpredict

- `rotctld -m MODEL -r PORT -t 4533`; list models with `rotctl -l` (Easycomm, Yaesu GS-232, SPID and others).
- Test: `rotctl -m 2 -r localhost:4533 p` reads az/el; `P 180 45` moves.
- In Gpredict add the rotator (host localhost, port 4533, az type 0-360 or 180-540, limits), open Antenna
  Control, pick the satellite, engage. Set a small tolerance (2-5 degrees) to avoid constant small moves.
- Flip passes: if a pass crosses north (az 360/0) and the rotator stops at 0/360, either use 180-540 az or a
  "flip" mode (el 90-180) if the rotator supports it.

## Pointing a phased array from az/el

1. Target unit vector in local ENU: e = cos(el) sin(az), n = cos(el) cos(az), u = sin(el) (az from true north,
   clockwise).
2. Rotate into the array frame (x, y in the array face, z = boresight). For a flat array facing straight up with
   x = east, y = north: ux = e, uy = n, uz = u. For a tilted array apply its rotation matrix.
3. Phase for the element at (x_m, y_n): phi_mn = -2*pi/lambda * (x_m*ux + y_n*uy) (wrap to 0-360 degrees,
   quantize to the phase shifter's step, e.g. 5.6 degrees for 6 bits).
4. Scan angle theta from boresight: cos(theta) = uz. Gain falls roughly with the projected area (about cos theta),
   and grating lobes appear unless element spacing d <= lambda / (1 + sin(theta_max)) (lambda/2 is safe for +/-90).
5. Wideband signals: use true time delay tau_mn = (x_m*ux + y_n*uy) / c instead of phase, or accept beam squint
   of about (delta_f / f) * tan(theta) radians.
