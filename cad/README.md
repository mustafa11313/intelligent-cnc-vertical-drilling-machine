# Mechanical (CAD) review, measured from the original assembly

> **The full upgrade** (every improvement modelled in the original assembly's coordinates, clash-checked) is in
> [UPGRADE.md](UPGRADE.md). This page is the review that led to it.

## How the CAD was read

SolidWorks doesn't run on Linux, so `xt/` holds a reader for the Parasolid file that SolidWorks
exported (`Parasolid/Ana_Montaj_1_6_25.x_t`, in the RAR). It is in `xt/`.

- It decodes the whole file: 122,471 entities, 41 different bodies, 135 placed parts, 5 sub-assemblies.
- It also reads the geometry of each part: holes, faces, edges and the transforms.
- Every number below is measured from that model, not read off the report drawings. The earlier
  version of this review was based on the drawings, and a few of its guesses were wrong.
  Those are corrected here.

```
xt/xt_parser.py   reads the .x_t text format (schema, all node types in this file)
xt/model.py       assembly tree, transforms, edges as polylines, holes/planes
xt/render.py      python3 render.py <file.x_t> ..   -> assembly_views.png, assembly_parts.csv
xt/feats.py       python3 feats.py <file.x_t> "X Eksen Somunu"  -> holes and faces of a part
```

`assembly_views.png` shows the model from three sides plus a 3D view, coloured by the axis
that moves each part. `assembly_parts.csv` lists every placed body with its position in mm.

**Coordinates.** These are the SolidWorks world axes. Y is up. The table moves along X. The spindle carriage
moves along world Z, which is machine Y. The spindle moves along world Y, which is machine Z.

## What the machine actually is

| Item | From the CAD |
|---|---|
| Overall size | 472 × 513 × 390 mm (X × height × depth), including motors |
| Base | 2 × 45×90 sigma profiles, 400 mm long, 266.5 mm apart. Two 5 mm end plates (`Arka_Kapak-Son`, `On_Kapak-Son`) |
| X axis (table) | 2 × HGR15 rail, 400 mm. **One** HGH15CA block per rail. Table 200 × 300 × 10 mm, with a pocket **150 × 200 × 4 mm** (R5 corners) |
| X drive | Tr8x2 screw, **255 mm**, motor at the back, **front end free** at X = +78 (122 mm short of the front plate) |
| Gantry | 10 mm steel side plates (`Yan_Plaka_1/2`) carry a 45×90 cross profile at 325–415 mm height |
| Y axis (carriage) | **One** HGR15 rail (306 mm) with **one** HGW15CC block. The whole Z/spindle unit hangs from it |
| Y drive | Tr8x2, 310 mm. Motor end in a flexible beam coupler, far end turned to Ø6 in 626 bearings in `Yan_Plaka_2` |
| Z axis | 2 × HGR15 rail (150 mm), 1 × HGW15CC each, Tr8x2 125 mm. The screw hangs from the motor coupler with **no bearing** |
| Spindle | HMA85 square-flange spindle with ER16 collet. Axis is 98 mm in front of the cross profile |
| Couplers | 20 × 26 mm beam (slotted) couplers 5→8 on all three axes. If the prototype has solid ones, use these |

### Travel (mechanical, from part positions)

| Axis | Travel | What stops it |
|---|---|---|
| X | **232 mm** (table centre −154 to +78 relative to the model pose) | back: nut block reaches the coupler. Front: brass nut reaches the end of the 255 mm screw |
| Y | **191 mm** | the 120 mm carriage plate meets the side plates (5.5 mm gaps either side) |
| Z | **67 mm** (58 up, 9 down) | up: spindle top reaches the motor plate. Down: the Z blocks are 9 mm from the ends of their rails |

- **Work area.** The whole 200 mm table length can pass under the spindle in X. In Y the spindle covers
  191 of the table's 300 mm. The 150 × 200 pocket sits inside that, about 4 mm short at each Y end. So the
  drillable area is roughly **200 × 190 mm**.
- **App defaults.** The app and GRBL defaults are set to 225 / 185 / 60 mm, which leaves about 5 mm of margin
  (`app/config.py`, `firmware/grbl/README.md`).
- **Z at the bottom.** Nothing hard stops Z at the bottom. If Z is driven 9 mm below the model's pose, the Z
  blocks run off their rails and drop their balls. That is one more reason for a Z limit switch or soft limits.

## Problems found, most important first

### 1. A standard PCB bit can't reach the board
- In the model, Z is near its lowest point and a **127 mm long Ø10 jobber drill** reaches 1.3 mm into the
  table.
- With Z fully down, the collet face is **57 mm above the table top**.
- A standard PCB bit is 38 mm long with a 1/8" shank. With about 20 mm sticking out of the collet, its tip stops
  **about 37 mm above the table**, so it can never reach a PCB lying on the table.
- Check this on the machine: jog Z to the bottom and measure from the collet face to the table.
- **Fix now:** `pcb_riser_200x200x45.step`. It is a 45 mm riser bolted to the table with 4 × M5×55 into holes tapped
  at (±90, ±90) mm from the table centre. That position is outside the pocket and clear of the carriage screws.
  With 20 mm of bit out of the collet:
  - at the bottom of Z, the tip reaches 9 mm below the top of a 1.6 mm board, so there is room for the drilling depth;
  - at the top of Z, the tip clears the board by about 58 mm.
- **Proper fix later:** lengthen `Tabla2` by 40 mm downward and move the Z rails and screw down with it. This needs a
  165 mm Z screw.

### 2. The X lead screw is free at the front and its nut works at the tip
- The X screw is 255 mm long and ends in the air at X = +78. In the modelled position the brass nut is already
  at the free end. Every hole near the front of the table is drilled with the nut on the unsupported tip,
  where the screw whips most.
- **Fix:** `x_front_plate_KFL08.step`.
  - It is a copy of `On_Kapak-Son` with the same outline and the same two Ø10.2 profile holes.
  - It adds a Ø16 clearance hole on the screw axis and 2 × Ø5.5 holes 37 mm apart for a **KFL08** flange bearing
    on the outer face. Long axis horizontal, because the plate is only 45 mm tall and the axis is 15 mm above its
    lower edge.
  - The screw axis is 1.75 mm off the plate centre. The part already accounts for that.
- **Screw:** buy a **395 mm Tr8x2** screw and clamp it in the KFL08 with a lock collar. The front bearing then takes
  the drilling thrust instead of the motor. X travel grows to about 320 mm (limited by the blocks reaching the
  rail ends), so keep the soft limit.

### 3. The Y carriage rides on one block on one rail
- The spindle axis is **84 mm** in front of the Y block and the tip is **246 mm** below it. Drilling thrust and
  the spindle's weight twist the single HGW15CC block about the rail axis.
- Forces in PCB drilling are small (5–15 N), so this is about stiffness and repeatability, not strength.
  A single block's own preload decides how much the bit tilts.
- **Fix, in order of benefit:**
  1. Add a second HGR15 rail on the same profile face. The 90 mm face has slots at 22.5 and 67.5 mm, so the
     rails go 45 mm apart. Use **HGH15CA** blocks (34 mm wide), which fit at that spacing where HGW15CC (47 mm)
     do not. That stops the roll.
  2. Use 2 blocks in tandem on the existing rail. This needs a carriage plate of at least 125 mm and costs
     about 10 mm of Y travel. It stops pitch and yaw but not roll.

### 4. The Z screw hangs on the motor bearing
- The 125 mm Z screw goes from the coupler straight down with no bearing at either end. The spindle's weight
  and every drilling thrust pass through the coupler into the stepper's small front bearing. Over time Z0 drifts
  and the motor bearing wears.
- **Fix:** a KFL08 under the motor plate (`Arka Kapak`) with the screw clamped in it, so the bearing takes the
  thrust and the coupler only drives. A shorter coupler or a slightly longer screw makes room for it.
  The Y axis already does this right with its 626 bearings.

### 5. Wrong screws in the X carriages
- The table is bolted to the two **HGH15CA** blocks with **M5×12** screws in Ø5.5 counterbored holes. The
  HGH15CA mounting threads are **M4**: the block model has Ø4 holes, which matches HIWIN's catalogue.
- Use **M4×12** screws. If the table is already made, the Ø5.5/Ø10 counterbores are fine for M4 with a washer.
- (The Y/Z HGW15CC blocks are M5, so their M5 screws are correct.)

### 6. Backlash in the brass nuts
All three axes use the same Ø22-flange brass Tr8x2 nut. These have 0.1–0.3 mm of play.
- The software already approaches every hole from −X/−Y, which cancels the play's effect on hole position.
- For Y and Z, `nut_block_antibacklash_Tr8.step` is the original nut block with its real dimensions:
  - 40 × 25 × 30 mm
  - Ø23 × 5 mm flange recess
  - 4 × M3 holes on a Ø16 circle
  - 4 × M4 mounting holes on 30 × 15
  - the bore opened to Ø12 for a spring-loaded POM anti-backlash nut
- The X nut block (`X Eksen Somunu`, 30 × 61.5 × 40) has the same nut interface. Open its Ø11 bore to Ø12 the
  same way.

### 7. No limit switches
- With 5.5 mm gaps between the table and the side plates, and Z blocks able to run off their rails, a wrong
  coordinate is expensive.
- `limit_sensor_bracket_M12.step` holds an M12 inductive sensor on any profile slot (M8 T-nut, ±5 mm adjust).
  The wiring is in `../electronics/README.md`.

### 8. Smaller points
- **Dust.** FR4 dust is glass fibre. Fit a brush-skirt dust shoe around the ER16 nut, which is Ø28 at the
  bottom of the spindle (`ER 161`).
- **Cables.** X and Z cables flex with every move. Use drag chain.
- **Table guidance.** One block per rail on the table is acceptable for drilling forces. Check the table for
  rocking with a dial gauge at its four corners.

## Corrections to the earlier review (drawing-based)

| Earlier estimate | The CAD shows |
|---|---|
| Table pocket 190 × 140 × 3 | **150 × 200 × 4**, R5 corners |
| The **Y** screw ends free at the front | Y is supported (626 bearings). It's the **X** screw that is free |
| Nut block 40 × 25 with the mounting pattern guessed | 40 × 25 × 30 with 4 × M4 on **30 × 15**, Ø23 × 5 recess |
| Rigid couplers | Beam couplers in the CAD (check what's on the prototype) |
| Add a 608 floating support on the profile | Replaced by the KFL08 front plate, which fits the real geometry |

## Parts in `step/`

| File | What | Material |
|---|---|---|
| `pcb_riser_200x200x45.step` | lifts the PCB into reach of short PCB bits, 4 × M5, 2 × Ø3 pin holes | MDF or aluminium |
| `x_front_plate_KFL08.step` | replaces `On_Kapak-Son`, adds the KFL08 front bearing for the X screw | 5 mm steel (as original) |
| `nut_block_antibacklash_Tr8.step` | Y/Z nut block for a spring anti-backlash nut | aluminium 6061 |
| `spoilboard_insert_150x200.step` | backer that fills the table pocket (for long bits / without the riser) | 4 mm MDF / FR4 |
| `limit_sensor_bracket_M12.step` | M12 sensor bracket, M8 T-slot | 4 mm aluminium angle or PETG |

Regenerate the parts with `pip install cadquery && python3 parts.py`, and the preview with
`python3 preview.py`. Import them into SolidWorks with File → Open → STEP.

## Parts to buy

| Qty | Part | For |
|---|---|---|
| 1 | Tr8x2 lead screw, 395 mm (or 400 mm cut) | X, with front support |
| 2 | KFL08 flange bearing + 8 mm lock collars | X front, Z top |
| 1 | HGR15 rail ~306 mm + 1 × HGH15CA block (or a 2nd HGW15CC for tandem) | Y stiffness |
| 8 | M4×12 ISO 4762 | table to HGH15CA blocks |
| 2–3 | Tr8x2 anti-backlash spring nut (POM, flange Ø22, 4 holes on Ø16) | Y, Z (X) |
| 3 | LJ12A3-4-Z/BX + steel targets | limits / homing |
| 1 | 45 mm MDF or aluminium plate 200 × 200 (or 2 × 22 mm MDF glued) | riser |
| 1 | drag chain 10 × 15, ~1 m; dust shoe | cables, dust |
