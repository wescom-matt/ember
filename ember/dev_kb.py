"""Offline developer reference: ESP32-S3, Arduino-ESP32, ESP-IDF, RadioLib, LoRaWAN,
SX1262 and Heltec V3 documents, searchable with SQLite FTS5 like the radio KB.

Built by scripts/fetch_dev_kb.py while online into data_dir/dev-kb/ (raw files,
SOURCES.json with URL, date, sha256 and terms, and index.db). Only documents that
are free to download are used, kept as a personal offline copy, never re-published.
"""

from __future__ import annotations

from pathlib import Path

from ember.radio_kb import RadioKB

ESPRESSIF = "https://www.espressif.com/sites/default/files/documentation"
HELTEC = "https://resource.heltec.cn/download/WiFi_LoRa_32_V3"
FREE = "free download from the publisher; personal offline copy"

# kind: pdf (indexed per page), html, git-docs (sparse git checkout of a docs folder; text/PDF indexed),
# tar-headers (source tarball, C/C++ headers with their API comments indexed), file (kept, not indexed).
DEV_SOURCES: list[dict[str, str]] = [
    {
        "id": "esp32s3-datasheet",
        "kind": "pdf",
        "title": "ESP32-S3 Series Datasheet (Espressif)",
        "url": f"{ESPRESSIF}/esp32-s3_datasheet_en.pdf",
        "terms": FREE,
    },
    {
        "id": "esp32s3-trm",
        "kind": "pdf",
        "title": "ESP32-S3 Technical Reference Manual (Espressif)",
        "url": f"{ESPRESSIF}/esp32-s3_technical_reference_manual_en.pdf",
        "terms": FREE,
    },
    {
        "id": "esp-idf-4.4",
        "kind": "pdf",
        "title": "ESP-IDF v4.4.8 Programming Guide for ESP32-S3",
        "url": "https://docs.espressif.com/projects/esp-idf/en/v4.4.8/esp32s3/esp-idf-en-v4.4.8-esp32s3.pdf",
        "terms": "Apache-2.0 (ESP-IDF docs)",
    },
    {
        "id": "esp-idf-5.5",
        "kind": "git-docs",
        "title": "ESP-IDF v5.5.5 docs (English source)",
        "url": "https://github.com/espressif/esp-idf",
        "ref": "v5.5.5",
        "path": "docs/en",
        "terms": "Apache-2.0 (ESP-IDF docs)",
    },
    {
        "id": "arduino-esp32-2",
        "kind": "git-docs",
        "title": "Arduino-ESP32 2.0.17 docs",
        "url": "https://github.com/espressif/arduino-esp32",
        "ref": "2.0.17",
        "path": "docs",
        "terms": "LGPL-2.1 repository (docs from the arduino-esp32 repo)",
    },
    {
        "id": "arduino-esp32-3",
        "kind": "git-docs",
        "title": "Arduino-ESP32 3.3.12 docs",
        "url": "https://github.com/espressif/arduino-esp32",
        "ref": "3.3.12",
        "path": "docs",
        "terms": "LGPL-2.1 repository (docs from the arduino-esp32 repo)",
    },
    {
        "id": "radiolib",
        "kind": "tar-headers",
        "title": "RadioLib 7.8.1 API (header comments)",
        "url": "https://codeload.github.com/jgromes/RadioLib/tar.gz/refs/tags/7.8.1",
        "terms": "MIT",
    },
    {
        "id": "lorawan-l2-1.0.4",
        "kind": "pdf",
        "title": "LoRaWAN L2 1.0.4 Specification (TS001-1.0.4)",
        "url": "https://lora-alliance.org/wp-content/uploads/2021/11/LoRaWAN-Link-Layer-Specification-v1.0.4.pdf",
        "terms": FREE,
    },
    {
        "id": "lorawan-rp002-1.0.3",
        "kind": "pdf",
        "title": "LoRaWAN Regional Parameters RP002-1.0.3",
        "url": "https://lora-alliance.org/wp-content/uploads/2021/05/RP002-1.0.3-FINAL-1.pdf",
        "terms": FREE + " (1.0.4 is behind a sign-up form, so 1.0.3 is used)",
    },
    {
        "id": "sx1262-datasheet",
        "kind": "pdf",
        "title": "Semtech SX1261/2 Datasheet",
        "url": "https://cdn.sparkfun.com/assets/6/b/5/1/4/SX1262_datasheet.pdf",
        "terms": FREE + " (Semtech document, SparkFun mirror)",
    },
    {
        "id": "heltec-v3",
        "kind": "pdf",
        "title": "Heltec WiFi LoRa 32 V3 (Rev 1.1) pin definitions",
        "url": f"{HELTEC}/HTIT-WB32LA_V3(Rev1.1).pdf",
        "terms": FREE,
    },
    {
        "id": "heltec-v3.2",
        "kind": "pdf",
        "title": "Heltec WiFi LoRa 32 V3.2 pin definitions",
        "url": f"{HELTEC}/HTIT-WB32LA_V3.2.pdf",
        "terms": FREE,
    },
    {
        "id": "heltec-v3-schematic",
        "kind": "pdf",
        "title": "Heltec WiFi LoRa 32 V3 schematic",
        "url": f"{HELTEC}/HTIT-WB32LA(F)_V3_Schematic_Diagram.pdf",
        "terms": FREE,
    },
    {
        "id": "heltec-v4r8",
        "kind": "pdf",
        "title": "Heltec WiFi LoRa 32 V4-R8 datasheet (pins, power, RF)",
        "url": "https://resource.heltec.cn/download/WiFi_LoRa_32_V4-R8/datasheet/WiFi_LoRa_32_V4R8.pdf",
        "terms": FREE,
    },
    {
        "id": "heltec-v4r8-schematic",
        "kind": "pdf",
        "title": "Heltec WiFi LoRa 32 V4-R8 schematic (HTIT-WBR8H V4.3.2)",
        "url": "https://resource.heltec.cn/download/WiFi_LoRa_32_V4-R8/Schematic/HTIT-WBR8H_V4.3.2.pdf",
        "terms": FREE,
    },
    {
        "id": "heltec-v4r8-pinout",
        "kind": "file",
        "title": "Heltec WiFi LoRa 32 V4-R8 pin map image",
        "url": "https://resource.heltec.cn/download/WiFi_LoRa_32_V4-R8/pinmap/lora%20_32_v4-R8%20pinmap.png",
        "terms": FREE,
    },
    {
        "id": "heltec-v4",
        "kind": "pdf",
        "title": "Heltec WiFi LoRa 32 V4 (R2) datasheet",
        "url": "https://resource.heltec.cn/download/WiFi_LoRa_32_V4/datasheet/WiFi_LoRa_32_V4.2.0.pdf",
        "terms": FREE,
    },
    {
        "id": "heltec-v3-pinout",
        "kind": "file",
        "title": "Heltec WiFi LoRa 32 V3 pinout image",
        "url": f"{HELTEC}/HTIT-WB32LA(F)_V3.png",
        "terms": FREE,
    },
]

# Packet radio: AX.25 / KISS / APRS / Direwolf / Linux AX.25, and X.25.
PACKET_SOURCES: list[dict[str, str]] = [
    {
        "id": "ax25-2.2",
        "kind": "pdf",
        "title": "AX.25 Link Access Protocol for Amateur Packet Radio v2.2 (TAPR, July 1998)",
        "url": "https://www.ax25.net/AX25.2.2-Jul%2098-2.pdf",
        "terms": FREE + " (TAPR document; ax25.net copy, tapr.org link moved)",
    },
    {
        "id": "kiss",
        "kind": "html",
        "title": "The KISS TNC protocol (Chepponis & Karn, 1987)",
        "url": "https://www.ka9q.net/papers/kiss.html",
        "terms": FREE,
    },
    {
        "id": "aprs101",
        "kind": "pdf",
        "title": "APRS Protocol Reference 1.0.1 (APRS101)",
        "url": "https://raw.githubusercontent.com/wb2osz/aprsspec/main/APRS101.pdf",
        "terms": FREE + " (wb2osz/aprsspec copy)",
    },
    {
        "id": "direwolf-docs",
        "kind": "git-docs",
        "title": "Dire Wolf documentation (User Guide, APRS, KISS, FX.25)",
        "url": "https://github.com/wb2osz/direwolf",
        "ref": "master",
        "path": "doc",
        "suffixes": ".pdf .md",
        "terms": "GPL-2.0 (Dire Wolf repository)",
    },
    {
        "id": "linux-ax25-howto",
        "kind": "pdf",
        "title": "Linux AX.25 HOWTO (The Linux Documentation Project)",
        "url": "https://tldp.org/HOWTO/pdf/AX25-HOWTO.pdf",
        "terms": "LDP license (free to copy and redistribute)",
    },
    {
        "id": "linuxax25",
        "kind": "git-docs",
        "title": "Linux AX.25 tools, apps and library (man pages, READMEs)",
        "url": "https://github.com/ve7fet/linuxax25",
        "ref": "master",
        "path": "",
        "suffixes": ".1 .4 .5 .8 .md .txt README",
        "terms": "GPL/LGPL (linuxax25 repository)",
    },
    {
        "id": "x25-itu",
        "kind": "pdf",
        "title": "ITU-T Recommendation X.25 (10/96)",
        "url": "https://www.itu.int/rec/dologin_pub.asp?lang=e&id=T-REC-X.25-199610-I!!PDF-E&type=items",
        "terms": FREE + " (ITU-T Recommendations are free to download)",
    },
    {
        "id": "wiki-x25",
        "kind": "html",
        "title": "Wikipedia - X.25",
        "url": "https://en.wikipedia.org/wiki/X.25",
        "terms": "CC BY-SA 4.0",
    },
    {
        "id": "wiki-ax25",
        "kind": "html",
        "title": "Wikipedia - AX.25",
        "url": "https://en.wikipedia.org/wiki/AX.25",
        "terms": "CC BY-SA 4.0",
    },
]

DEV_SOURCES += PACKET_SOURCES

# Optional (--with-api-docs): kept for browsing, not indexed.
API_DOCS: list[dict[str, str]] = [
    {
        "id": "flutter-docset",
        "kind": "file",
        "title": "Flutter API docs (Dash docset)",
        "url": "https://api.flutter.dev/offline/flutter.docset.tar.gz",
        "terms": "BSD-3-Clause (Flutter)",
    },
]


def kb_dir(data_dir: Path) -> Path:
    return data_dir / "dev-kb"


class DevKB(RadioKB):
    id = "dev"
    label = "Developer reference (offline)"
    description = "ESP32-S3, Arduino-ESP32, ESP-IDF, RadioLib, LoRaWAN, SX1262, Heltec V3/V4, AX.25/APRS, X.25"
    build_hint = "dev knowledge base is not built yet (run scripts/fetch_dev_kb.py while online)"

    def __init__(self, data_dir: Path) -> None:
        super().__init__(data_dir)
        self.path = kb_dir(data_dir) / "index.db"
