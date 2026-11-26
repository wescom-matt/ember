// Two-part case for common ESP32 / LoRa boards (base + snap lid). CC0.
// Board sizes (L x W, mm): ESP32 DevKit V1 30-pin 51.5x28.5, 38-pin 55x28,
// Heltec WiFi LoRa 32 V3 50.2x25.5, TTGO/LILYGO LoRa32 V2.1 61x26, Wemos D1 mini 34.2x25.6.
// The USB opening is on the -X end. part = "base" | "lid" | "both". antenna = SMA hole on +X end.
board = [51.5, 28.5]; board_h = 1.6; under = 4; above = 12; wall = 2; usb = [12, 7]; antenna = 0; part = "both";
$fn = 40;
in = [board[0] + 1, board[1] + 1, under + board_h + above];
module base() {
  difference() {
    translate([-wall, -wall, -wall]) cube([in[0] + 2 * wall, in[1] + 2 * wall, in[2] + wall]);
    cube([in[0], in[1], in[2] + 1]);
    translate([-wall - 1, in[1] / 2 - usb[0] / 2, under - 1]) cube([wall + 2, usb[0], usb[1]]);
    if (antenna > 0) translate([in[0] - 1, in[1] / 2, under + board_h + 6]) rotate([0, 90, 0]) cylinder(d = antenna, h = wall + 2);
    for (x = [in[0] * 0.3, in[0] * 0.7]) translate([x, -wall - 1, in[2] - 2]) cube([6, in[1] + 2 * wall + 2, 1.2]);
  }
  for (p = [[1.5, 1.5], [in[0] - 1.5, 1.5], [1.5, in[1] - 1.5], [in[0] - 1.5, in[1] - 1.5]]) translate([p[0], p[1], 0]) cylinder(d = 2.5, h = under);
}
module lid() {
  translate([-wall, -wall, 0]) cube([in[0] + 2 * wall, in[1] + 2 * wall, wall]);
  difference() {
    translate([0.2, 0.2, wall]) cube([in[0] - 0.4, in[1] - 0.4, 4]);
    translate([1.6, 1.6, wall]) cube([in[0] - 3.2, in[1] - 3.2, 5]);
  }
  for (x = [in[0] * 0.3, in[0] * 0.7]) translate([x + 0.5, -0.4, wall + 1.6]) cube([5, in[1] + 0.8, 0.8]);
}
if (part == "base" || part == "both") base();
if (part == "lid" || part == "both") translate([0, in[1] + 3 * wall + 6, 0]) lid();
