// Handheld radio (HT) cradle for wall, desk or vehicle. CC0.
// Approximate body sizes with battery (MEASURE YOURS, add 1 mm):
//   Baofeng UV-5R / BF-F8+: 58 x 32   Baofeng UV-9R Plus: 58 x 37   AnyTone AT-D868UV: 62 x 36
width = 59; depth = 33; height = 55; wall = 3; screw = 4.2;
$fn = 48;
difference() {
  translate([-wall, -wall, 0]) cube([width + 2 * wall, depth + 2 * wall, height]);
  translate([0, 0, wall]) cube([width, depth, height]);
  translate([width * 0.2, -wall - 1, height * 0.45]) cube([width * 0.6, wall + 2, height]);   // front window (PTT side free)
  translate([width / 2 - 10, depth / 2 - 6, -1]) cube([20, 12, wall + 2]);                   // charge-contact / drain hole
  for (x = [width * 0.25, width * 0.75]) translate([x, depth + wall + 1, height * 0.6]) rotate([90, 0, 0]) cylinder(d = screw, h = wall + 2);
}
