// Keyhole microphone hanger for mobile/base rigs (fits mics with a rear hanger button). CC0.
// button = head diameter of the mic's hanger button, neck = its neck diameter, check your mic.
button = 12; neck = 6.5; plate = [40, 60, 4]; screw = 4.2;
$fn = 48;
difference() {
  union() {
    translate([-plate[0] / 2, 0, 0]) cube(plate);
    translate([-plate[0] / 2, plate[1] - 26, 0]) cube([plate[0], 26, plate[2] + 6]);
  }
  // keyhole: drop the button in the big hole, slide down into the slot
  translate([0, plate[1] - 8, -1]) cylinder(d = button + 1, h = 20);
  hull() for (y = [plate[1] - 8, plate[1] - 22]) translate([0, y, -1]) cylinder(d = neck + 0.6, h = 20);
  hull() for (y = [plate[1] - 8, plate[1] - 22]) translate([0, y, plate[2]]) cylinder(d = button + 1, h = 3.5);
  for (y = [10, 24]) translate([0, y, -1]) cylinder(d = screw, h = 10);
}
