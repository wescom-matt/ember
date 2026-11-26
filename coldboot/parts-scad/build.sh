#!/usr/bin/env bash
# Rebuild the STLs from the .scad files (needs openscad).
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p stl
openscad -q -o stl/knob_25mm_6mmD.stl -D 'dia=25' knob.scad
openscad -q -o stl/knob_35mm_6mmD.stl -D 'dia=35' knob.scad
openscad -q -o stl/knob_25mm_6.35round_setscrew.stl -D 'dia=25' -D 'shaft_d=6.55' -D 'flat_d=0' knob.scad
openscad -q -o stl/hose_barb_6-8mm.stl -D 'id_a=6' -D 'id_b=8' hose_barb.scad
openscad -q -o stl/hose_barb_8-10mm.stl -D 'id_a=8' -D 'id_b=10' hose_barb.scad
openscad -q -o stl/hose_barb_10-13mm.stl -D 'id_a=10' -D 'id_b=13' hose_barb.scad
openscad -q -o stl/hose_barb_13-19mm.stl -D 'id_a=13' -D 'id_b=19' hose_barb.scad
openscad -q -o stl/cable_clip_4mm.stl -D 'cable=4' cable_clip.scad
openscad -q -o stl/cable_clip_6mm.stl -D 'cable=6' cable_clip.scad
openscad -q -o stl/cable_clip_8mm.stl -D 'cable=8' cable_clip.scad
openscad -q -o stl/cable_clip_10mm.stl -D 'cable=10' cable_clip.scad
openscad -q -o stl/l_bracket_30.stl -D 'size=30' l_bracket.scad
openscad -q -o stl/l_bracket_40.stl -D 'size=40' l_bracket.scad
openscad -q -o stl/l_bracket_50.stl -D 'size=50' l_bracket.scad
openscad -q -o stl/project_box_60x35x25.stl -D 'inner=[60, 35, 25]' project_box.scad
openscad -q -o stl/project_box_70x40x30.stl -D 'inner=[70, 40, 30]' project_box.scad
openscad -q -o stl/project_box_100x60x40.stl -D 'inner=[100, 60, 40]' project_box.scad
openscad -q -o stl/sma_mount_6.6mm.stl -D 'hole=6.6' sma_mount.scad
openscad -q -o stl/so239_mount_16mm.stl -D 'hole=16' sma_mount.scad
openscad -q -o stl/belt_clip_45mm.stl -D 'belt=45' belt_clip.scad
openscad -q -o stl/belt_clip_38mm.stl -D 'belt=38' belt_clip.scad
openscad -q -o stl/drill_guide.stl  drill_guide.scad
openscad -q -o stl/radio_stand_36mm.stl -D 'slot=36' radio_stand.scad
openscad -q -o stl/radio_stand_42mm.stl -D 'slot=42' radio_stand.scad
