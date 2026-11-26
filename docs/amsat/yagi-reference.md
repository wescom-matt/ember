# 2 m and 70 cm Yagi reference (Ember)

Written for Ember's radio library. All dimensions below were designed and modeled by Ember with NEC-2 (PyNEC) on 2026-11-25. They are free to use and share (CC0). They are starting points: model your exact build in xnec2c or 4nec2 and check SWR on the real antenna before relying on it.

## How these were modeled

- Free space, lossless, round rods, boom ignored (elements insulated from the boom or mounted above it). Real antennas are 0.2-0.5 dB below these figures.
- Spacing follows the long-Yagi pattern made popular by DL6WU: reflector to driven element about 0.2 wavelength, a close first director, then spacings growing toward about 0.4 wavelength. Director lengths taper slowly along the boom.
- Gain is in dBi (subtract 2.15 for dBd). F/B is front to back at 180 degrees. Z is the feed impedance of a plain split dipole at that point; see Feeding below.
- Positions are from the reflector. Lengths are tip to tip.

## Boom correction (important)

If the elements pass through a metal boom and touch it, each parasitic element must be made longer, because the boom shortens it electrically. The correction grows with boom size: as a rough guide add about 0.7 x boom diameter for a round metal boom with the elements passing through and bonded (for example about 14 mm for a 20 mm boom), and about half that when the elements are insulated but pass through it. Elements mounted on insulators at least one boom diameter above the boom need almost no correction. Model the boom in NEC or measure and trim if in doubt. Non-metal booms (wood, fibreglass) need no correction but should be kept dry.

## 2 m weak-signal (144.0-144.5 MHz, SSB/CW, contests, aircraft scatter)

| Elements | Boom | Gain | F/B | Z at feed | 3 dB beam E/H | Stack E/H (DL6WU) | Rod |
|---|---|---|---|---|---|---|---|
| 3 | 0.60 m | 7.7 dBi | 20.4 dB | 15-0j ohm | 64° / 106° | 1.96 / 1.30 m | 6.0 mm |
| 5 | 1.47 m | 10.6 dBi | 20.8 dB | 29+0j ohm | 52° / 65° | 2.37 / 1.94 m | 6.0 mm |
| 7 | 2.66 m | 12.3 dBi | 19.0 dB | 49-0j ohm | 45° / 52° | 2.72 / 2.37 m | 6.0 mm |
| 9 | 3.77 m | 13.2 dBi | 19.2 dB | 56+0j ohm | 42° / 47° | 2.90 / 2.61 m | 6.0 mm |
| 11 | 5.56 m | 14.8 dBi | 19.2 dB | 67-0j ohm | 34° / 37° | 3.56 / 3.28 m | 6.0 mm |

**3 elements, 144.2 MHz** (rod 6.0 mm). Edge of band: 143.9 MHz 7.6 dBi, F/B 21.0 dB, Z 16-3j; 144.5 MHz 7.7 dBi, F/B 19.6 dB, Z 14+3j.

| Element | Position from R (mm) | Length (mm) |
|---|---|---|
| R | 0 | 1029 |
| DE | 416 | 1012 |
| D1 | 597 | 961 |

**5 elements, 144.2 MHz** (rod 6.0 mm). Edge of band: 143.9 MHz 10.5 dBi, F/B 21.9 dB, Z 29-4j; 144.5 MHz 10.6 dBi, F/B 19.6 dB, Z 29+4j.

| Element | Position from R (mm) | Length (mm) |
|---|---|---|
| R | 0 | 1029 |
| DE | 416 | 990 |
| D1 | 584 | 940 |
| D2 | 988 | 934 |
| D3 | 1471 | 928 |

**7 elements, 144.2 MHz** (rod 6.0 mm). Edge of band: 143.9 MHz 12.3 dBi, F/B 20.3 dB, Z 46-2j; 144.5 MHz 12.4 dBi, F/B 17.9 dB, Z 53+2j.

| Element | Position from R (mm) | Length (mm) |
|---|---|---|
| R | 0 | 1004 |
| DE | 416 | 974 |
| D1 | 584 | 927 |
| D2 | 988 | 918 |
| D3 | 1471 | 909 |
| D4 | 2032 | 900 |
| D5 | 2661 | 892 |

**9 elements, 144.2 MHz** (rod 6.0 mm). Edge of band: 143.9 MHz 13.2 dBi, F/B 19.9 dB, Z 54-0j; 144.5 MHz 13.3 dBi, F/B 18.6 dB, Z 58-0j.

| Element | Position from R (mm) | Length (mm) |
|---|---|---|
| R | 0 | 1004 |
| DE | 416 | 988 |
| D1 | 572 | 927 |
| D2 | 946 | 915 |
| D3 | 1393 | 903 |
| D4 | 1913 | 891 |
| D5 | 2495 | 880 |
| D6 | 3119 | 870 |
| D7 | 3773 | 859 |

**11 elements, 144.2 MHz** (rod 6.0 mm). Edge of band: 143.9 MHz 14.8 dBi, F/B 21.0 dB, Z 63+5j; 144.5 MHz 14.8 dBi, F/B 17.7 dB, Z 69-7j.

| Element | Position from R (mm) | Length (mm) |
|---|---|---|
| R | 0 | 1004 |
| DE | 416 | 996 |
| D1 | 584 | 940 |
| D2 | 988 | 930 |
| D3 | 1471 | 922 |
| D4 | 2032 | 913 |
| D5 | 2661 | 905 |
| D6 | 3335 | 896 |
| D7 | 4042 | 889 |
| D8 | 4783 | 881 |
| D9 | 5558 | 874 |

## 2 m satellite (145.8-146.0 MHz)

| Elements | Boom | Gain | F/B | Z at feed | 3 dB beam E/H | Stack E/H (DL6WU) | Rod |
|---|---|---|---|---|---|---|---|
| 4 | 0.85 m | 8.7 dBi | 17.9 dB | 35-0j ohm | 61° / 92° | 2.02 / 1.43 m | 6.0 mm |

**4 elements, 145.9 MHz** (rod 6.0 mm). Edge of band: 145.7 MHz 8.6 dBi, F/B 17.9 dB, Z 35-1j; 146.1 MHz 8.7 dBi, F/B 17.9 dB, Z 36+1j.

| Element | Position from R (mm) | Length (mm) |
|---|---|---|
| R | 0 | 992 |
| DE | 411 | 969 |
| D1 | 540 | 900 |
| D2 | 851 | 891 |

## 70 cm weak-signal (432.0-432.5 MHz)

| Elements | Boom | Gain | F/B | Z at feed | 3 dB beam E/H | Stack E/H (DL6WU) | Rod |
|---|---|---|---|---|---|---|---|
| 7 | 0.83 m | 12.2 dBi | 22.3 dB | 41-0j ohm | 44° / 51° | 0.93 / 0.81 m | 4.0 mm |
| 10 | 1.49 m | 14.0 dBi | 23.5 dB | 57+0j ohm | 37° / 40° | 1.09 / 1.01 m | 4.0 mm |
| 13 | 2.40 m | 15.6 dBi | 21.2 dB | 40-0j ohm | 32° / 34° | 1.26 / 1.19 m | 4.0 mm |
| 17 | 3.34 m | 16.8 dBi | 18.4 dB | 49+0j ohm | 28° / 29° | 1.43 / 1.39 m | 4.0 mm |

**7 elements, 432.1 MHz** (rod 4.0 mm). Edge of band: 431.1 MHz 12.2 dBi, F/B 25.0 dB, Z 38-3j; 433.1 MHz 12.3 dBi, F/B 20.2 dB, Z 44+3j.

| Element | Position from R (mm) | Length (mm) |
|---|---|---|
| R | 0 | 335 |
| DE | 139 | 321 |
| D1 | 191 | 305 |
| D2 | 316 | 302 |
| D3 | 465 | 299 |
| D4 | 638 | 296 |
| D5 | 833 | 294 |

**10 elements, 432.1 MHz** (rod 4.0 mm). Edge of band: 431.1 MHz 14.0 dBi, F/B 26.5 dB, Z 53+2j; 433.1 MHz 14.0 dBi, F/B 21.4 dB, Z 60-4j.

| Element | Position from R (mm) | Length (mm) |
|---|---|---|
| R | 0 | 335 |
| DE | 139 | 329 |
| D1 | 191 | 309 |
| D2 | 316 | 305 |
| D3 | 465 | 301 |
| D4 | 638 | 298 |
| D5 | 833 | 294 |
| D6 | 1041 | 290 |
| D7 | 1259 | 287 |
| D8 | 1488 | 283 |

**13 elements, 432.1 MHz** (rod 4.0 mm). Edge of band: 431.1 MHz 15.6 dBi, F/B 19.7 dB, Z 38-3j; 433.1 MHz 15.6 dBi, F/B 23.1 dB, Z 43+3j.

| Element | Position from R (mm) | Length (mm) |
|---|---|---|
| R | 0 | 335 |
| DE | 139 | 329 |
| D1 | 195 | 309 |
| D2 | 330 | 305 |
| D3 | 491 | 301 |
| D4 | 678 | 298 |
| D5 | 888 | 294 |
| D6 | 1113 | 290 |
| D7 | 1349 | 287 |
| D8 | 1596 | 283 |
| D9 | 1855 | 280 |
| D10 | 2124 | 277 |
| D11 | 2405 | 274 |

**17 elements, 432.1 MHz** (rod 4.0 mm). Edge of band: 431.1 MHz 16.7 dBi, F/B 18.3 dB, Z 51-2j; 433.1 MHz 16.8 dBi, F/B 18.8 dB, Z 47+3j.

| Element | Position from R (mm) | Length (mm) |
|---|---|---|
| R | 0 | 335 |
| DE | 139 | 334 |
| D1 | 191 | 305 |
| D2 | 316 | 302 |
| D3 | 465 | 299 |
| D4 | 638 | 296 |
| D5 | 833 | 294 |
| D6 | 1041 | 291 |
| D7 | 1259 | 288 |
| D8 | 1488 | 286 |
| D9 | 1728 | 283 |
| D10 | 1977 | 281 |
| D11 | 2238 | 279 |
| D12 | 2508 | 277 |
| D13 | 2786 | 275 |
| D14 | 3063 | 273 |
| D15 | 3341 | 271 |

## 70 cm satellite (435-438 MHz)

| Elements | Boom | Gain | F/B | Z at feed | 3 dB beam E/H | Stack E/H (DL6WU) | Rod |
|---|---|---|---|---|---|---|---|
| 7 | 0.83 m | 12.2 dBi | 22.1 dB | 41+0j ohm | 44° / 51° | 0.92 / 0.80 m | 4.0 mm |

**7 elements, 435.5 MHz** (rod 4.0 mm). Edge of band: 433.5 MHz 12.2 dBi, F/B 28.2 dB, Z 36-6j; 437.5 MHz 12.3 dBi, F/B 18.3 dB, Z 50+5j.

| Element | Position from R (mm) | Length (mm) |
|---|---|---|
| R | 0 | 332 |
| DE | 138 | 318 |
| D1 | 189 | 303 |
| D2 | 313 | 300 |
| D3 | 461 | 297 |
| D4 | 633 | 294 |
| D5 | 826 | 291 |

## Stacking

The DL6WU stacking distance is D = wavelength / (2 x sin(B/2)), where B is the 3 dB beamwidth in the plane you stack in. Stack in the E plane (side by side for horizontal elements) using the E beamwidth, and in the H plane (one above the other) using the H beamwidth. At this distance two Yagis give close to +3 dB minus feed losses (about 2.5-2.8 dB in practice) with clean sidelobes. Closer stacking gives a little less gain and a wider pattern; much wider stacking raises sidelobes. Feed both with equal-length cables into a power divider (a 2-way divider made from quarter-wave 75 ohm sections for 50 ohm antennas, or a commercial splitter) and keep the phasing the same (both driven elements oriented the same way).

## Feeding and matching

- **Plain split dipole:** feed impedance in the tables. Short Yagis (3-5 elements) run 15-30 ohm and need a match. Longer ones run 40-60 ohm and can often feed 50 ohm coax directly with a choke balun.
- **Folded dipole:** about 4 times the split-dipole impedance (equal rod sizes). Use a 4:1 coax half-wave balun (an electrical half wavelength of coax: length = 0.5 x wavelength x velocity factor) to get back to 50 ohm. Handy for 12-15 ohm short Yagis (4 x 12.5 = 50 ohm, then fed through a 1:1 choke) or 50 ohm designs with the 4:1 balun to 200 ohm.
- **Hairpin (beta) match:** shorten the driven element so it is capacitive, then a short shorted stub across the feed point brings it to 50 ohm. Simple and DC grounded.
- **Gamma match:** a rod alongside one half of a continuous driven element plus a series capacitor. Easy to tune on a mounted antenna; it slightly skews the pattern.
- **Direct 28 ohm feed:** the DK7ZB-style approach uses a split dipole designed for about 28 ohm and two parallel quarter-wave 75 ohm coax sections (37.5 ohm) as a transformer to 50 ohm. Design the Yagi for 25-30 ohm in NEC to use it.
- **Always** add a choke balun (ferrite beads or a few turns of coax) at the feed so the coax shield doesn't radiate, and keep the coax at right angles to the elements for a few element lengths.

## Cross-Yagi for satellites

- Two identical Yagis on one boom at 90 degrees (one horizontal, one vertical, or both at 45 degrees as an X).
- For circular polarisation, feed them in quadrature (90 degrees apart) in one of two ways:
  - offset one set of elements a quarter wavelength along the boom and feed both in phase, or
  - mount them in the same plane and add a quarter-wave delay line in one feed.
- Then combine with a 2-way divider. Swapping the delay to the other half switches between RHCP and LHCP; a relay box lets you choose per pass, since Faraday rotation and satellite tumbling change what works best.
- Typical portable/fixed satellite pair: 2x4 to 2x6 elements on 2 m with 2x7 to 2x10 elements on 70 cm, for example the 4-element 145.9 MHz and 7-element 435.5 MHz designs above built as crosses.
- With wide beams (60-90 degrees) azimuth-only or az/el pointing by hand works for most LEO passes; the narrower 70 cm beam benefits from a rotator (Hamlib rotctld with Gpredict).
- Mount 70 cm at least half a wavelength away from 2 m elements, or interlace carefully and model the combination: a 2 m element close to a 70 cm Yagi can spoil its pattern (2 m elements are near 3/2 wavelength at 70 cm).

## Modeling notes (NEC-2, xnec2c)

- Use 20 or more segments per half-wave element (keep segment length at least 4 times the wire radius and under 0.1 wavelength), and give all elements the same segment length when possible.
- Excite the middle segment of the driven element (EX card) and add a frequency sweep (FR card) across the band to check gain, F/B and SWR together. Use free space (GE 0 with no GN card, or GN -1) for the antenna itself, then add ground (GN 2 with real ground) only for the height and elevation-angle study.
- Model the boom when the elements touch it, or apply the correction above.
- xnec2c (GPL) reads standard NEC-2 card decks, runs multi-threaded, and plots gain, F/B, VSWR and impedance against frequency; it also has an optimizer link for scripted tuning. 4nec2 (Windows, freeware) and the NEC-2 based PyNEC (Python) do the same job.
- Minimal NEC-2 deck for the 5-element 144.2 MHz design above (6 mm rods, metres, elements along Y, boom along X):

```
CM 5-element 144.2 MHz Yagi, Ember reference
CE

GW 1 21 0.000 -0.5145 0 0.000 0.5145 0 0.003
GW 2 21 0.416 -0.4950 0 0.416 0.4950 0 0.003
GW 3 21 0.584 -0.4700 0 0.584 0.4700 0 0.003
GW 4 21 0.988 -0.4670 0 0.988 0.4670 0 0.003
GW 5 21 1.471 -0.4640 0 1.471 0.4640 0 0.003
GE 0
EX 0 2 11 0 1 0
FR 0 7 0 0 143.9 0.1
RP 0 1 361 1000 90 0 0 1
EN
```

## Quick numbers

- Wavelength in mm = 299,792 / MHz (2079 mm at 144.2 MHz, 694 mm at 432.1 MHz).
- Doubling the boom length adds roughly 2-2.5 dB of gain.
- Two stacked Yagis add about 2.5-2.8 dB; four add about 5-5.5 dB, less feed and divider loss.
- Coax loss matters at 70 cm: 15 m of RG-58 loses about 2.5 dB at 432 MHz, about the gain of stacking. Use low-loss cable or put the preamp at the antenna.
