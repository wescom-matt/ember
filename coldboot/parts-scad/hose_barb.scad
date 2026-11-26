// Straight hose barb reducer. CC0. id_a/id_b = hose inside diameters (mm). wall = bore wall.
id_a = 10; id_b = 13; len_each = 22; wall = 1.6;
$fn = 72;
module barb(id, l) {
  bore = min(id_a, id_b) - 2 * wall - 1;
  for (z = [0 : l / 3 : l - l / 3]) translate([0, 0, z]) cylinder(d1 = id * 1.12, d2 = id * 0.92, h = l / 3);
}
difference() {
  union() {
    barb(id_a, len_each);
    translate([0, 0, len_each]) cylinder(d = max(id_a, id_b) + 4, h = 4);
    translate([0, 0, 2 * len_each + 4]) mirror([0, 0, 1]) barb(id_b, len_each);
  }
  translate([0, 0, -1]) cylinder(d = min(id_a, id_b) - 2 * wall, h = 2 * len_each + 10);
}
