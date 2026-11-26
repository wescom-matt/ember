// N-cell 18650 holder / spacer grid (for packs with spot-welded strips or wire). CC0.
cells_x = 4; cells_y = 1; cell = 18.6; pitch = 19.5; h = 12; floor_h = 1.6;
$fn = 64;
difference() {
  translate([-pitch / 2 - 2, -pitch / 2 - 2, 0]) cube([cells_x * pitch + 4, cells_y * pitch + 4, h]);
  for (i = [0 : cells_x - 1], j = [0 : cells_y - 1]) {
    translate([i * pitch, j * pitch, floor_h]) cylinder(d = cell + 0.4, h = h);
    translate([i * pitch, j * pitch, -1]) cylinder(d = cell - 6, h = h);   // contact window
  }
}
