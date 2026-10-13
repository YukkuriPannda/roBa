"""PLA strength screen for the trackball bearing case (doc/pla-strength-check.md).

Pure Python, no FreeCAD. Reads design values from bearing_case.py DEFAULTS
(read-only, regex) and from generated/build.json, computes hand-check stresses,
and writes generated/strength_check.json. Every material strength used here is
a PROVISIONAL, UNSOURCED placeholder for comparison only; it is not an allowable.
Load values are ASSUMPTIONS. Output verdict is HOLD unless every condition in
the doc is fixed (printer, PLA lot, load, same-condition allowables).

All lengths mm, stresses MPa, forces N.
"""
import json, math, re
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'generated' / 'strength_check.json'

def read_defaults():
    src = (HERE / 'bearing_case.py').read_text(encoding='utf-8')
    block = src[src.index('DEFAULTS = {'):src.index('}', src.index('DEFAULTS = {'))]
    vals = {}
    for k, v in re.findall(r"'([A-Za-z0-9]+)'\s*:\s*(-?[0-9.]+)", block):
        vals[k] = float(v)
    return vals

P = read_defaults()
build = json.loads((HERE / 'generated' / 'build.json').read_text(encoding='utf-8'))
verif = json.loads((HERE / 'generated' / 'verification.json').read_text(encoding='utf-8'))

# ---- geometry (from DEFAULTS) ----
R = P['BallDiameter'] / 2                       # 17.0 ball radius
RV = R + P['BallClearance']                     # 17.4 ball void radius
RO = P['BearingOuterDiameter'] / 2              # 2.0 bearing OD radius
D = R + RO                                      # 19.0 ball centre -> bearing centre
RP = P['PilotDiameter'] / 2                     # 1.075 pilot bore radius
HALF = P['BearingWidth'] / 2                    # 1.0
SP = P['SpacerThickness']                       # 0.4
A_FACE = HALF + SP                              # 1.4 boss face offset from bearing centre
RB = P['BossRadius']                            # 3.5 boss outer radius
LB = P['BossLength']                            # 2.5 boss height
POLAR = P['Support1Polar']                      # 61 deg
DP = P['PilotDiameter']
SCREW_D = P['ScrewDiameter']                    # 2.5
CONTACT_OD = P['InnerRingContactDiameter']      # 2.9 metal spacer
CONTACT_ID = 2.60                               # spacer bore 2*1.30 (hardware(): cylinder(1.30))
L_ENG = (-HALF - SP + P['ScrewLength']) - (HALF + SP)  # screw tip t=3.6 minus boss face t=1.4 -> 2.2
assert abs(L_ENG - 2.2) < 1e-9, L_ENG

# ---- ball-side web ----
web_analytic = (D - RP) - math.sqrt(RV * RV - A_FACE * A_FACE)
assert abs(web_analytic - build['ball_side_web_mm']) < 1e-6, (web_analytic, build['ball_side_web_mm'])

def web_thickness(theta):
    """Wall from pilot bore point at angle theta (0 = ball-facing) to void, boss face plane."""
    d = math.hypot(D - RP * math.cos(theta), RP * math.sin(theta))
    return d - math.sqrt(RV * RV - A_FACE * A_FACE)

def neck_width(t_limit):
    """Arc length on the pilot bore where web thickness <= t_limit (numerical)."""
    n = 4000; total = 0.0; prev = None
    for i in range(n + 1):
        th = math.pi * i / n
        inside = web_thickness(th) <= t_limit
        if inside and prev is not None:
            total += RP * (math.pi / n)
        prev = inside
    return total

# neck_width integrates theta in [0, pi]; the thin region is symmetric about theta=0,
# so the full neck arc is twice the one-sided arc.
B_NECK_1MM = min(2 * neck_width(1.0), 2 * RP * math.pi)
T_MIN = web_analytic

# ---- support loads ----
share = 1 / (3 * math.cos(math.radians(POLAR)))   # equal triad, vertical load
assert abs(share - verif['checks']['vertical_load_distribution']['evidence']['relative_reactions_per_unit_downward_load'][0]) < 1e-6
FORCES = [5.0, 10.0, 20.0]                       # ASSUMED ball press (N), not measured
PRELOADS = [30.0, 50.0, 100.0]                   # ASSUMED screw preload (N), not measured

# ---- provisional reference strengths (NOT sourced; comparison only) ----
REF = {
    'tensile_in_plane': 50.0,   # MPa, generic PLA order of magnitude, assumed
    'tensile_z': 25.0,          # MPa, assumed 50% of in-plane for layer-normal
    'shear_in_plane': 30.0,     # MPa, assumed
    'shear_layer': 20.0,        # MPa, assumed
    'compressive': 60.0,        # MPa, assumed
}
SF_TARGET = 2.0                 # doc: initial target SF >= 2 (project provisional)

def sf(allow, stress):
    return allow / stress if stress > 0 else float('inf')

results = {'checks': {}, 'inputs': {}, 'assumptions': [], 'reference_strengths_provisional': REF}

results['inputs'] = {
    'ball_radius_mm': R, 'ball_void_radius_mm': RV, 'bearing_centre_distance_mm': D,
    'pilot_radius_mm': RP, 'boss_face_offset_mm': A_FACE, 'boss_radius_mm': RB,
    'boss_length_mm': LB, 'support_polar_deg': POLAR, 'support_azimuth_deg': [P['Support1Azimuth'], P['Support2Azimuth'], P['Support3Azimuth']],
    'screw_engagement_in_boss_mm': L_ENG, 'screw_diameter_mm': SCREW_D,
    'spacer_contact_od_mm': CONTACT_OD, 'spacer_contact_id_mm': CONTACT_ID,
    'ball_side_web_analytic_mm': web_analytic, 'ball_side_web_neck_width_le1mm_mm': B_NECK_1MM,
    'support_share_per_unit_load': share,
    'print': {'nozzle_mm': 0.4, 'layer_mm': 0.2, 'walls_printed_by_PRINT_md': 3,
              'walls_doc_baseline': 4, 'top_bottom_min_mm': 1.0, 'infill': '30-40% gyroid',
              'orientation': 'print Z = source Z; bearing/screw axes horizontal (tilt 0)',
              'printer': 'UNKNOWN', 'pla_product_lot': 'UNKNOWN', 'drying': 'UNKNOWN',
              'temperature': '200-210 C nozzle / 50-60 C bed per PRINT.md (unverified profile)'},
}
results['assumptions'] = [
    'Ball press force: 5 / 10 / 20 N downward on ball, ASSUMED (no user load defined in repo). Sensitivity only.',
    'Screw preload 30 / 50 / 100 N, ASSUMED (no torque or preload measurement).',
    'PLA strengths in REF are provisional placeholders, not same-condition test data; per doc they are comparison values only.',
    'Bearing reaction taken as vertical-load equal triad: each support reaction = share * F (verified in verification.json).',
    'Web model: thin cantilever of thickness t_min, neck width b where t<=1.0 mm, fixed at shell end, load N distributed over L_eng. Crude; real web is curved and partly supported by the boss. Not FEM.',
    'Boss root model: annular cantilever (R_out 3.5, bore 1.075), point load N at boss height 2.5 mm. Crude.',
    'Thread stress from screw-pilot interference is NOT computed: no thread-form or fit data. Requires coupon test.',
    'Drop/handling loads: NOT computed (no impact energy or height defined).',
    'Temperature and creep: NOT evaluated (no service temperature or life target defined).',
]

# ---- Check 1: support reactions ----
rows = []
for F in FORCES:
    rows.append({'F_ball_N': F, 'N_per_support_N': share * F})
results['checks']['1_support_reaction'] = {'formula': 'N = F / (3 cos(polar))', 'rows': rows,
    'note': 'Equal triad; horizontal components cancel for symmetric vertical load.'}

# ---- Check 2: boss-face crush under metal spacer (preload) ----
A_CONTACT = math.pi * (CONTACT_OD ** 2 - CONTACT_ID ** 2) / 4
rows = []
for Fp in PRELOADS:
    s = Fp / A_CONTACT
    rows.append({'F_pre_N': Fp, 'stress_MPa': s, 'SF_vs_provisional_compressive': sf(REF['compressive'], s)})
results['checks']['2_boss_face_crush_spacer'] = {
    'formula': 'sigma = F_pre / A, A = pi/4 (OD^2 - ID^2) of metal spacer contact annulus',
    'A_contact_mm2': A_CONTACT, 'rows': rows,
    'layer_direction': 'boss face is perpendicular to the horizontal screw axis, i.e. a vertical plane; the compressive load runs along the axis, parallel to layer planes (in-plane direction)',
    'note': 'Largest preload-dependent stress; preload is not defined, so this sets a preload ceiling.'}

# ---- Check 3: screw thread shear in pilot (pull-out, axial) ----
A_SHEAR = math.pi * DP * L_ENG
rows = []
for Fp in PRELOADS:
    t = Fp / A_SHEAR
    rows.append({'F_pre_N': Fp, 'shear_MPa': t, 'SF_vs_provisional_shear': sf(REF['shear_in_plane'], t)})
results['checks']['3_screw_pullout_shear'] = {
    'formula': 'tau = F_pre / (pi * d_pilot * L_eng)', 'A_shear_mm2': A_SHEAR, 'rows': rows,
    'layer_direction': 'shear surface is cylindrical about screw axis (horizontal); layer planes cut it, so shear crosses layer interfaces on the thread flank',
    'note': 'Pull-out in an 8 mm long boss is governed by layer shear if the thread crosses layers; thread-form stress not computed.'}

# ---- Check 4: ball-side web bending (governing candidate) ----
M_FACTOR = L_ENG / 2   # uniform load over L_eng, cantilever root moment = N*L/2
rows = []
for F in FORCES:
    N = share * F
    M = N * M_FACTOR
    s = 6 * M / (B_NECK_1MM * T_MIN ** 2)
    s_point = 6 * (N * L_ENG) / (B_NECK_1MM * T_MIN ** 2)
    rows.append({'F_ball_N': F, 'N_N': N, 'M_root_Nmm': M, 'stress_MPa_uniform': s,
                 'SF_vs_provisional_in_plane_tension': sf(REF['tensile_in_plane'], s),
                 'stress_MPa_point_load_at_tip': s_point,
                 'SF_point_load': sf(REF['tensile_in_plane'], s_point)})
# allowable ball press for SF target, uniform model
sigma_allow = REF['tensile_in_plane'] / SF_TARGET
N_allow = sigma_allow * B_NECK_1MM * T_MIN ** 2 / (6 * M_FACTOR)
F_allow = N_allow / share
results['checks']['4_ball_side_web_bending'] = {
    'formula': 'sigma = 6 M / (b t^2), M = N L/2 (uniform) or N L (tip)',
    'b_mm': B_NECK_1MM, 't_min_mm': T_MIN, 'L_mm': L_ENG,
    'rows': rows,
    'allowable_ball_press_for_SF2_provisional_N': F_allow,
    'allowable_N_per_support_N': N_allow,
    'layer_direction': 'bending stress acts along the screw/bearing axis (horizontal), i.e. in the layer plane; the web normal has a vertical component cos(61)=0.485 so layer interfaces cut the web thickness at an angle',
    'line_count': {'web_thickness_mm': T_MIN, 'nozzle_0.4_lines': T_MIN / 0.4,
                   'note': 'thickness is between one and two 0.4 mm lines; 3 vs 4 perimeter setting does not add lines to this web'},
}

# ---- Check 5: boss root bending and shear (annulus) ----
ri = RP; ro = RB
A_ROOT = math.pi * (ro ** 2 - ri ** 2)
Z_ROOT = math.pi * (ro ** 4 - ri ** 4) / (4 * ro)
rows = []
for F in FORCES:
    N = share * F
    M = N * LB
    rows.append({'F_ball_N': F, 'N_N': N, 'M_root_Nmm': M, 'sigma_bending_MPa': M / Z_ROOT,
                 'SF_in_plane_tension': sf(REF['tensile_in_plane'], M / Z_ROOT),
                 'tau_mean_layer_MPa': (N * math.cos(math.radians(POLAR))) / A_ROOT,
                 'SF_layer_shear': sf(REF['shear_layer'], (N * math.cos(math.radians(POLAR))) / A_ROOT)})
results['checks']['5_boss_root_bending'] = {
    'formula': 'sigma = M/Z, Z = pi(Ro^4-Ri^4)/(4Ro); tau = V/A (vertical component only)',
    'A_mm2': A_ROOT, 'Z_mm3': Z_ROOT, 'rows': rows,
    'layer_direction': 'bending stress is along the boss axis (horizontal, in layer plane); interlayer shear is the vertical component only',
    'note': 'Root bending is low; not governing under these assumptions.'}

# ---- Check 6: wall thickness vs doc rule (line width 0.4 mm) ----
LW = 0.4
wall = {
    'ball_side_web_mm': T_MIN, 'ball_side_web_lines': T_MIN / LW, 'ball_side_web_rule_lines': 4, 'ball_side_web_rule_mm': 4 * LW,
    'boss_outer_radial_mm': RB - RP, 'boss_outer_lines': (RB - RP) / LW, 'boss_root_rule_lines': 6, 'boss_root_rule_mm': 6 * LW,
    'boss_outer_with_3_walls_each_side_mm': 2 * 3 * LW, 'boss_outer_with_4_walls_each_side_mm': 2 * 4 * LW,
    'floor_mm': P['BallSideWebFloor'], 'target_mm': P['MinBallSideWeb'],
}
results['checks']['6_wall_thickness_rule'] = wall

# ---- Check 7: not computed ----
results['checks']['7_not_computed'] = {
    'screw_thread_radial_stress_in_pilot': 'no fit/thread model; test coupon required',
    'layer_normal_tension_in_web': 'needs web normal stress from fit model; test required',
    'drop_handling': 'no impact definition',
    'creep_fatigue_temperature': 'no service temperature or life target',
    'global_minimum_thickness': 'untested (verification.json: global_minimum_not_measured)',
}

# ---- Verdict ----
results['verdict'] = 'HOLD'
results['verdict_reasons'] = [
    'Printer model, PLA product and lot, drying, and profile version are not fixed (doc requires them).',
    'No user load is defined; all loads here are assumptions. Finger press is assumed 5/10/20 N.',
    'No same-condition allowable exists; the PLA strengths used are provisional placeholders, so only comparisons are valid.',
    'Ball-side web is 0.58 mm, below the 1.2 mm floor and the 1.6 mm target. Under the provisional crude model it fails SF 2 at a ball press above about %.1f N.' % F_allow,
    'Boss-face crush under metal spacer is high at 50-100 N preload; preload not defined.',
    'Boss root bending and screw shear are low under the assumed loads, not governing.',
    'No physical print, fit, or drop/cycle test has been done.',
]
results['governing_failure_mode'] = 'ball-side web bending (thin neck between pilot bore and ball void), with boss-face crush as a preload ceiling'

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
print(json.dumps({'verdict': results['verdict'], 'web_mm': web_analytic, 'b_neck_mm': B_NECK_1MM,
                  'F_allow_web_SF2_N': F_allow, 'A_contact_mm2': A_CONTACT, 'A_shear_mm2': A_SHEAR,
                  'Z_root_mm3': Z_ROOT}, indent=2))
