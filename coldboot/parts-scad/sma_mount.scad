// Antenna bracket: L plate with a 6.6 mm hole for an SMA bulkhead (or 16 mm for SO-239) and
// slots for hose clamps / zip ties around a mast up to ~40 mm. CC0.
hole = 6.6; t = 4; w = 30;
$fn = 48;
difference() {
  union() { cube([w, 40, t]); cube([w, t, 35]); }
  translate([w / 2, 24, -1]) cylinder(d = hole, h = t + 2);
  for (z = [10, 25]) translate([-1, -1, z]) cube([w + 2, t + 2, 0]);
  for (z = [9, 24]) translate([w / 2 - 7, -1, z]) cube([14, t + 2, 4]);  // strap slots
}
