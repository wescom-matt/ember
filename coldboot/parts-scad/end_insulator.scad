// Dog-bone antenna end insulator. CC0. Print in ASA/PETG, 100% infill for wire antennas.
len = 70; wid = 18; thick = 8; hole = 6;
$fn = 48;
difference() {
  hull() for (x = [-len / 2, len / 2]) translate([x, 0, 0]) cylinder(d = wid, h = thick);
  for (x = [-len / 2, len / 2]) translate([x, 0, -1]) cylinder(d = hole, h = thick + 2);
  translate([-len / 2 + hole + 6, -wid, thick - 1.5]) cube([len - 2 * hole - 12, 2 * wid, 2]);
}
