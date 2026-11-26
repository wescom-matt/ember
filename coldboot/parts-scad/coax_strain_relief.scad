// Coax strain relief clip: screw-down saddle with zip-tie slots. CC0.
// coax: RG-58 ~5, RG-8X ~6.1, LMR-400/RG-213 ~10.3 mm.
coax = 6.1; len = 30; screw = 4.2;
$fn = 64;
w = coax + 8; base = 3;
difference() {
  union() {
    translate([-len / 2, -w / 2 - 9, 0]) cube([len, w + 18, base]);
    translate([-len / 2, 0, base + coax / 2]) rotate([0, 90, 0]) cylinder(d = coax + 5, h = len);
    translate([-len / 2, -(coax + 5) / 2, 0]) cube([len, coax + 5, base + coax / 2]);
  }
  translate([-len / 2 - 1, 0, base + coax / 2]) rotate([0, 90, 0]) cylinder(d = coax + 0.4, h = len + 2);
  translate([-len / 2 - 1, -coax * 0.35, base + coax / 2]) cube([len + 2, coax * 0.7, coax]);
  for (y = [-w / 2 - 4.5, w / 2 + 4.5]) translate([0, y, -1]) cylinder(d = screw, h = base + 2);
  for (x = [-len / 4, len / 4]) translate([x - 2, -w, base + coax / 2 - 1]) cube([4, 2 * w, 2]);
}
