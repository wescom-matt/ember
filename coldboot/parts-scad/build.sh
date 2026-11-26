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
openscad -q -o stl/bnc_mount_9.7mm.stl -D 'hole=9.7' sma_mount.scad
openscad -q -o stl/dipole_center_so239.stl dipole_center.scad
openscad -q -o stl/end_insulator_70mm.stl end_insulator.scad
openscad -q -o stl/coax_strain_relief_rg58.stl -D 'coax=5' coax_strain_relief.scad
openscad -q -o stl/coax_strain_relief_rg8x.stl -D 'coax=6.1' coax_strain_relief.scad
openscad -q -o stl/coax_strain_relief_lmr400.stl -D 'coax=10.3' coax_strain_relief.scad
openscad -q -o stl/mast_clamp_25mm.stl -D 'pipe=25' mast_clamp.scad
openscad -q -o stl/mast_clamp_32mm.stl -D 'pipe=32' mast_clamp.scad
openscad -q -o stl/mast_clamp_42mm.stl -D 'pipe=42' mast_clamp.scad
openscad -q -o stl/element_holder_20sq_4.8mm.stl -D 'boom=20' -D 'element=4.8' element_holder.scad
openscad -q -o stl/element_holder_25round_6.35mm.stl -D 'boom=25' -D 'round_boom=true' -D 'element=6.35' element_holder.scad
openscad -q -o stl/ht_holder_uv5r_bff8.stl -D 'width=59' -D 'depth=33' ht_holder.scad
openscad -q -o stl/ht_holder_uv9r_plus.stl -D 'width=59' -D 'depth=38' ht_holder.scad
openscad -q -o stl/ht_holder_anytone_d868uv.stl -D 'width=63' -D 'depth=37' ht_holder.scad
openscad -q -o stl/mic_hanger_keyhole.stl mic_hanger.scad
openscad -q -o stl/rig_tilt_wedge.stl rig_tilt_wedge.scad
openscad -q -o stl/drip_coupler_4mm.stl -D 'type="coupler"' drip_fitting.scad
openscad -q -o stl/drip_elbow_4mm.stl -D 'type="elbow"' drip_fitting.scad
openscad -q -o stl/drip_tee_4mm.stl -D 'type="tee"' drip_fitting.scad
openscad -q -o stl/drip_cross_4mm.stl -D 'type="cross"' drip_fitting.scad
openscad -q -o stl/drip_stake_6.5mm.stl drip_stake.scad
openscad -q -o stl/battery_18650_holder_4x1.stl -D 'cells_x=4' battery_18650_holder.scad
openscad -q -o stl/battery_18650_holder_4x2.stl -D 'cells_x=4' -D 'cells_y=2' battery_18650_holder.scad
openscad -q -o stl/solar_bracket_35mm.stl -D 'frame=35' solar_panel_bracket.scad
openscad -q -o stl/solar_bracket_40mm.stl -D 'frame=40' solar_panel_bracket.scad
openscad -q -o stl/esp32_devkit_30pin_case.stl -D 'board=[51.5,28.5]' esp32_case.scad
openscad -q -o stl/esp32_devkit_38pin_case.stl -D 'board=[55,28]' esp32_case.scad
openscad -q -o stl/heltec_v3_case_sma.stl -D 'board=[50.2,25.5]' -D 'antenna=6.6' esp32_case.scad
openscad -q -o stl/ttgo_lora32_case_sma.stl -D 'board=[61,26]' -D 'antenna=6.6' esp32_case.scad
openscad -q -o stl/wemos_d1_mini_case.stl -D 'board=[34.2,25.6]' -D 'above=8' esp32_case.scad
