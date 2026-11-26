// Z-bracket for mounting a framed solar panel to a roof, rack or wall. CC0.
// frame = panel frame thickness (30, 35 or 40 mm are common). Print 4, PETG/ASA, 100% infill.
frame = 35; wid = 30; thick = 5; flange = 30; bolt = 6.5;
$fn = 48;
difference() {
  union() {
    cube([flange, wid, thick]);                                  // panel side
    translate([flange - thick, 0, 0]) cube([thick, wid, frame + thick]);
    translate([flange - thick, 0, frame]) cube([flange + thick, wid, thick]);  // rack side
  }
  translate([flange / 2, wid / 2, -1]) cylinder(d = bolt, h = thick + 2);
  translate([flange + flange / 2, wid / 2, frame - 1]) cylinder(d = bolt, h = thick + 2);
}
