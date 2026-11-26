# Phased arrays: radar tracking and satellite link handoff (Ember)

Written for Ember's offline radio library, for amateur and research use. Licence: same as the Ember repo.
Background pages (Wikipedia, PySDR, Hamlib, KrakenSDR DoA software) are in the library too. In the USA, check
Part 97 (in the radio library) for which bands and power an amateur radar or beacon may use.

## Radar basics

- Pulse radar: range R = c * t / 2 (t = round-trip time). Range resolution about c * tau / 2 for pulse length
  tau (or c / 2B with pulse compression over bandwidth B). Maximum unambiguous range = c / (2 * PRF).
- FMCW radar: a chirp of bandwidth B over time T_c. Beat frequency f_b = 2 * R * B / (c * T_c), so
  R = c * f_b * T_c / (2 * B). Range resolution = c / (2B) (150 MHz of sweep gives 1 m). Velocity from the Doppler
  shift f_d = 2 * v / lambda, measured across several chirps (range-Doppler FFT).
- Radar equation (monostatic): received power scales with Pt * G^2 * lambda^2 * sigma / R^4, so doubling the range
  needs 16 times the power-gain product.

## Finding and tracking a target with an array

- Beam-steered search: step the beam across the sector; dwell long enough for detection (several chirps/pulses).
- Monopulse: form a sum beam (all elements in phase) and difference beams (one half of the array 180 degrees
  out of phase, left/right and up/down). The ratio Delta/Sigma is about proportional to the angle error inside
  the beam, so one dwell gives an angle measurement. On a digital array (e.g. 4- or 8-channel SDR) form the
  beams in software from the same samples.
- Sequential lobing / conical scan: compare power in slightly offset beams; simpler but needs several dwells.
- Direction finding on SDR arrays (KrakenSDR, Pluto + phaser boards): MUSIC or Bartlett beamforming over the
  channel samples after phase calibration; calibrate with a common noise source or a known emitter.

## Track filters

- Alpha-beta filter (constant velocity), update period T:
  predict x_p = x + v*T; residual r = z - x_p; update x = x_p + alpha*r, v = v + (beta/T)*r.
  Typical alpha 0.5-0.9, beta 0.1-0.5; bigger values follow manoeuvres faster but pass more noise.
- Kalman filter: state [position, velocity] (per axis or for az/el), F = [[1, T], [0, 1]], measurement H = [1, 0],
  process noise Q from expected acceleration, measurement noise R from the sensor's angle/range error. Predict:
  x = F x, P = F P F' + Q. Update: K = P H' (H P H' + R)^-1, x = x + K (z - H x), P = (I - K H) P.
- Gate: ignore detections whose residual is more than about 3-4 sigma from the prediction; coast on the
  prediction for a few missed updates before declaring the track lost.

## Steering math for satellite links

- Element phase: phi_mn = -2*pi/lambda * (x_m*ux + y_n*uy), with (ux, uy) the target direction cosines in the
  array frame (see satellite-ops.md). True time delay: tau_mn = (x_m*ux + y_n*uy) / c (no squint).
- Beamwidth of an N x N half-wavelength array is roughly 102 / N degrees at boresight (wider when scanned).
- Angular rate of a LEO satellite is highest at zenith: about v / h (7.5 km/s at 500 km is about 0.86 deg/s).
- Update rate: keep pointing error under about 1/10 of the beamwidth, so update interval
  T <= 0.1 * beamwidth / angular_rate. Example: a 10 degree beam needs an update about every 1.2 s; a 2 degree
  beam about every 0.23 s. Phase shifters settle in microseconds, so the limit is computing and writing weights.
- Precompute weights along the predicted track (from SGP4) and load the next set on a timer; correct with
  monopulse or signal-strength feedback if available.

## Pass scheduling and handoff between satellites

- Predict all passes for the next hours with fresh TLEs; build a timeline of (satellite, AOS, LOS, max elevation).
- Choose the next satellite before the current one drops below the elevation mask: prefer the one with the
  longest remaining time above the mask and higher elevation (better link margin, less blockage).
- Make-before-break: acquire the next satellite on a second beam (a second beamformer channel, a subarray or a
  second array) while the first link is still up; switch traffic only after the new link is locked and its
  SNR is stable; then release the old beam. Required overlap >= acquisition time + lock time + margin
  (often 10-30 s for amateur equipment).
- Break-before-make (single beam): schedule the switch at a planned time, preset the new beam weights and
  frequencies, and accept a short gap; buffer data across it.
- Doppler hand-over: preset the new link's receive and transmit frequencies from its predicted range rate at the
  switch time (f_rx = f0 * (1 - v_r/c), f_tx = f_up / (1 - v_r/c)), then let the tracker take over. The two links
  usually have very different Doppler at the moment of hand-over (one rising, one setting).
- Keep both satellites' TLEs current; a 2-3 km along-track error is about 1 second of timing error at LEO, which
  matters for narrow beams.
