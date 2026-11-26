// Mast / pipe saddle clamp half (print two, bolt together, or bolt one to a wall). CC0.
pipe = 32; wid = 25; wall = 5; bolt = 6.5;
$fn = 96;
ear = bolt + 10;
difference() {
  union() {
    cylinder(d = pipe + 2 * wall, h = wid);
    translate([-(pipe / 2 + wall + ear), -wall / 2 - 2, 0]) cube([pipe + 2 * wall + 2 * ear, wall + 4, wid]);
  }
  translate([0, 0, -1]) cylinder(d = pipe + 0.6, h = wid + 2);
  translate([-pipe, 0, -1]) cube([2 * pipe, pipe, wid + 2]);
  for (s = [-1, 1]) translate([s * (pipe / 2 + wall + ear / 2), 10, wid / 2]) rotate([90, 0, 0]) cylinder(d = bolt, h = 30);
}
