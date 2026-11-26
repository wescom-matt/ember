#!/usr/bin/env python3
"""Read a TI mmWave radar (IWR1843BOOST, IWR6843AOPEVM, D3 RS-6843) and point an antenna.

CC0 / public domain (written for Ember). Reads the UART TLV stream from the
mmWave SDK out-of-box demo (TLV 1 point cloud) or the Radar Toolbox tracking
demos (TLV 1010 target list, TLV 1020 compressed point cloud), turns detections
into azimuth/elevation for your antenna, smooths them, predicts ahead for latency
and sends `P az el` to Hamlib rotctld (or prints JSON for an array pointer).

  python3 mmwave_cue.py --data /dev/ttyUSB1 --yaw 135 --pitch 10 --rotctld 127.0.0.1:4533
  python3 mmwave_cue.py --file capture.bin --yaw 0      # replay a saved capture, print JSON

Needs pyserial only for live ports (`pip install pyserial`). Send the .cfg file on
the CLI port first (TI visualizer, or --cli /dev/ttyUSB0 --cfg profile.cfg).
"""

from __future__ import annotations

import argparse
import json
import math
import socket
import struct
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import BinaryIO

MAGIC = bytes([2, 1, 4, 3, 6, 5, 8, 7])
HEADER = struct.Struct("<8I")  # version, totalLen, platform, frame, cpuCycles, numObj, numTLVs, subFrame
TLV = struct.Struct("<2I")
POINT = struct.Struct("<4f")  # TLV 1: x, y, z, doppler (sensor frame: x right, y forward, z up)
TARGET = struct.Struct("<I9f16f2f")  # TLV 1010: tid, pos xyz, vel xyz, acc xyz, ec[16], g, confidence
UNITS = struct.Struct("<5f")  # TLV 1020 units: elevation, azimuth, doppler, range, snr
CPOINT = struct.Struct("<2bh2H")  # TLV 1020 point: elevation, azimuth, doppler, range, snr
MAX_FRAME = 65536
MAX_TLVS = 32


@dataclass
class Det:
    x: float  # metres, sensor frame
    y: float
    z: float
    v: float = 0.0  # radial m/s (points) or speed (tracks)
    tid: int = -1  # track id, -1 for raw points


def frames(stream: BinaryIO) -> Iterator[tuple[int, bytes]]:
    """Yield (frame_number, tlv_bytes) for each complete frame."""
    buf = b""
    while True:
        chunk = stream.read(4096)
        if not chunk:
            return
        buf += chunk
        for _ in range(64):  # bounded work per read
            start = buf.find(MAGIC)
            if start < 0:
                buf = buf[-7:]
                break
            if len(buf) < start + 8 + HEADER.size:
                buf = buf[start:]
                break
            hdr = HEADER.unpack_from(buf, start + 8)
            total = hdr[1]
            if total < 8 + HEADER.size or total > MAX_FRAME:
                buf = buf[start + 8 :]
                continue
            if len(buf) < start + total:
                buf = buf[start:]
                break
            yield hdr[3], buf[start + 8 + HEADER.size : start + total]
            buf = buf[start + total :]


def parse_tlvs(body: bytes) -> list[Det]:
    """Tracks (TLV 1010) win over points; points come from TLV 1 or TLV 1020."""
    points: list[Det] = []
    tracks: list[Det] = []
    off = 0
    for _ in range(MAX_TLVS):
        if off + TLV.size > len(body):
            break
        kind, length = TLV.unpack_from(body, off)
        off += TLV.size
        data = body[off : off + length]
        off += length
        if kind == 1:
            for i in range(len(data) // POINT.size):
                x, y, z, v = POINT.unpack_from(data, i * POINT.size)
                points.append(Det(x, y, z, v))
        elif kind == 1010:
            for i in range(len(data) // TARGET.size):
                t = TARGET.unpack_from(data, i * TARGET.size)
                tracks.append(Det(t[1], t[2], t[3], math.hypot(t[4], t[5], t[6]), int(t[0])))
        elif kind == 1020 and len(data) >= UNITS.size:
            eu, au, du, ru, _su = UNITS.unpack_from(data, 0)
            for i in range((len(data) - UNITS.size) // CPOINT.size):
                e, a, d, r, _s = CPOINT.unpack_from(data, UNITS.size + i * CPOINT.size)
                el, az, rng = e * eu, a * au, r * ru
                points.append(
                    Det(
                        rng * math.cos(el) * math.sin(az), rng * math.cos(el) * math.cos(az), rng * math.sin(el), d * du
                    )
                )
    return tracks or points


def to_enu(
    d: Det, yaw: float, pitch: float, roll: float, offset: tuple[float, float, float]
) -> tuple[float, float, float]:
    """Sensor frame -> east/north/up at the antenna.

    yaw = compass bearing of the radar boresight (deg, clockwise from true north),
    pitch = boresight tilt up (deg), roll = clockwise roll seen from behind (deg),
    offset = radar position minus antenna position in metres (east, north, up).
    """
    r, p, h = (math.radians(a) for a in (roll, pitch, yaw))
    x = d.x * math.cos(r) + d.z * math.sin(r)  # roll about the boresight (y)
    z = -d.x * math.sin(r) + d.z * math.cos(r)
    y = d.y * math.cos(p) - z * math.sin(p)  # pitch about x
    up = d.y * math.sin(p) + z * math.cos(p)
    east = x * math.cos(h) + y * math.sin(h)  # yaw about up
    north = -x * math.sin(h) + y * math.cos(h)
    return east + offset[0], north + offset[1], up + offset[2]


def az_el(east: float, north: float, up: float) -> tuple[float, float, float]:
    az = math.degrees(math.atan2(east, north)) % 360.0
    el = math.degrees(math.atan2(up, math.hypot(east, north)))
    return az, el, math.sqrt(east * east + north * north + up * up)


class AlphaBeta:
    """Alpha-beta filter on az/el (handles the 359->0 wrap) with latency prediction."""

    def __init__(self, alpha: float = 0.5, beta: float = 0.1) -> None:
        self.alpha, self.beta = alpha, beta
        self.az = self.el = self.daz = self.del_ = 0.0
        self.t = -1.0

    def update(self, az: float, el: float, t: float) -> None:
        if self.t < 0:
            self.az, self.el, self.t = az, el, t
            return
        dt = max(t - self.t, 1e-3)
        self.t = t
        paz, pel = self.az + self.daz * dt, self.el + self.del_ * dt
        raz = (az - paz + 180.0) % 360.0 - 180.0
        rel = el - pel
        self.az, self.el = (paz + self.alpha * raz) % 360.0, pel + self.alpha * rel
        self.daz += self.beta * raz / dt
        self.del_ += self.beta * rel / dt

    def predict(self, ahead: float) -> tuple[float, float]:
        return (self.az + self.daz * ahead) % 360.0, max(-5.0, min(90.0, self.el + self.del_ * ahead))


class Rotctld:
    """Minimal Hamlib rotctld client with a deadband so the rotator isn't hammered."""

    def __init__(self, host: str, port: int, deadband: float = 2.0) -> None:
        self.sock = socket.create_connection((host, port), timeout=5)
        self.deadband = deadband
        self.last: tuple[float, float] | None = None

    def point(self, az: float, el: float) -> bool:
        el = max(0.0, el)
        if (
            self.last
            and abs((az - self.last[0] + 180) % 360 - 180) < self.deadband
            and abs(el - self.last[1]) < self.deadband
        ):
            return False
        self.sock.sendall(f"P {az:.1f} {el:.1f}\n".encode())
        self.sock.recv(64)  # "RPRT 0"
        self.last = (az, el)
        return True


def pick(dets: list[Det], min_range: float, max_range: float) -> Det | None:
    """Nearest track, else the strongest-looking moving point (largest |doppler|)."""
    ok = [d for d in dets if min_range <= math.sqrt(d.x * d.x + d.y * d.y + d.z * d.z) <= max_range]
    if not ok:
        return None
    tracks = [d for d in ok if d.tid >= 0]
    if tracks:
        return min(tracks, key=lambda d: d.x * d.x + d.y * d.y + d.z * d.z)
    return max(ok, key=lambda d: abs(d.v))


def send_cfg(port: str, cfg: str) -> None:
    import serial  # pyserial, only for live use

    with serial.Serial(port, 115200, timeout=1) as cli, open(cfg, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("%"):
                cli.write((line + "\n").encode())
                time.sleep(0.05)
                cli.read(256)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--data", help="data UART (921600 baud), e.g. /dev/ttyUSB1 or COM5")
    src.add_argument("--file", help="replay a raw capture of the data UART")
    ap.add_argument("--cli", help="CLI UART (115200) to send --cfg on first")
    ap.add_argument("--cfg", help="chirp .cfg file")
    ap.add_argument("--yaw", type=float, default=0.0)
    ap.add_argument("--pitch", type=float, default=0.0)
    ap.add_argument("--roll", type=float, default=0.0)
    ap.add_argument("--offset", default="0,0,0", help="radar minus antenna position, metres east,north,up")
    ap.add_argument("--latency", type=float, default=0.3, help="seconds to predict ahead")
    ap.add_argument("--range", default="2,500", help="min,max metres")
    ap.add_argument("--rotctld", help="host:port, e.g. 127.0.0.1:4533")
    a = ap.parse_args(argv)
    off = tuple(float(v) for v in a.offset.split(","))[:3]
    rmin, rmax = (float(v) for v in a.range.split(","))
    if a.cli and a.cfg:
        send_cfg(a.cli, a.cfg)
    if a.data:
        import serial

        stream: BinaryIO = serial.Serial(a.data, 921600, timeout=1)
    else:
        stream = open(a.file, "rb")  # noqa: SIM115
    rot = None
    if a.rotctld:
        host, port = a.rotctld.rsplit(":", 1)
        rot = Rotctld(host, int(port))
    filt = AlphaBeta()
    for frame, body in frames(stream):
        target = pick(parse_tlvs(body), rmin, rmax)
        if target is None:
            continue
        az, el, rng = az_el(*to_enu(target, a.yaw, a.pitch, a.roll, (off[0], off[1], off[2])))
        filt.update(az, el, time.monotonic())
        paz, pel = filt.predict(a.latency)
        moved = rot.point(paz, pel) if rot else False
        print(
            json.dumps(
                {
                    "frame": frame,
                    "az": round(paz, 1),
                    "el": round(pel, 1),
                    "range_m": round(rng, 1),
                    "track": target.tid,
                    "sent": moved,
                }
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
