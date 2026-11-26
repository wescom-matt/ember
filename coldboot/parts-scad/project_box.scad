// Electronics project box with slide-on lid and optional SMA antenna hole. CC0.
// Inner size in mm; check your board (and battery) fit before printing.
inner = [60, 35, 25]; wall = 2; sma = true; usb = [12, 7]; part = "both";  // "box", "lid", "both"
$fn = 48;
o = inner + [2 * wall, 2 * wall, wall];
module box() {
  difference() {
    cube(o);
    translate([wall, wall, wall]) cube(inner + [0, 0, 1]);
    translate([wall / 2, -1, o.z - wall]) cube([inner.x + wall, o.y + 2, wall / 2 + 0.2]);   // lid groove... open front
    translate([-1, wall + inner.y / 2 - usb.x / 2, wall + 3]) cube([wall + 2, usb.x, usb.y]);  // USB opening
    if (sma) translate([o.x - wall - 1, o.y / 2, o.z - 8]) rotate([0, 90, 0]) cylinder(d = 6.6, h = wall + 2);  // SMA bulkhead
    for (x = [8 : 6 : o.x - 8]) translate([x, -1, wall + inner.z * 0.4]) cube([2.5, wall + 2, inner.z * 0.35]);  // vents
  }
}
module lid() { translate([0, 0, 0]) cube([inner.x + wall - 0.4, o.y, wall / 2]); }
if (part != "lid") box();
if (part != "box") translate([0, o.y + 8, 0]) lid();
