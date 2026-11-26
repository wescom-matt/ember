// Knurled control knob. CC0 (public domain), made for Ember's parts library.
// D-shaft: shaft_d with a flat at flat_d (e.g. 6 mm shaft, 4.5 mm across the flat). flat_d = 0 -> round + M3 set screw.
dia = 25; height = 15; shaft_d = 6.2; flat_d = 4.7; depth = 11; ridges = 24;
$fn = 64;
difference() {
  union() {
    cylinder(d = dia, h = height);
    for (i = [0 : ridges - 1]) rotate(i * 360 / ridges) translate([dia / 2, 0, 0]) cylinder(d = 2, h = height, $fn = 12);
  }
  translate([0, 0, -0.01]) intersection() {
    cylinder(d = shaft_d, h = depth);
    if (flat_d > 0) translate([-shaft_d / 2, -shaft_d / 2, 0]) cube([shaft_d, flat_d, depth]);
  }
  if (flat_d == 0) translate([0, 0, depth / 2]) rotate([0, 90, 0]) cylinder(d = 2.6, h = dia);
  translate([0, dia / 2 - 3, height - 0.8]) cylinder(d = 1.6, h = 1);  // pointer dot
}
