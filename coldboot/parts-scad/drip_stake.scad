// Ground stake that holds 1/4" (6-7 mm OD) drip tubing or a dripper. CC0.
tube_od = 6.5; len = 120;
$fn = 40;
linear_extrude(3) polygon([[-4, 0], [4, 0], [4, len - 14], [0, len + 6], [-4, len - 14]]);   // flat stake
translate([0, len - 8, 0]) rotate([0, 0, 0]) linear_extrude(3) polygon([[-8, 0], [8, 0], [0, 14]]);
difference() {
  translate([0, 0, 0]) cylinder(d = tube_od + 5, h = 10);
  translate([0, 0, -1]) cylinder(d = tube_od + 0.3, h = 12);
  translate([-tube_od * 0.35, 0, -1]) cube([tube_od * 0.7, tube_od, 12]);
}
