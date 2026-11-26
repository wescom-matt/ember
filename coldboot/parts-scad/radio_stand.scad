// Desk stand for a handheld radio, slot width = radio thickness + 1 mm. Leans the radio back 15 deg. CC0.
slot = 36; depth = 60; base_w = 70;
$fn = 40;
difference() {
  hull() { cube([base_w, depth, 4]); translate([0, 10, 0]) cube([base_w, 20, 30]); }
  translate([-1, 14, 6]) rotate([-15, 0, 0]) cube([base_w + 2, slot, 60]);
  translate([base_w / 2 - 8, 5, 6]) cube([16, 40, 40]);  // charger/antenna cable notch
}
