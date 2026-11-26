// Screw-down cable clip. CC0. cable = cable diameter (mm); screw hole for M3/#4 wood screw.
cable = 6; width = 10; t = 2;
$fn = 48;
difference() {
  union() {
    translate([-(cable / 2 + t + 8), 0, 0]) cube([cable + 2 * t + 16, width, t]);
    translate([0, width, cable / 2 + t]) rotate([90, 0, 0]) cylinder(r = cable / 2 + t, h = width);
  }
  translate([0, width + 1, cable / 2 + t]) rotate([90, 0, 0]) cylinder(r = cable / 2, h = width + 2);
  translate([-(cable / 2 + t + 8), -1, -10]) cube([cable + 2 * t + 16, width + 2, 10]);
  translate([-(cable / 2 + t + 8), -1, t + 0.01]) cube([8, width + 2, cable + 2 * t]);  // flat feet stay flat
  translate([cable / 2 + t, -1, t + 0.01]) cube([8, width + 2, cable + 2 * t]);
  for (x = [-(cable / 2 + t + 4), cable / 2 + t + 4]) translate([x, width / 2, -1]) cylinder(d = 3.4, h = t + 2);
}
