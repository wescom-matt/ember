# Ember and ColdBoot

**Version 0.6.0** · private repo `wescom-matt/ember` · runs on the Nomad box (ThinkPad P1, `think-pad-p1`, 192.168.1.177)

**Ember** is an offline workshop assistant you open in a web browser on the home network. Its main jobs:

1. **Radio programmer:** reads, edits and writes radio channels with CHIRP, with an offline radio library that includes an AMSAT satellite pack (section 9).
2. **Coding, build and flash tool:** writes code and builds and flashes ESP32/LoRa boards (PlatformIO, arduino-cli, esptool).
3. **3D printer helper:** runs the ELEGOO Centauri Carbon 2, slices offline and keeps a parts library.
4. **Config changer, installer and fixer:** reads logs, edits config files, restarts services and installs packages on the P1 and your other computers.

5. **Off-grid project work:** keeps Outpost and the other `wescom-matt` projects buildable with no internet: repo mirrors, cached toolchains and packages, a developer reference library and a Projects view (section 13).
6. **Small-model helpers:** a context budget, code index, project notes, small-step mode, rolling chat summary, trimmed build errors and edit-by-diff help the small local models do real project work; switch to the slower `qwen3.5-9b-8k` when 4k runs out (section 14).

Ember is also a **general-purpose chat assistant**. Ask it anything: it answers from the local AI model, and when it helps it searches and cites the Nomad library, the radio and developer references or the parts library. Offline it is slower than an online assistant, and the small local model knows less, so check anything important. Ember never contacts the internet.

**ColdBoot** (`coldboot.sh`) rebuilds the whole P1 setup and Ember with one command, even offline from a USB disk. It also checks health and backs up and restores Ember's data.

| Document | What's in it |
|---|---|
| [COLDBOOT.md](COLDBOOT.md) | Step-by-step rebuild guide: USB contents, fresh install, sudo steps, troubleshooting |
| [docs/RECOVERY-PLAN.md](docs/RECOVERY-PLAN.md) | Plain description of the system and what to do in each disaster |
| [coldboot/Modelfiles.md](coldboot/Modelfiles.md) | Recipes for the custom 4k models |

---

## Contents
1. [The system on the P1](#1-the-system-on-the-p1)
2. [First-time setup (Matt runs these by hand)](#2-first-time-setup-matt-runs-these-by-hand)
3. [Using Ember](#3-using-ember)
4. [Users, admin and permissions](#4-users-admin-and-permissions)
5. [Computers (targets), roles and SSH keys](#5-computers-targets-roles-and-ssh-keys)
6. [Running commands safely](#6-running-commands-safely)
7. [Fix and install mode](#7-fix-and-install-mode)
8. [Radio programming (CHIRP)](#8-radio-programming-chirp)
9. [Radio reference library](#9-radio-reference-library)
10. [Code, build and flash (build hosts)](#10-code-build-and-flash-build-hosts)
11. [3D printer: ELEGOO Centauri Carbon 2](#11-3d-printer-elegoo-centauri-carbon-2)
12. [Parts library](#12-parts-library)
13. [Off-grid project work](#13-off-grid-project-work)
14. [Small-model helpers (4k and 8k)](#14-small-model-helpers-4k-and-8k)
15. [Security model](#15-security-model)
16. [ColdBoot](#16-coldboot)
17. [Where things live](#17-where-things-live)
18. [Troubleshooting](#18-troubleshooting)
19. [Honest limits](#19-honest-limits)
20. [For developers](#20-for-developers)
21. [Version history](#21-version-history)

---

## 1. The system on the P1

| Part | What it does | Address / command |
|---|---|---|
| Nomad (Project Nomad, Docker) | Offline library (medical, repair, radio, outdoors...). Installed separately. | `/opt/project-nomad` |
| Qdrant (in Nomad) | Library search index, `nomad_knowledge_base`, about 3.6 million passages | `127.0.0.1:6333` |
| Ollama 0.40.14 (in Nomad) | Runs the AI models | `127.0.0.1:11434` |
| Models | `qwen3.5-9b-4k` (default, can use tools), `qwen3.5-9b-8k` (bigger memory, slower on full turns; section 14), `llama3.2-4k`, `llama3.2-1b-4k`, `nomic-embed-text:v1.5` (search). "4k" models are the base models with a smaller memory window so they fit the 4 GB T1000 card. | |
| nomad-search | Library search command, also used by Goose | `nomad-search "question"` |
| Goose 1.59.1 | Terminal AI agent, asks before every action | `goose`, `goose-lw "task"` |
| Open Interpreter 0.4.3 | Code agent, asks before running code | `ai-interp` |
| **Ember** | This repo: the web app | `https://192.168.1.177:8600` |
| **ColdBoot** | Rebuild, check, backup, restore, offline cache | `~/ember/coldboot.sh` |

Other computers Ember can work on (once you add them, section 5):

| Computer | Typical role | Notes |
|---|---|---|
| Mint | radio host, build host | Linux, user `matt` |
| Zorin (T480s) | radio host | Linux, user `mwescom` |
| Los Gatos | build host, radio host | Windows (PowerShell) |
| Centauri Carbon 2 | printer | LAN only |

---

## 2. First-time setup (Matt runs these by hand)

Ember 0.6.0 is installed and running on the P1. These steps need you, because they need a password, a sudo prompt or physical access.

1. **Make your Ember admin account** (on the P1):
   ```bash
   ember create-admin matt        # asks for a password, 10+ characters
   ```
2. **Open Ember:** `https://192.168.1.177:8600`. Accept the certificate warning once; the certificate is self-signed.
3. **Turn on command running:** Users & admin → Targets & credentials → **Command running**.
4. **Add the P1 itself:** add a target of type **This computer**.
5. **Add your other computers.** For each one, add a credential, choose **Generate SSH key** and copy the public key into that computer's `~/.ssh/authorized_keys`. Then add the target with its roles and click **Test**. Details are in section 5.
6. **Set up each radio or build host** (Mint, Zorin). On that computer:
   ```bash
   git clone matt@192.168.1.177:ember ~/ember                       # copy from the P1 (or: git clone /media/USB/coldboot-cache/ember.bundle ~/ember)
   bash ~/ember/coldboot/buildhost/install-buildhost.sh             # radio + build tools, no sudo
   bash ~/buildhost-sudo-steps.sh                                   # read it first; needs your password
   ```
   The sudo steps add you to the `dialout` group (USB radio cables), install the udev rules for ESP32 boards and add the slicer's WebKit library. Log out and back in afterwards. On Los Gatos (Windows) run `coldboot\buildhost\install-buildhost.ps1` in PowerShell. It needs internet.
7. **Printer:** on the Centauri Carbon 2 screen, turn on **LAN-only mode** and note the **access code**. In Ember, add a password credential holding the access code. Then add a target of type **Printer** with the printer's LAN IP and that credential.
8. **Pick active hosts:** Workshop → Hosts. Choose the default radio host and build host.
9. **Make a USB copy** (section 16): `./coldboot.sh cache /media/matt/USB/coldboot-cache` and `./coldboot.sh backup --out /media/matt/USB/backups`.
10. **Later, when you're home with the P1:** set up Tailscale for remote access (section 3). It is not installed yet.

---

## 3. Using Ember

**Open it**
- At home: `https://192.168.1.177:8600`.
- Away from home, until Tailscale is set up: from a computer that can reach the P1, run `ssh -L 8600:127.0.0.1:8600 matt@192.168.1.177`, then open `https://localhost:8600`.
- **Tailscale (later):** this will be set up when you're home with the P1. It needs sudo and your Tailscale login. Ember stays the same; Tailscale only adds a private route to it from away. ColdBoot doesn't install or change Tailscale.

**The screen**
- **Left sidebar:** your chats (search, rename, delete), **Workshop**, **Users & admin** (admins only), **Change password**.
- **Chat box:** pick the model, the knowledge base (**None**, **Nomad**, **Radio reference**, **Parts library**, **Developer reference**), Think mode, **Commands** with a target computer, the **Project** (loads its notes and code) and **Small steps**. Under the box: a context indicator and, for the 8k model, a speed warning.
- **Workshop window** has six tabs: **Radio**, **Printer & slicing**, **Parts library**, **Hosts**, **Projects** (with project notes and the code index) and **Models** (speed sample).

**The `ember` command (on the P1)**

| Command | What it does |
|---|---|
| `ember status` / `start` / `stop` / `restart` | Controls the service |
| `ember logs [N]` | Last N log lines (default 50) |
| `ember url` | The LAN address |
| `ember create-admin NAME` | Makes an admin (password typed at a hidden prompt) |
| `ember reset-password NAME` | Sets a new password |
| `ember list-users` | Lists accounts |
| `ember version` | Prints the version |

Passwords are never taken as command-line arguments, printed or logged.

---

## 4. Users, admin and permissions

- Admins create accounts; there is no public sign-up. The limit is 50 users, and Ember always keeps at least one active admin.
- **Users & admin → Users:** add users, make or remove admins, tick **Run commands**, disable accounts, reset passwords.
- To run commands, use the Workshop or edit files, all of these must be on:
  1. the **master switch** (Command running; off by default)
  2. **Run commands** permission for that user (admins have it)
  3. the safety checks in section 6
- **Audit log:** logins, failed logins and lockouts, user and admin changes, credential and target changes, and every command, file edit, radio action and printer action, with who did it, its risk, the decision and the result.

## 5. Computers (targets), roles and SSH keys

A **target** is a computer or device Ember can work on:
- **This computer** (the P1)
- **SSH** (Linux with bash, or Windows with PowerShell)
- **Printer**

**Add an SSH computer**
1. Users & admin → Targets & credentials → add a credential → **Generate SSH key** → **Copy public key**.
2. On that computer, add the key as one line to `~/.ssh/authorized_keys`. On Windows use `C:\Users\<you>\.ssh\authorized_keys`, or `C:\ProgramData\ssh\administrators_authorized_keys` for admin accounts. Use a normal account, never root. A password credential also works.
3. Add the target: name, host or IP, port, user, Linux or Windows, the credential, and **Roles**. Presets fill in Mint, Zorin, Los Gatos and the printer.
4. Click **Test**. The first connection saves the computer's host key fingerprint. If the key ever changes, Ember refuses to connect until an admin clicks **Reset key**. That protects you from a fake computer on the network.

**Roles**
- A comma list: `radio`, `build`, `printer`, `general`, or your own words (letters, numbers and `-`).
- **Active host:** Workshop → Hosts sets the radio host and build host for everyone. Each chat can pick a different one ("this chat").
- If nothing is set, Ember uses the first enabled computer in this order:
  - radio: Mint, Zorin, Los Gatos
  - build: Los Gatos, Mint
- In a chat, the model can run a command on the chat's target, the radio host or the build host.

Ember never installs anything on other computers by itself. Their tools come from `install-buildhost.sh`, which you run there.

## 6. Running commands safely

In a chat, tick **Commands**, pick a target and ask. The model must support tools; the default `qwen3.5-9b-4k` does.

- **Safe commands** (read-only, like `ls`, `cat`, `journalctl`, `systemctl status`) run straight away.
- **Risky commands** show a card with the reason and wait for **Run** or **Cancel**. Risky includes:
  - recursive delete, `dd`, `mkfs`, shutdown or reboot
  - `sudo`, package installs, recursive chmod or chown
  - writes outside your home folder, command substitution
  - flashing: `esptool write_flash`, `pio -t upload`, `arduino-cli upload`
  - CHIRP uploads and memory writes to a real radio port
  - slicer output outside your home folder
  - PowerShell `Remove-Item -Recurse`, `Format-*`, `Stop-Computer`
  - anything unknown or that can't be parsed
- Limits:
  - 4 actions per reply
  - 120 seconds per command
  - commands up to 2,000 characters
  - output stored up to 8,000 characters; the model sees 2,500
- Known secrets are removed from output, and passwords and keys never reach the AI model.

## 7. Fix and install mode

Ask Ember to fix or set up something in a chat with **Commands** on. It will:
- **read logs** with `journalctl -u NAME` and status commands (safe, automatic)
- **edit files** with `write_file`. This always shows a Confirm card with the exact diff. The old file is kept as `<file>.bak-ember`.
- **restart services** and **install packages**. These are always confirmed. Sudo only works where `sudo -n` is allowed without a password. Otherwise Ember gives you the commands to run yourself.

## 8. Radio programming (CHIRP)

CHIRP runs on the **radio host**, the computer the programming cable is plugged into. It's a pinned version (commit `a477ca9`) in its own Python environment.

**Steps (Workshop → Radio)**
1. Add the radio (name, model, port if known).
2. **Find ports** on the radio host.
3. **Read radio (backup).** The first step is always a download, and it's saved before anything else happens.
4. **Open** an image to see its channels.
5. **Edit** channels. This makes a new image, and nothing is sent to the radio yet. You see a diff against the image it came from.
6. **Upload.** You confirm first. Ember reads a fresh backup from the radio right before writing.

Images are stored per radio in `~/.local/share/ember/radios/<id>/`, each with a SHA-256 check.

| Radio | Support |
|---|---|
| Baofeng BF-F8 Plus | Yes (CHIRP `Baofeng_UV-5R` driver) |
| Baofeng UV-5R | Yes |
| Baofeng UV-9R Plus | Probably (`Baofeng_UV-9R`). Not tested on your radio. A wrong model fails safely on the radio's ID check. |
| Kenwood TK-271 | No CHIRP driver. Ember offers the TK-270 family as a try; otherwise use Kenwood KPG software. |
| AnyTone AT-D868UV | **Not supported by CHIRP** (DMR radio). Use AnyTone CPS on Windows. Ember can't read, edit or store its codeplug. |
| ICOM IC-7300 | Read-only: a text snapshot of memories over CI-V. No image download or upload. |

## 9. Radio reference library

An offline, searchable library. Pick **Radio reference** in the chat. Answers cite the source, and Ember won't invent frequencies. Rules and orbits change, so check the source date for anything that matters. Stored in `~/.local/share/ember/radio-kb/` (about 23 MB with the AMSAT pack); every source, its licence, date and checksum is listed in `radio-kb/SOURCES.json`.

**Core (23 sources):** the ARRL band plan, FCC Part 97 (amateur) and Part 95 (GMRS, FRS, MURS, CB), the marine, aviation and Part 90 frequency rules, USCG marine channels, NOAA weather radio, NOAA space weather and background pages.

**AMSAT pack (50 sources, ~14 MB raw, ~2,600 passages in the whole library):** for amateur satellite, aircraft scatter and VHF/UHF antenna work.
- **Satellites and frequencies:** SatNOGS DB (CC BY-SA 4.0): every in-orbit amateur satellite's active transmitters, with uplink/downlink, mode, baud and inverting flag (for example RS-44's V/U linear transponder).
- **TLEs:** CelesTrak's amateur group and AMSAT's `nasabare.txt` (public orbital data). They're also saved as plain files in `radio-kb/tle/`, so Gpredict can import them offline (Edit → Update TLE → from local files).
- **Ember guides** (written for Ember, in `docs/amsat/`):
  - pass prediction and TLE freshness
  - Doppler formulas and the "one true frequency" rule
  - Hamlib `rigctld` with the IC-7300. Note that it covers HF/6 m only, so it's useful just for 10 m/6 m links or with transverters.
  - `rotctld` with Gpredict
  - pointing a phased array from az/el (element phases, true time delay, grating lobes)
  - radar basics (pulse, FMCW), monopulse and beam-steered tracking, alpha-beta and Kalman track filters
  - beam update timing, pass scheduling, make-before-break handoff between satellites and Doppler hand-over
  - **cued beam steering** for ham links: a radar, ADS-B or orbit-prediction track turned into az/el and then into array or rotator pointing (frame conversion, track filter, latency prediction, Doppler); **aircraft scatter** on 2 m/70 cm/23 cm with ADS-B scheduling; and an overview of the VHF/UHF contest rules (ARRL, CQ WW VHF, IARU Region 1)
  - **Small mmWave radars as pointing cues** (TI IWR1843BOOST, D3 RS-6843 24-patch, TI IWR6843AOPEVM): specs, flashing with UniFlash, `.cfg` chirp files, the UART TLV format (point cloud, tracker output), mounting and lever-arm maths, smoothing, latency and rotctld, with honest range limits. The reader is `scripts/mmwave_cue.py` (CC0). TI/D3 documents are linked and summarised, not copied. See the comparison below.
  - **2 m and 70 cm Yagis:** element tables for 3-11 elements (144.2 MHz), 7-17 elements (432.1 MHz) and satellite 4-element (145.9) and 7-element (435.5) designs, designed and modeled by Ember with NEC-2 (gain, F/B, impedance, beamwidth, DL6WU stacking distances). Also boom correction, matching (folded dipole, 4:1 balun, hairpin, gamma, 28 ohm with 75 ohm quarter-wave lines), cross-Yagis for circular polarisation and xnec2c modeling notes with a sample NEC deck. These are starting points: model and measure your build.
- **Software docs:**
  - Hamlib `rigctld`/`rigctl`/`rotctld`/`rotctl` man pages (GPL)
  - Gpredict rig notes for the IC-9700, IC-9100, IC-910 and FT-847, plus its time-keeping note (GPL)
  - the KrakenSDR DoA software README (GPL-3.0)
  - the xnec2c README (GPL) and the dump1090-fa ADS-B decoder README (GPL-2.0+)
- **Tutorials and background:**
  - PySDR chapters on beamforming/DOA, the Phaser (CN0566) phased array and PlutoSDR (CC BY-NC-SA 4.0: free to keep and share, not for commercial use)
  - Wikipedia (CC BY-SA 4.0) on amateur satellites, TLEs, SGP4, Doppler, az/el coordinates, phased arrays, beamforming, beam steering, monopulse, FMCW and pulse-Doppler radar, radar trackers, alpha-beta and Kalman filters, handover, direction finding, the Yagi-Uda antenna, antenna gain, front-to-back ratio, baluns, folded dipoles, antenna arrays, radiation patterns, NEC, ADS-B, tropospheric propagation, radio horizon and amateur radio contests
- **Left out on purpose** (no open licence):
  - the AMSAT status and frequency pages
  - JE9PEL's satellite list
  - the KrakenSDR wiki and manuals
  - the Analog Devices wiki
  - published DK7ZB, DL6WU and Cushcraft element tables (copyrighted). Ember's own NEC-modeled designs follow the same long-Yagi spacing method instead.
  - AirScout, which is only mentioned by name

**Radar and DF options for drone fox hunts and radar-cued Yagi pointing** (prices late 2026; ranges are estimates scaled from TI/D3 figures):

| Option | Small drone | Aircraft | FoV | Angle resolution | Cost | Tiling / sync | Software |
|---|---|---|---|---|---|---|---|
| **ADS-B** (RTL-SDR + dump1090-fa/readsb) | – | 200-400 km | all-round | exact position | $30-60 | merge many receivers | open source, mature |
| **KrakenSDR** (5-ch coherent RF DF) | the fox **transmitter** at km range | – | 360° | a few degrees | $749 + antennas | coherent per unit; triangulate | open source, Raspberry Pi |
| TI IWR1843BOOST | ~15-40 m | ~200-300 m | ±60° / ±15° | 15° / 58° | ~$299 | independent; HW frame trigger | SDK 3.x, Radar Toolbox |
| D3 RS-6843 24-patch | **~75-80 m** (measured) | ~150 m+ | ~20° beam | none (staring beam) | quote | independent | TI SDK + D3 |
| TI IWR6843AOPEVM | ~15-25 m | ~130 m | ±60° / ±60° | 29° / 29° | ~$175-210 | independent | SDK 3.x, 3D tracking |
| TI IWR6843ISK | ~30-45 m | ~175-310 m | ±60° / ±20° | 15° / 58° | ~$243 | independent | same as AOP |
| TI AWR2944EVM | ~40-55 m | ~250 m | ±80° az | ~9.5° az | ~$549 | independent | MCU+ SDK (more work) |
| TI 4-chip cascade (MMWCAS) | ~50-70 m | 350 m+ | ±70° / ±30° | 1.4° az | $1,300-6,800 + DSP board | coherent LO | heavy (Studio/MATLAB) |
| Infineon BGT60TR13C / Acconeer XE121 | ~5-10 m | – | 60-90° | coarse / none | ~$100-230 | independent | vendor SDKs |

**Recommendation:**
1. **Aircraft scatter:** use **ADS-B**, not radar. It is 100× the reach, passive and about $40.
2. **Drone fox hunts:** use **KrakenSDR** direction finding for the transmitter, plus **one narrow-beam radar on the boom** for the last 50-80 m. The D3 RS-6843 24-patch is the best of the three picks for that.
3. **Wide-view radar cue:** the **IWR1843BOOST** is the best of the three. The **IWR6843ISK** is a better 60 GHz buy than the AOPEVM unless you need ±60° elevation. Skip the cascade, BGT60 and Acconeer for this job.

Refresh while online on the P1:
- `.venv/bin/python scripts/fetch_radio_kb.py --only amsat` updates TLEs and SatNOGS. Do it weekly before satellite work.
- `.venv/bin/python scripts/fetch_radio_kb.py` updates everything.
- `--rebuild` only re-indexes the saved files, offline.

## 10. Code, build and flash (build hosts)

A **build host** compiles and flashes boards and slices 3D models. Set one up with `install-buildhost.sh` (section 2, step 6). Everything is installed at user level, pinned and checksum-verified:

| Tool | Version |
|---|---|
| PlatformIO | 6.2.0 |
| esptool | 5.7.0 |
| arduino-cli | 1.6.0 (ESP32 core and LoRa libraries) |
| OrcaSlicer | 2.5.2 |
| ElegooSlicer | |
| Centauri Carbon 2 profiles | 55 profiles |
| CHIRP | `a477ca9` |

The tools are installed in `~/.local/share/ember/` and `~/.local/opt/`, with links in `~/.local/bin/`. Offline: `./coldboot.sh install --build-host --cache /media/matt/USB/coldboot-cache` (add `--radio` or `--build` for one side only).

Then ask in chat, for example "build ~/lora-sender for the ESP32 on the build host and flash it". Compiling runs straight away; flashing waits for **Run**.

You don't have to use these pinned tools. Ember checks the host's PATH over SSH and uses what's already there: Los Gatos's own PlatformIO 6.2.0 with espressif32 7.1.3 works as it is. `arduino-cli` must be on PATH (Arduino IDE 2's bundled copy usually isn't), and Windows hosts need OpenSSH Server. Project-specific toolchains for offline use are in section 13.

## 11. 3D printer: ELEGOO Centauri Carbon 2

- **How Ember talks to it:**
  - commands go over MQTT on port 1883 (user `elegoo`, password = your access code, or `123456` if none is set)
  - the printer is found by UDP discovery on port 52700
  - files are sent with HTTP PUT to `/upload`

  This was worked out from ELEGOO's open-source slicer and community tools. ELEGOO doesn't publish an official API.
- **Needs:** LAN-only mode turned on at the printer, and the printer target set up (section 2, step 7). Only private home-network addresses are accepted.
- **Workshop → Printer & slicing:**
  - **Status** and **Pause** run straight away.
  - **Resume**, **Cancel**, **Send to printer** and **Start print** always ask first. Check the bed is clear and the right filament is loaded.
  - **Slice** runs OrcaSlicer on the build host with the CC2 profile. Defaults: `0.20mm Standard @Elegoo CC2 0.4 nozzle`, `Elegoo PLA @ECC2`; 0.4/0.2/0.6/0.8 nozzles are supported. The G-code then goes from the build host to the printer.
- In chat, the model can ask for status or pause, or propose start or cancel; those always need your OK.

## 12. Parts library

An offline library of printable parts and repair guides on the P1, in `~/.local/share/ember/parts/`. Every part records its name, category, source link, license, author, tags and print notes. Search it in Workshop → Parts library, or pick **Parts library** in a chat. **Slice for CC2** sends a part to the build host and slices it.

**What's in it now:** 200 parts (966 MB) and 214 iFixit repair guides.

| Category | Parts | Examples |
|---|---|---|
| Antenna parts | 30 | Yagi, Moxon and QFH parts, dipole center (SO-239), end insulator, coax strain relief, mast clamps, element holders, SMA/BNC/SO-239 mounts, magnetic-loop tuners |
| Plumbing fittings | 16 | pipe fittings and valves, hose adapters and barbs, 1/4" drip fittings and stakes, drain and Y-valves, pipe clamps |
| Radio mounts | 8 | HT holders (UV-5R/BF-F8+, UV-9R Plus, AT-D868UV), IC-7300 go-kit, mic hanger, desk tilt wedge, QCX case |
| ESP32 / LoRa cases | 32 | DevKit, Heltec, TTGO LoRa32, T-Beam, Wemos D1 mini, Meshtastic and sensor/solar node cases |
| Cable management | 8 | clips, cable box, cable ties, strain relief |
| Solar and battery | 16 | 18650 holders, battery boxes, solar panel brackets |
| Tools | 17 | clamps, wrench, jigs, Gridfinity storage |
| Household repair | 23 | knobs, hooks, spacers, replacement parts |
| CoreXY printer parts | 49 | Voron 2.4, Voron 0 and Voron Tap parts |
| Off-grid | 1 | hose barb reducer |

- **Licenses:** only open ones (CC0, CC-BY/SA/NC, GPL, MIT, BSD, Apache, CERN-OHL, MPL, public domain). Anything without a clear license is refused.
  - For GitHub repos, the license in `coldboot/parts-seed.json` must match the repo's own LICENSE file.
  - Repos with mixed licenses need a hand-checked entry.
  - Folders with their own license are left out.
- **Duplicates:** identical files are stored once (SHA-256).
- **Repair guides** are from iFixit under CC BY-NC-SA 3.0, with authors credited.
- 23 designs were made by Ember in OpenSCAD and are public domain, in `coldboot/parts-scad/`. Radio and board sizes in those are typical, so measure yours before printing.

**Add more** (on the P1, in `~/ember`):
```bash
.venv/bin/python scripts/parts_import.py add-file part.stl --name "Antenna clip" --category antenna-radio \
    --license CC-BY-4.0 --source https://example.org/thing --author someone --tags "clip mast"
.venv/bin/python scripts/parts_import.py add-url https://example.org/part.stl --name ... --category ... --license ...
.venv/bin/python scripts/parts_import.py list antenna      # search
.venv/bin/python scripts/parts_import.py stats
.venv/bin/python scripts/parts_import.py remove 42         # delete part #42
.venv/bin/python scripts/parts_import.py seed --max-gb 3   # re-run the seed list (adds only what's new)
```
Categories: `antenna-radio`, `radio-mounts`, `plumbing`, `electronics-enclosure`, `cable-management`, `solar-battery`, `tools`, `household`, `off-grid`, `printer-parts`, `corexy`, `storage`, `other`.

For Printables or Thingiverse, download the file yourself and copy the license shown on the page into `--license`. Ember doesn't scrape those sites; Thingiverse's API needs a registered app and Printables has no public API. To grow the seed, add GitHub repos (with `license`) to `coldboot/parts-seed.json`. The `--max-gb` cap covers the whole library (default 3 GB).

## 13. Off-grid project work

The goal: keep working on Outpost and the other `wescom-matt` projects with no internet. It's slower, but it works.

**Projects view** (Workshop → **Projects**) lists the 13 projects: repo, build host and folder, backup host, board, PlatformIO env, serial port and the build/test/flash commands. Click **Ask Ember: <command>** to put a command in the chat. Ember runs it on that host through the normal approval flow (building runs straight away, flashing waits for **Run**). Admins can edit the list as JSON (it's saved in `~/.local/share/ember/projects.json`). The chat agent also gets this list, so "build Outpost" knows where and how.

| Project | Build host (backup) | Notes |
|---|---|---|
| Outpost | Los Gatos `C:\Users\Matt\Documents\Outpost` (Mint `~/projects/Outpost`) | Heltec V3, env `heltec_v3_arduino3` (ship), `heltec_v3` (legacy), `native` tests |
| Outpost 2.0 (Heltec V4) | planned | Heltec V4-R8, see below |
| FEW, Face-AI, ember, CamWall, BlackCat, bcfc-workspace, SystemScrape, rebuild-kit-builder, NomadHardware, FEW-Jenkins, wescom | see the Projects view | Python, .NET, Flutter, etc. |

**Repo mirrors.** All 12 repos are bare mirrors in `~/git/NAME.git` on the P1, with issues and pull requests saved as JSON in `~/git/issues/`. Refresh them while online with `scripts\windows\mirror-repos.ps1` on Los Gatos (uses its GitHub login, copies bundles to the P1 and runs `scripts/import-mirrors.sh`). Refreshing never overwrites offline work: a branch that changed on both sides is skipped with a warning. The USB cache also holds a `git bundle` of every repo (`repos/`), and `./coldboot.sh install --cache DIR` imports them.

**Offline git workflow**
```bash
git remote add p1 matt@192.168.1.177:git/Outpost.git    # once, on each computer (los-gatos-user-steps.ps1 does it on Los Gatos)
git pull p1 main    # get work from the P1
git push p1 main    # share work through the P1 instead of GitHub
git clone /media/matt/USB/coldboot-cache/repos/Outpost.bundle Outpost   # no P1? clone from the USB
```
Back online, push the mirrors to GitHub: on Los Gatos `cd` into each clone and `git push origin main`, or on the P1 run `bash scripts/p1-github-key.sh` once (add the printed key at github.com/settings/keys), then `bash scripts/sync-mirrors.sh push`. `sync-mirrors.sh fetch` pulls GitHub changes into the mirrors. Neither one force-pushes.

**Using tools already on a host.** Ember doesn't need its own toolchain on a build host. It runs commands over SSH, so whatever is on that host's PATH works:
- Los Gatos already has PlatformIO 6.2.0 with espressif32 7.1.3 and the Outpost packages; they work as they are.
- `arduino-cli` must be on PATH. The copy bundled inside Arduino IDE 2 usually isn't.
- Windows hosts need **OpenSSH Server** (`scripts\windows\los-gatos-admin-steps.ps1`) before Ember can reach them.

**Offline caches** (in the USB cache, `./coldboot.sh cache DIR`; `--skip-projects` leaves them out, `--only-projects` makes only them):

| Cache folder | What | How to use offline |
|---|---|---|
| `buildhost/pio-envs/<core>/` | PlatformIO cores pinned to Outpost: `pioarduino-55.03.312-…` (Arduino-ESP32 3.3.12, ship env and Outpost 2.0), `espressif32@7.1.3` (legacy env), `native` | `install-buildhost.sh --cache DIR` copies them to `~/.platformio-envs/` and fixes their paths. Then `PLATFORMIO_CORE_DIR=~/.platformio-envs/<core> pio run -e <env>` |
| `projects/<name>/libdeps/` | Exact library versions (RadioLib 7.8.1, ArduinoJson 7.4.3, NimBLE, Adafruit SSD1306/GFX/BusIO) | copy to the project's `.pio/libdeps/` |
| `projects/wheels/{linux,windows}/` | Python 3.12 wheels for FEW, Face-AI and ember | `pip install --no-index --find-links DIR -r requirements.txt` |
| `projects/npm-cache/` + `projects/node/` | FEW frontend packages (Linux and Windows) and Node 24.19.0 | `npm ci --offline --cache DIR` |
| `projects/nuget.tar.gz` | 74 NuGet packages for the 7 .NET solutions | extract, then `dotnet restore --source DIR` |
| `dev-kb/` | Developer reference (below) | copied to `~/.local/share/ember/dev-kb/` |
| `projects/MANIFEST.json` | What was cached, versions and any problems | |

**Developer reference library.** Pick **Developer reference** in the chat. About 160 MB, 27 freely available sources, each recorded with its URL, date and checksum in `~/.local/share/ember/dev-kb/SOURCES.json`:
- ESP32-S3 datasheet and technical reference manual, ESP-IDF 4.4 and 5.5 docs, Arduino-ESP32 2.x and 3.x docs, RadioLib 7.8.1 headers
- LoRaWAN 1.0.4 and regional parameters (RP002 1.0.3; 1.0.4 is behind a sign-up form), SX1262 datasheet
- Heltec V3/V3.2 datasheets, schematic and pinout; **Heltec V4-R8** and V4 datasheets, V4-R8 schematic and pinout
- **Packet radio:** AX.25 2.2 spec (TAPR), KISS, APRS 1.0.1 spec, Direwolf docs, Linux AX.25 HOWTO and ax25 tools man pages, ITU X.25 recommendation, background pages on X.25 and AX.25

Build or refresh it online: `.venv/bin/python scripts/fetch_dev_kb.py [--rebuild]`. Add `--with-api-docs` for the Flutter API docs (about 100 MB more). The .NET API docs aren't included.

**Outpost 2.0 (Heltec WiFi LoRa 32 V4-R8).** Checked against Heltec's datasheet and wiki: ESP32-S3R8 (8 MB octal PSRAM), 16 MB flash, SX1262 LoRa radio with a 28 dBm front end (model HTIT-WBR8H). Radio pins are the same as the V3 (NSS 8, SCK 9, MOSI 10, MISO 11, RST 12, BUSY 13, DIO1 14). The R8 changes: LED 46, Vext 40, GNSS power 42, PA control 5, FEM enable 2, FEM power 7.
- **Gap:** there is no official PlatformIO board for the V4. Arduino-ESP32 3.3.12 has a `heltec_wifi_lora_32_V4` variant, but it matches the R2 board (other PSRAM, LED and Vext pins).
- So Ember ships a starter project in `coldboot/outpost2-template/`: a custom board file, an R8 pin variant and `platformio.ini` env `heltec_v4r8` on the same toolchain as Outpost (pioarduino 55.03.312). `src/main.cpp` is a bring-up check: PSRAM size, radio start at 915 MHz, LED blink. It doesn't transmit.
- It builds online and offline from the cache. It has **not been tested on a real board** yet. Check the front-end pins against the board before you transmit.

**What doesn't work offline**
- No pull requests, issues, GitHub Actions or cloud agents. You can read saved issues and PRs in `~/git/issues/`.
- iOS builds need a Mac.
- BlackCat and Face-AI features that call online AI services won't work.
- The local models are slower and weaker than online ones. Use short steps and check their code.
- Outpost's legacy `heltec_v3` env fails to compile on `main` (the code uses the Arduino 3 `softAPConfig`); that is a code issue, not the cache. Use `heltec_v3_arduino3`.

**Hand-run steps (once, while online)**
1. Los Gatos, PowerShell as admin: `scripts\windows\los-gatos-admin-steps.ps1` (OpenSSH Server on the private network only, CMake, g++, Inno Setup check). Optional `-EmberPublicKey "ssh-ed25519 ..."`.
2. Los Gatos, normal PowerShell: `scripts\windows\los-gatos-user-steps.ps1` (clones BlackCat, bcfc-workspace and rebuild-kit-builder, fetches all, adds the `p1` remote, runs one online `flutter build apk` for Outpost's app so Gradle's cache is filled).
3. Los Gatos: `scripts\windows\mirror-repos.ps1` and `scripts\windows\nuget-offline.ps1` whenever you want fresh copies.
4. Optional, P1: `bash scripts/p1-github-key.sh`, so the P1 can sync mirrors with GitHub itself.
5. Mint and Zorin: `sudo apt install build-essential cmake` for Outpost's native tests.
6. Refresh the USB: `./coldboot.sh cache /media/matt/USB/coldboot-cache`.

## 14. Small-model helpers (4k and 8k)

The local models have a small memory: `qwen3.5-9b-4k` holds about 4,000 tokens (roughly 14,000 characters) for the whole turn. Ember 0.6 packs that memory carefully so project work still goes well.

**Pick a project** in the chat box (the **Project** list). Ember then adds the project's notes and the most relevant code to each turn. Turn on **Small steps** (needs **Commands**) for bigger jobs.

| Helper | What it does |
|---|---|
| **Context budget** | Splits the model's memory per turn: 4k = system 25%, notes 8%, code/references 20%, history 22%, reply 25%; 8k gives code and history more room. The line under the chat box shows what this turn used, for example `Context ~2.9k / 4.1k tokens: sys 900 · notes 310 · code/refs 780 · history 870 · reply 1.0k · code: main.cpp:120`. |
| **Code index** | Splits each project's source (C/C++/Arduino, Python, Dart, C#, JS/TS) into function-sized chunks, embeds them with `nomic-embed-text` and pulls the best 3-5 chunks that fit the budget into each turn. It reads the repo mirror in `~/git` (offline; may lag work not yet pushed from the build host), skips generated code, and re-indexes changed files in the background when the mirror's HEAD changes. Outpost: 133 files, ~800 chunks. **Re-index code** in Workshop → Projects forces it. |
| **Project notes** | A short summary per project (purpose, board, pins, commands, key decisions), loaded first. Auto-drafted from the Projects entry and the repo (README, `platformio.ini`, pin `#define`s) with no model call; edit and save it in Workshop → Projects → Project notes (admin). The agent can propose changes with `update_notes`; you see the diff and confirm. The last 5 versions are kept. |
| **Small steps** | The model first plans the task as up to 6 tiny steps. Each step then runs with a fresh, minimal context: notes + code for that step + the step + one line per finished step. The plan shows in the reply and each step is ticked off as it finishes. Risky actions still stop for **Run**. |
| **Rolling summary** | When a chat's history no longer fits, older turns are compressed into a short summary (one extra model call) and the last 4 messages stay word for word. You see a notice when it happens. |
| **Trimmed build errors** | When a command fails with long output, the model gets only the first real errors (PlatformIO/gcc, CMake, Flutter/Dart, dotnet, Python tracebacks) plus the source lines around them from the mirror, about 1 KB instead of 8 KB. The full output is still in the action card. |
| **Edit by diff** | `edit_file` takes small SEARCH/REPLACE blocks or a unified diff. Ember reads the file, applies the edit, checks it (every block must match once, braces stay balanced, Python must still parse), shows the diff, asks, then writes it and keeps `FILE.bak-ember`. `write_file` is now only for new files. |

**The 8k model.** `qwen3.5-9b-8k` is the same model with an 8,192-token memory. Pick it in the model list when 4k runs out (big files, long error logs). A warning with the measured numbers appears when you select it. 4k stays the default.

**Speed sample** (Workshop → **Models**; measured on the P1, Quadro T1000 4 GB, 2026-11-25; only about a third of the 9B model fits on the GPU, so most of it runs on the CPU; actual speed varies):

| Model | Writing speed | First word, short prompt | First word, full memory | Reading speed | On GPU |
|---|---|---|---|---|---|
| qwen3.5-9b-4k | 4.6 tok/s | 6.6 s (cold start) | 50 s (3,300 tokens) | ~66 tok/s | 1.97 GB (33%) |
| qwen3.5-9b-8k | 4.4 tok/s (4.0 when full) | 6.7 s (cold start) | 102 s (6,500 tokens) | ~64 tok/s | 1.88 GB (31%) |

At the same prompt size both models are equally fast. The 8k model is slower only because a full 8k turn has twice as much to read. Admins can click **Re-run benchmark** (about 10 minutes; it briefly unloads other models) to store fresh numbers for this machine in `~/.local/share/ember/model-bench.json`. You can also run `.venv/bin/python -m ember.bench` on the P1.

## 15. Security model

- **Offline:** Ember only talks to Ollama and Qdrant on `127.0.0.1`, plus the computers and printer you add.
- **Passwords:** stored as argon2id hashes. A login locks for 5 minutes after 5 failures.
- **Sessions:** random tokens, kept only as hashes. Cookies are HttpOnly, SameSite=Strict and Secure, and last 7 days.
- **Web:** an `X-Ember: 1` header is required on every change, which blocks cross-site tricks. There's a strict content security policy with no outside scripts.
- **Saved logins** (SSH keys, passwords, printer access codes) are encrypted with `~/.config/ember/secret.key`, which is kept outside the database. A copied database alone reveals nothing.
- **Commands** run through argument lists (never `shell=True`) and are gated by the master switch, the user's permission, the risk checks and Confirm cards, with timeouts and output limits. SSH host keys are trusted on first use, and a changed key is refused.
- **Service:** runs as your user (`systemd --user`) with a private file mask and `NoNewPrivileges`.
- **No secrets in the repo.** Coding rules are in `.cursor/rules/` (NASA Power of 10, SEI CERT, Bandit).

## 16. ColdBoot

```bash
cd ~/ember
./coldboot.sh check                                  # PASS/WARN/FAIL for every part
./coldboot.sh install [--cache DIR] [--dry-run]      # rebuild whatever is missing (no sudo)
./coldboot.sh install --system                       # print + save the steps that need sudo
./coldboot.sh install --build-host [--cache DIR] [--radio|--build]   # radio/build host tools
./coldboot.sh backup [--out DIR]                     # Ember's data -> .tar.gz + checksums
./coldboot.sh restore ARCHIVE [--to DIR] [--dry-run] [--yes]
./coldboot.sh cache DIR [--skip-models] [--skip-buildtools] [--only-buildtools] [--skip-projects] [--only-projects] [--with-arduino-core] [--parts-gb N]
```

**install** runs as your normal user, never uses sudo and is safe to repeat. It saves any file it changes as `*.bak-coldboot-<date>`. It puts back:
- uv and Python 3.12
- Ollama (only if Nomad's isn't running)
- the models, including rebuilding the 4k models
- Goose and Open Interpreter, with their configs
- nomad-search
- Ember and its service
- CHIRP, the radio library and the parts library (from the cache)
- the project mirrors in `~/git` and the developer reference (from the cache; mirrors are only added to, never overwritten)

It checks Nomad and Qdrant read-only and never changes them. Steps that need sudo go into `~/coldboot-sudo-steps.sh` for you to read and run.

**backup** writes `ember-coldboot-<host>-<date>.tar.gz` (mode 600) and a `.sha256` file. It holds the database (users, chats, targets, encrypted logins, radio list, audit log), **the secret key**, settings, the TLS certificate, the Goose and Interpreter settings, project notes, the projects list and the model speed sample. Keep it offline; never email or upload it. Radio images, the parts library and the radio library are not in the backup. Copy `~/.local/share/ember/radios/` yourself if you want your radio backups saved too.

**restore** checks every checksum and refuses unsafe archives. It keeps replaced files as `*.pre-restore-<date>` and restarts Ember. `--to DIR` tests into a folder, and `--dry-run` only checks.

**cache** fills a USB disk for an offline rebuild, **about 28 GB** (about 20 GB with `--skip-projects`):

| Folder | Contents | Size |
|---|---|---|
| `models/` | AI models | ~10.2 GB |
| `ollama/` | Ollama 0.40.14 | ~1.5 GB |
| `goose/` | Goose 1.59.1 | ~0.35 GB |
| `python/` | uv, Python 3.12, Open Interpreter packages | ~0.2 GB |
| `ember-wheels/` | Ember's packages | ~0.03 GB |
| `buildtools/` | CHIRP, PlatformIO + ESP32 packages, esptool, arduino-cli, OrcaSlicer, ElegooSlicer, CC2 profiles | ~5.4 GB |
| `parts/` | Parts library (skipped if bigger than `--parts-gb`, default 3) | ~1 GB |
| `radio-kb/` | Radio reference library with the AMSAT pack | ~23 MB |
| `buildhost/pio-envs/` | Outpost's PlatformIO cores: pioarduino 55.03.312 (ship env, Outpost 2.0) ~5.5 GB, espressif32 7.1.3 (legacy env) ~2 GB | ~7.5 GB |
| `projects/` | Library versions, Python wheels, npm cache, Node, NuGet packages, MANIFEST.json | ~0.7 GB |
| `repos/` | `git bundle` of all 12 repos, plus issues and PRs | ~0.06 GB |
| `dev-kb/` | Developer reference library | ~0.16 GB |
| `arduino/` | Arduino ESP32 core, only with `--with-arduino-core` | ~9 GB |
| `ember.bundle`, `COLDBOOT.md`, `SHA256SUMS` | Repo copy, guide, checksums | small |

A 32 GB USB disk still fits (about 28 GB, so only ~2 GB spare); **a 64 GB disk is recommended**, and is required with `--with-arduino-core` (about 37 GB). Every download is pinned by SHA-256 in `coldboot/pins.txt` or hashed requirement files, and nothing is piped from `curl` into a shell. Full rebuild guide: [COLDBOOT.md](COLDBOOT.md).

## 17. Where things live

| What | Where (on the P1) |
|---|---|
| Code | `~/ember` (must be this path) |
| Settings (no secrets) | `~/.config/ember/ember.env` |
| Secret key (back it up!) | `~/.config/ember/secret.key` |
| TLS cert and key | `~/.config/ember/tls/` |
| Database | `~/.local/share/ember/ember.db` |
| Radio images | `~/.local/share/ember/radios/<id>/` |
| Radio library | `~/.local/share/ember/radio-kb/` (TLE files in `tle/`, sources in `SOURCES.json`) |
| Project notes | `~/.local/share/ember/notes/` (in the backup) |
| Code index | `~/.local/share/ember/code-index/` (rebuilt from the mirrors) |
| Model speed sample | `~/.local/share/ember/model-bench.json` (else the sample shipped in `ember/model_bench_sample.json`) |
| Parts library | `~/.local/share/ember/parts/` |
| Developer reference | `~/.local/share/ember/dev-kb/` (sources in `SOURCES.json`) |
| Projects list | `~/.local/share/ember/projects.json` (seed: `coldboot/projects-seed.json`) |
| Repo mirrors | `~/git/NAME.git`, issues and PRs in `~/git/issues/` |
| NuGet packages | `~/offline/nuget.tar.gz` |
| CHIRP helper | `~/.local/share/ember/chirp-venv/` |
| Service | `~/.config/systemd/user/ember.service` |
| Backups (default) | `~/coldboot-backups/` |
| Sudo steps | `~/coldboot-sudo-steps.sh`, `~/ember-sudo-steps.sh`, `~/buildhost-sudo-steps.sh` (build hosts) |
| Goose config | `~/.config/goose/config.yaml` |
| Older rebuild kit | `~/agent-stack-backup/` |

On radio and build hosts: `~/.local/share/ember/` (chirp-venv, pio-venv, slicer profiles), `~/.local/opt/` (slicers), `~/.local/bin/` (links), `~/.platformio-envs/` (cached PlatformIO cores).

## 18. Troubleshooting

| Problem | What to do |
|---|---|
| Ember doesn't open | `ember status`, `ember logs`, then `ember restart`. Still broken: `./coldboot.sh install`. |
| Browser certificate warning | Expected (self-signed). Accept it once. |
| "Commands are off" in chat | Turn on the master switch, give the user **Run commands**, pick a target, use a model with tools. |
| SSH target fails **Test** | Check the IP, user and that the public key is in `authorized_keys` on that computer. "Host key changed": make sure it's really your computer, then **Reset key**. |
| "no radio host" / "no build host" | Add the role to a target and pick it in Workshop → Hosts. |
| No serial ports found | Plug in the cable. On Linux, run the build host sudo steps (`dialout` group) and log out and back in. Try `ls /dev/serial/by-id`. |
| CHIRP download fails | Check the radio is on, the volume is up, the cable is seated and the model is right. Cheap cables (fake Prolific chips) often fail; an FTDI or CH340 cable is more reliable. |
| "CHIRP helper not installed" on the P1 | `bash ~/ember/coldboot/buildhost/install-buildhost.sh --chirp-only` |
| Printer test/status fails | Printer on, LAN-only mode on, right IP and access code, same network. |
| Slicing fails | Run `install-buildhost.sh --build` on the build host and its sudo steps (the slicer needs `libwebkit2gtk-4.1-0`). |
| Parts search empty | `.venv/bin/python scripts/parts_import.py stats` on the P1; re-run `seed` while online, or `./coldboot.sh install --cache DIR`. |
| `./coldboot.sh check` shows FAIL | Read the FAIL line; most are fixed by `./coldboot.sh install`. More in [COLDBOOT.md](COLDBOOT.md). |
| Code chunks never show up | The project needs a mirror in `~/git` (section 13). Workshop → Projects shows "Code index: … chunks"; click **Re-index code**. Check `ember logs` for "code index". |
| 8k model feels stuck | A full 8k turn takes about 1.5-2 minutes before the first word on the P1. Use 4k with **Small steps** for long jobs. |
| Satellite frequencies or TLEs look old | `.venv/bin/python scripts/fetch_radio_kb.py --only amsat` while online. |
| Forgot the Ember password | `ember reset-password matt` on the P1. |
| Projects view says "no mirror" | Run `scripts\windows\mirror-repos.ps1` on Los Gatos while online, or `bash scripts/import-mirrors.sh /media/matt/USB/coldboot-cache/repos` on the P1. |
| Developer reference empty | `.venv/bin/python scripts/fetch_dev_kb.py` on the P1 while online (needs `pdftotext`). |
| Offline `pio run` tries to download | Set `PLATFORMIO_CORE_DIR=~/.platformio-envs/<core>` to the core for that env (see `projects/MANIFEST.json`) and copy the cached `libdeps` into `.pio/libdeps/`. |
| Ember can't reach Los Gatos | Run `los-gatos-admin-steps.ps1` (OpenSSH Server), then add the target (section 5). |

## 19. Honest limits

- **Radios:**
  - The AT-D868UV is not in CHIRP.
  - The TK-271 has no driver.
  - The IC-7300 is a read-only snapshot.
  - The UV-9R Plus is untested on your radio.
- **Printer:**
  - CC2 control is built from the open-source protocol and tested against a fake printer, not your printer yet.
  - It needs LAN-only mode.
  - The upload sends the access code over plain HTTP on your home network; the printer offers nothing better.
- **Parts library:**
  - No openly licensed spare parts made specifically for the CC2 were found.
  - ELEGOO's maintenance pages have no open license, so they aren't copied.
  - Radio mounts are few (8); GitHub has little for Baofeng and AnyTone.
- **Windows build hosts** install PlatformIO and CHIRP online only.
- **Other computers:** Ember can only reach them after you add them and their keys (section 5).
- **Tailscale** is not installed yet.
- **Off-grid project work:** no PRs, issues, Actions or cloud agents offline; iOS needs a Mac; online AI features in BlackCat and Face-AI won't work; the Outpost 2.0 board files are untested on hardware (section 13).
- **Small-model helpers:** the code index reads the mirror, not the build host, so unpushed work isn't in it; Small steps adds one planning call; summaries can drop detail. The speed numbers are one sample.
- **AMSAT pack:** TLEs go stale in days; SatNOGS status is community data. The phased-array and radar guides are reference notes; check Part 97 before transmitting.
- **The AI model** has a small memory (4k), so long jobs work best in short steps. Check anything safety-critical yourself.

## 20. For developers

```bash
EMBER_DEV=1 ./install.sh
.venv/bin/python -m pytest -q
.venv/bin/ruff check . && .venv/bin/mypy ember coldboot/cbmodels.py coldboot/projects_cache.py
.venv/bin/bandit -q -c pyproject.toml -r ember coldboot scripts
.venv/bin/shellcheck -x coldboot.sh install.sh bin/ember coldboot/buildhost/install-buildhost.sh scripts/*.sh
.venv/bin/pip-audit -r requirements.txt
.venv/bin/python scripts/make_preview.py ~/Desktop/ember-preview
```

**Layout**
- `ember/`: the app.
  - `app.py`: web routes
  - `routes_exec.py`: targets, credentials, audit
  - `routes_devices.py`: Workshop API
  - `agent.py`: the tool-calling chat
  - `classifier.py`: risk rules
  - `runner.py`: local and SSH
  - `roles.py`
  - `radio.py`, `radio_helper.py`, `radio_kb.py`
  - `printer.py`
  - `parts.py`
  - `projects.py`, `dev_kb.py`
  - `budget.py`, `context.py` (context budget, rolling summary), `code_index.py`, `notes.py`, `build_errors.py`, `patching.py`, `bench.py`
  - `static/`: the web page, including `workshop.js`
- `coldboot.sh` and `coldboot/` (pins, models, `buildhost/` installers, `parts-scad/`, `parts-seed.json`, `projects-seed.json`, `projects_cache.py`, `outpost2-template/`)
- `docs/amsat/`: Ember's satellite and phased-array guides (indexed into the radio library)
- `scripts/`: previews, radio (with AMSAT) and developer library fetch, parts import, mirror import/sync, `windows/` scripts for Los Gatos
- `tests/`
- `docs/RECOVERY-PLAN.md`

Requirements are pinned with hashes; regenerate them with `uv pip compile requirements.in --python-version 3.12 --generate-hashes -o requirements.txt`.

## 21. Version history

| Version | What changed |
|---|---|
| 0.1.0 | Offline chat: logins, history, model picker, Nomad knowledge base |
| 0.2.0 | Commands: targets, encrypted credentials, risk checks, confirm cards, audit log |
| 0.3.0 | ColdBoot: rebuild, check, backup/restore, offline cache |
| 0.3.1 | Full README and recovery plan |
| 0.4.0 | Workshop refocus: host roles, CHIRP radio programming, radio library, build hosts, CC2 printer and slicing, parts library (200 parts, 214 guides), fix mode |
| 0.5.0 | Off-grid project work: Projects view, repo mirrors and offline git, Outpost PlatformIO and package caches, developer reference (ESP32/LoRa, Heltec V4, AX.25/X.25), Outpost 2.0 (Heltec V4-R8) starter, general chat documented |
| 0.6.0 | Small-model helpers: context budget and indicator, code index, project notes, small-step mode, rolling summary, trimmed build errors, edit-by-diff; `qwen3.5-9b-8k` with a measured speed sample and Models page; AMSAT pack (satellites, TLEs, Doppler, rig/rotator control, phased arrays, radar tracking, handoff, radar/ADS-B-cued steering, aircraft scatter and contests, NEC-modeled 2 m/70 cm Yagis, mmWave radar cueing with `mmwave_cue.py` and a radar/DF comparison) |
