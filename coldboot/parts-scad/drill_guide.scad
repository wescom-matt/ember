// Square drilling guide block: holes 3, 4, 5, 6, 8, 10 mm (print solid, 100% infill). CC0.
sizes = [3, 4, 5, 6, 8, 10]; h = 25;
$fn = 48;
len = 10 + len(sizes) * 15;
difference() {
  cube([len, 20, h]);
  for (i = [0 : len(sizes) - 1]) translate([12 + i * 15, 10, -1]) cylinder(d = sizes[i] + 0.2, h = h + 2);
  for (i = [0 : len(sizes) - 1]) translate([8 + i * 15, 1, h - 0.6]) linear_extrude(1)
    text(str(sizes[i]), size = 4);
}
