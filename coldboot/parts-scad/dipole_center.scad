// Dipole center insulator with SO-239 flange mount. CC0.
// Wire eyes at both ends, hanging hole on top, zip-tie slots for coax strain relief.
// SO-239 square flange: 25.4 mm, holes 18.3 mm apart, body hole 16 mm (measure yours).
len = 90; wid = 34; thick = 8; so239_hole = 16; so239_pitch = 18.3; screw = 3.4; eye = 6;
$fn = 64;
difference() {
  hull() for (x = [-len / 2 + wid / 4, len / 2 - wid / 4]) translate([x, 0, 0]) cylinder(d = wid / 2, h = thick);
  translate([0, 0, -1]) cylinder(d = so239_hole, h = thick + 2);
}
difference() {
  translate([-wid / 2, -wid / 2, 0]) cube([wid, wid, thick]);
  translate([0, 0, -1]) cylinder(d = so239_hole, h = thick + 2);
  for (x = [-1, 1], y = [-1, 1]) translate([x * so239_pitch / 2, y * so239_pitch / 2, -1]) cylinder(d = screw, h = thick + 2);
}
// wire eyes
for (s = [-1, 1]) difference() {
  translate([s * (len / 2 + eye / 2), 0, 0]) cylinder(d = eye + 8, h = thick);
  translate([s * (len / 2 + eye / 2), 0, -1]) cylinder(d = eye, h = thick + 2);
}
// hanging tab
difference() {
  translate([-6, wid / 2 - 1, 0]) cube([12, 14, thick]);
  translate([0, wid / 2 + 8, -1]) cylinder(d = eye, h = thick + 2);
}
