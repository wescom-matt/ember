// Belt clip for radios/tools, for belts up to `belt` mm wide; screw to the device with 2x M3. CC0.
belt = 45; t = 3; gap = 5; w = 30;
$fn = 40;
difference() {
  union() {
    cube([w, belt + 10, t]);
    translate([0, 0, 0]) cube([w, t, gap + 2 * t]);
    translate([0, 0, gap + t]) cube([w, belt * 0.8, t]);
    translate([0, belt * 0.8 - t, gap + t - 1.2]) cube([w, t, 1.2 + t]);  // retaining lip
  }
  for (x = [w / 2 - 8, w / 2 + 8]) translate([x, belt * 0.55, -1]) cylinder(d = 3.4, h = t + 2);
}
