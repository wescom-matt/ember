// 90-degree L bracket with gusset. CC0. size = leg length, hole for M4 (4.4 mm).
size = 40; width = 20; t = 4; hole = 4.4;
$fn = 40;
difference() {
  union() {
    cube([size, width, t]);
    cube([t, width, size]);
    translate([0, width / 2 - t / 2, 0]) rotate([90, 0, 0]) translate([0, 0, -t])
      linear_extrude(t) polygon([[t, t], [size * 0.6, t], [t, size * 0.6]]);
  }
  for (p = [0.45, 0.8]) {
    translate([size * p, width / 2, -1]) cylinder(d = hole, h = t + 2);
    translate([-1, width / 2, size * p]) rotate([0, 90, 0]) cylinder(d = hole, h = t + 2);
  }
}
