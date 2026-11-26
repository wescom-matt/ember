// Barbed drip-irrigation fittings for 1/4" (4 mm ID) tubing: coupler, elbow, tee, cross. CC0.
// type = "coupler" | "elbow" | "tee" | "cross". Low pressure garden drip only.
type = "tee"; id = 4; barb_len = 10;
$fn = 40;
module barb() {
  difference() {
    union() for (z = [0, barb_len / 3, 2 * barb_len / 3]) translate([0, 0, z]) cylinder(d1 = id * 1.25, d2 = id * 0.95, h = barb_len / 3);
    translate([0, 0, -1]) cylinder(d = id * 0.5, h = barb_len + 2);
  }
}
dirs = type == "coupler" ? [0, 180] : type == "elbow" ? [0, 90] : type == "tee" ? [0, 90, 180] : [0, 90, 180, 270];
difference() {
  union() {
    sphere(d = id * 1.9);
    for (a = dirs) rotate([0, 90, a]) translate([0, 0, id * 0.6]) barb();
  }
  for (a = dirs) rotate([0, 90, a]) cylinder(d = id * 0.5, h = barb_len + id);
}
