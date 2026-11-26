// Desk rig tilt wedge (e.g. IC-7300 or a mobile rig on a desk): raises the front. CC0.
// Print two; set foot_d to your rig's rubber foot so it sits in the pocket.
len = 60; wid = 30; low = 6; high = 22; foot_d = 16; foot_h = 3;
$fn = 64;
difference() {
  rotate([90, 0, 0]) linear_extrude(wid) polygon([[0, 0], [len, 0], [len, low], [0, high]]);
  translate([len * 0.3, -wid / 2, high - (high - low) * 0.3 - foot_h]) rotate([0, -atan((high - low) / len), 0]) cylinder(d = foot_d + 1, h = 10);
}
