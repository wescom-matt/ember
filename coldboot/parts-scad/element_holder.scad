// Yagi / J-pole element holder: clamps to a boom and holds an element rod at 90 deg. CC0.
// boom: square or round boom size; element: rod/tube diameter (e.g. 3.2 brazing rod, 6.35 tube).
boom = 20; round_boom = false; element = 4.8; len = 40; screw = 3.4;
$fn = 64;
h = boom + 10;
difference() {
  translate([-len / 2, -h / 2, 0]) cube([len, h, boom / 2 + 10]);
  if (round_boom) translate([-len / 2 - 1, 0, 0]) rotate([0, 90, 0]) cylinder(d = boom + 0.5, h = len + 2);
  else translate([-len / 2 - 1, -(boom + 0.5) / 2, -1]) cube([len + 2, boom + 0.5, boom / 2 + 1]);
  translate([0, -h, boom / 2 + 5]) rotate([-90, 0, 0]) cylinder(d = element + 0.3, h = 2 * h);
  for (x = [-len / 2 + 6, len / 2 - 6]) translate([x, 0, -1]) cylinder(d = screw, h = boom + 20);
  translate([0, 0, boom / 2 + 1]) cylinder(d = screw, h = 20);
}
